"""JSONL supervisor and per-run worker for Desktop M2."""
from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, TextIO

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent import AgentLoop, ConversationRunner  # noqa: E402
from datasets import DatasetRegistry  # noqa: E402
from observability import TraceCollector  # noqa: E402
from skill_runtime import SkillRegistry, SkillRuntime  # noqa: E402
from tools import build_default_registry  # noqa: E402
from workflow import AnalysisNode, CalcNode, ChatNode, MemoryRecallNode, RuleRouter, Workflow  # noqa: E402

PROTOCOL_VERSION = 1
MAX_LINE_BYTES = 1024 * 1024
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
COMMAND_TYPES = frozenset({"run.start", "run.cancel"})
TERMINAL_TYPES = frozenset({"run_completed", "run_failed", "run_cancelled", "approval_required"})


class ProtocolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _record(value: Any) -> bool:
    return isinstance(value, dict)


def validate_command(value: Any) -> dict[str, Any]:
    if not _record(value):
        raise ProtocolError("invalid_message", "JSONL message must be an object")
    if value.get("protocol_version") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported_protocol", "protocol_version must be 1")
    message_type = value.get("type")
    if message_type not in COMMAND_TYPES:
        raise ProtocolError("unknown_message_type", "unknown command type")
    request_id = value.get("request_id")
    if not isinstance(request_id, str) or not ID_PATTERN.fullmatch(request_id):
        raise ProtocolError("invalid_request_id", "request_id is invalid")
    payload = value.get("payload")
    if not _record(payload):
        raise ProtocolError("invalid_payload", "payload must be an object")
    if message_type == "run.start":
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip() or len(message.strip()) > 4000:
            raise ProtocolError("invalid_run_input", "message must contain 1 to 4000 characters")
        thread_id = value.get("thread_id")
        if thread_id is not None and (
            not isinstance(thread_id, str) or not ID_PATTERN.fullmatch(thread_id)
        ):
            raise ProtocolError("invalid_thread_id", "thread_id is invalid")
    else:
        run_id = value.get("run_id")
        if not isinstance(run_id, str) or not ID_PATTERN.fullmatch(run_id):
            raise ProtocolError("invalid_run_id", "run_id is invalid")
    return value


class JsonlWriter:
    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self.lock = threading.Lock()

    def write(self, value: dict[str, Any]) -> None:
        encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
        with self.lock:
            self.stream.write(encoded + "\n")
            self.stream.flush()


def envelope(
    message_type: str,
    *,
    request_id: str | None,
    run_id: str | None,
    thread_id: str | None,
    trace_id: str | None,
    sequence: int,
    payload: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "run_id": run_id,
        "thread_id": thread_id,
        "trace_id": trace_id,
        "sequence": sequence,
        "type": message_type,
        "payload": payload or {},
        "error": error,
    }


class BridgeModel:
    """M2 composition adapter used only when the existing Workflow selects analysis."""

    def complete(self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        del messages, tools
        return {
            "type": "final_answer",
            "content": "Desktop Runtime Bridge 已连接；数据集接入将在后续阶段提供。",
        }


def build_workflow(thread_id: str) -> Workflow:
    runtime_dir = Path(
        os.environ.get(
            "DATA_AGENT_RUNTIME_DIR",
            str(Path(tempfile.gettempdir()) / "data-analysis-agent-desktop"),
        )
    )
    datasets = DatasetRegistry(runtime_dir / thread_id)
    runner = ConversationRunner(
        AgentLoop(BridgeModel(), build_default_registry()),
        dataset_registry=datasets,
        conversation_id=thread_id,
    )
    skills = SkillRuntime(runner, SkillRegistry())
    return Workflow(
        router=RuleRouter(),
        nodes={
            "chat": ChatNode(),
            "analysis": AnalysisNode(runner, skill_runtime=skills),
            "calc": CalcNode(),
            "memory_recall": MemoryRecallNode(None),
        },
    )


class RunEmitter:
    def __init__(self, writer: JsonlWriter, request_id: str, run_id: str, thread_id: str, trace_id: str) -> None:
        self.writer = writer
        self.request_id = request_id
        self.run_id = run_id
        self.thread_id = thread_id
        self.trace_id = trace_id
        self.sequence = 0

    def emit(self, message_type: str, payload: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> None:
        self.sequence += 1
        self.writer.write(
            envelope(
                message_type,
                request_id=self.request_id,
                run_id=self.run_id,
                thread_id=self.thread_id,
                trace_id=self.trace_id,
                sequence=self.sequence,
                payload=payload,
                error=error,
            )
        )

    def trace(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("event_type", "trace_event"))
        mapped = {
            "route_selected": "route_selected",
            "skill_triggered": "skill_triggered",
            "tool_called": "tool_called",
            "tool_completed": "tool_completed",
            "approval_requested": "approval_required",
        }.get(event_type)
        if event_type in {"request_started", "request_completed"}:
            return
        payload = {
            "event_type": event_type,
            "component": event.get("component"),
            "name": event.get("name"),
            "status": event.get("status"),
            "latency_ms": event.get("latency_ms"),
            "error_code": event.get("error_code"),
            "metadata": event.get("metadata", {}),
            "runtime_sequence": event.get("sequence"),
        }
        self.emit(mapped or "trace_event", payload)


def worker(command: dict[str, Any]) -> int:
    writer = JsonlWriter(sys.stdout)
    request_id = command["request_id"]
    run_id = command["run_id"]
    thread_id = command["thread_id"]
    collector = TraceCollector(event_sink=None)
    emitter = RunEmitter(writer, request_id, run_id, thread_id, collector.trace_id)
    collector._event_sink = emitter.trace
    emitter.emit("run_started", {"status": "running"})
    delay_ms = max(0, int(os.environ.get("DESKTOP_BRIDGE_WORKER_DELAY_MS", "0")))
    if delay_ms:
        time.sleep(delay_ms / 1000)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = build_workflow(thread_id).invoke(
                {"query": command["payload"]["message"], "_trace_collector": collector}
            )
        if result["status"] == "error":
            error = result.get("error") or {"code": "runtime_error", "message": "run failed"}
            emitter.emit("run_failed", {"status": "failed"}, dict(error))
            return 1
        if result["status"] == "needs_approval":
            return 0
        emitter.emit(
            "run_completed",
            {
                "status": result["status"],
                "route": result.get("route"),
                "response": result.get("response"),
            },
        )
        return 0
    except Exception as error:
        emitter.emit(
            "run_failed",
            {"status": "failed"},
            {"code": type(error).__name__, "message": "Python Runtime execution failed"},
        )
        print(f"runtime worker failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


class RunProcess:
    def __init__(self, process: subprocess.Popen[str], command: dict[str, Any]) -> None:
        self.process = process
        self.command = command
        self.lock = threading.Lock()
        self.last_sequence = 0
        self.trace_id: str | None = None
        self.cancelled = False
        self.terminal = False
        self.responded = False


class Supervisor:
    def __init__(self) -> None:
        self.writer = JsonlWriter(sys.stdout)
        self.runs: dict[str, RunProcess] = {}
        self.runs_lock = threading.Lock()

    def serve(self) -> int:
        for raw in sys.stdin:
            if len(raw.encode("utf-8")) > MAX_LINE_BYTES:
                self._protocol_failure(None, "frame_too_large", "JSONL frame exceeds limit")
                continue
            try:
                command = validate_command(json.loads(raw))
                if command["type"] == "run.start":
                    self._start(command)
                else:
                    self._cancel(command)
            except json.JSONDecodeError:
                self._protocol_failure(None, "invalid_json", "stdin contained invalid JSON")
            except ProtocolError as error:
                request_id = None
                try:
                    candidate = json.loads(raw)
                    if isinstance(candidate, dict) and isinstance(candidate.get("request_id"), str):
                        request_id = candidate["request_id"]
                except Exception:
                    pass
                self._protocol_failure(request_id, error.code, str(error))
            except Exception as error:
                print(f"bridge command failed: {type(error).__name__}: {error}", file=sys.stderr)
                self._protocol_failure(None, "bridge_error", "Runtime bridge command failed")
        self.shutdown()
        return 0

    def _start(self, command: dict[str, Any]) -> None:
        run_id = f"run_{uuid.uuid4().hex}"
        thread_id = command.get("thread_id") or f"thread_{uuid.uuid4().hex}"
        worker_command = dict(command)
        worker_command.update({"run_id": run_id, "thread_id": thread_id})
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--worker"],
            cwd=str(REPO_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        )
        state = RunProcess(process, worker_command)
        with self.runs_lock:
            self.runs[run_id] = state
        assert process.stdin is not None
        process.stdin.write(json.dumps(worker_command, ensure_ascii=True) + "\n")
        process.stdin.close()
        threading.Thread(target=self._forward_stdout, args=(run_id, state), daemon=True).start()
        threading.Thread(target=self._forward_stderr, args=(run_id, state), daemon=True).start()

    def _forward_stdout(self, run_id: str, state: RunProcess) -> None:
        assert state.process.stdout is not None
        for raw in state.process.stdout:
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                print(f"worker {run_id} polluted stdout", file=sys.stderr)
                continue
            with state.lock:
                if state.cancelled or state.terminal:
                    continue
                sequence = message.get("sequence")
                if not isinstance(sequence, int) or sequence != state.last_sequence + 1:
                    state.terminal = True
                    self._emit_run_failure(state, "invalid_sequence", "worker event sequence is invalid")
                    state.process.terminate()
                    continue
                state.last_sequence = sequence
                state.trace_id = message.get("trace_id")
                if message.get("type") == "run_started" and not state.responded:
                    state.responded = True
                    self.writer.write(
                        envelope(
                            "response",
                            request_id=state.command["request_id"],
                            run_id=run_id,
                            thread_id=state.command["thread_id"],
                            trace_id=state.trace_id,
                            sequence=0,
                            payload={"status": "running"},
                        )
                    )
                if message.get("type") in TERMINAL_TYPES:
                    state.terminal = True
                self.writer.write(message)
        return_code = state.process.wait()
        with state.lock:
            if state.cancelled or state.terminal:
                return
            state.terminal = True
            if not state.responded:
                self.writer.write(
                    envelope(
                        "response",
                        request_id=state.command["request_id"],
                        run_id=run_id,
                        thread_id=state.command["thread_id"],
                        trace_id=state.trace_id,
                        sequence=0,
                        error={"code": "runtime_start_failed", "message": "Runtime worker exited before start"},
                    )
                )
            else:
                self._emit_run_failure(state, "runtime_process_exit", f"Runtime worker exited with code {return_code}")

    def _forward_stderr(self, run_id: str, state: RunProcess) -> None:
        assert state.process.stderr is not None
        for line in state.process.stderr:
            print(f"[{run_id}] {line.rstrip()}", file=sys.stderr, flush=True)

    def _cancel(self, command: dict[str, Any]) -> None:
        run_id = command["run_id"]
        with self.runs_lock:
            state = self.runs.get(run_id)
        if state is None:
            self.writer.write(
                envelope(
                    "response",
                    request_id=command["request_id"],
                    run_id=run_id,
                    thread_id=None,
                    trace_id=None,
                    sequence=0,
                    error={"code": "run_not_found", "message": "run does not exist"},
                )
            )
            return
        with state.lock:
            if state.terminal or state.cancelled:
                self.writer.write(
                    envelope(
                        "response",
                        request_id=command["request_id"],
                        run_id=run_id,
                        thread_id=state.command["thread_id"],
                        trace_id=state.trace_id,
                        sequence=0,
                        payload={"status": "already_finished"},
                    )
                )
                return
            state.cancelled = True
            state.process.terminate()
            try:
                state.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                state.process.kill()
                state.process.wait(timeout=1)
            state.last_sequence += 1
            self.writer.write(
                envelope(
                    "response",
                    request_id=command["request_id"],
                    run_id=run_id,
                    thread_id=state.command["thread_id"],
                    trace_id=state.trace_id,
                    sequence=0,
                    payload={"status": "cancelled"},
                )
            )
            self.writer.write(
                envelope(
                    "run_cancelled",
                    request_id=command["request_id"],
                    run_id=run_id,
                    thread_id=state.command["thread_id"],
                    trace_id=state.trace_id,
                    sequence=state.last_sequence,
                    payload={"status": "cancelled"},
                )
            )

    def _emit_run_failure(self, state: RunProcess, code: str, message: str) -> None:
        state.last_sequence += 1
        self.writer.write(
            envelope(
                "run_failed",
                request_id=state.command["request_id"],
                run_id=state.command["run_id"],
                thread_id=state.command["thread_id"],
                trace_id=state.trace_id,
                sequence=state.last_sequence,
                payload={"status": "failed"},
                error={"code": code, "message": message},
            )
        )

    def _protocol_failure(self, request_id: str | None, code: str, message: str) -> None:
        message_type = "response" if request_id else "runtime_error"
        self.writer.write(
            envelope(
                message_type,
                request_id=request_id,
                run_id=None,
                thread_id=None,
                trace_id=None,
                sequence=0,
                payload={"status": "failed"},
                error={"code": code, "message": message},
            )
        )

    def shutdown(self) -> None:
        with self.runs_lock:
            states = list(self.runs.values())
        for state in states:
            if state.process.poll() is None:
                state.process.terminate()


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        raw = sys.stdin.readline()
        try:
            command = json.loads(raw)
        except json.JSONDecodeError:
            print("worker received invalid JSON", file=sys.stderr)
            return 2
        return worker(command)
    supervisor = Supervisor()
    signal.signal(signal.SIGTERM, lambda *_args: (supervisor.shutdown(), sys.exit(0)))
    return supervisor.serve()


if __name__ == "__main__":
    raise SystemExit(main())
