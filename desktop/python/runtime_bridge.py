"""JSONL supervisor and per-run worker for the Desktop runtime bridge."""
from __future__ import annotations

import contextlib
import copy
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
from datasets import DatasetRegistry, DatasetRegistryError  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402
from hitl import PersistentApprovalManager  # noqa: E402
from mcp_adapter import MCPToolAdapter, MockMCPClient, MockMCPServer  # noqa: E402
from observability import TraceCollector  # noqa: E402
from session import (  # noqa: E402
    SQLiteApprovalRepository,
    SQLiteSessionStore,
    SessionAlreadyExistsError,
    SessionNotFoundError,
)
from session.recovery import SessionStateProjector  # noqa: E402
from skill_runtime import SkillRegistry, SkillRuntime  # noqa: E402
from tools import build_default_registry  # noqa: E402
from workflow import AnalysisNode, CalcNode, ChatNode, MemoryRecallNode, RuleRouter, Workflow  # noqa: E402

PROTOCOL_VERSION = 1
MAX_LINE_BYTES = 1024 * 1024
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
COMMAND_TYPES = frozenset({
    "run.start", "run.cancel", "dataset.register",
    "session.list", "session.get", "session.resume", "approval.resolve",
})
TERMINAL_TYPES = frozenset({
    "run_completed", "run_failed", "run_cancelled", "approval_required", "approval_resolved",
})


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
        dataset_id = payload.get("dataset_id")
        if dataset_id is not None and (
            not isinstance(dataset_id, str)
            or not re.fullmatch(r"ds_[A-Za-z0-9_-]{1,64}", dataset_id)
        ):
            raise ProtocolError("invalid_dataset_id", "dataset_id is invalid")
    elif message_type == "dataset.register":
        file_path = payload.get("file_path")
        if not isinstance(file_path, str) or not file_path.strip():
            raise ProtocolError("invalid_dataset_path", "file_path is required")
        thread_id = value.get("thread_id")
        if thread_id is not None and (
            not isinstance(thread_id, str) or not ID_PATTERN.fullmatch(thread_id)
        ):
            raise ProtocolError("invalid_thread_id", "thread_id is invalid")
    elif message_type == "run.cancel":
        run_id = value.get("run_id")
        if not isinstance(run_id, str) or not ID_PATTERN.fullmatch(run_id):
            raise ProtocolError("invalid_run_id", "run_id is invalid")
    elif message_type == "session.list":
        limit = payload.get("limit", 20)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 100:
            raise ProtocolError("invalid_session_limit", "limit must be between 1 and 100")
    elif message_type in {"session.get", "session.resume"}:
        thread_id = value.get("thread_id")
        if not isinstance(thread_id, str) or not ID_PATTERN.fullmatch(thread_id):
            raise ProtocolError("invalid_thread_id", "thread_id is invalid")
    else:
        thread_id = value.get("thread_id")
        if not isinstance(thread_id, str) or not ID_PATTERN.fullmatch(thread_id):
            raise ProtocolError("invalid_thread_id", "thread_id is invalid")
        approval_id = payload.get("approval_id")
        action_hash = payload.get("action_hash")
        decision = payload.get("decision")
        if not isinstance(approval_id, str) or not ID_PATTERN.fullmatch(approval_id):
            raise ProtocolError("invalid_approval_id", "approval_id is invalid")
        if not isinstance(action_hash, str) or not action_hash or len(action_hash) > 256:
            raise ProtocolError("invalid_action_hash", "action_hash is invalid")
        if decision not in {"approve", "reject"}:
            raise ProtocolError("invalid_approval_decision", "decision must be approve or reject")
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
    """Minimal composition adapter used only when Workflow selects analysis."""

    def complete(self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        available = {item.get("function", {}).get("name") for item in tools}
        user_index = next(
            (index for index in range(len(messages) - 1, -1, -1) if messages[index].get("role") == "user"),
            -1,
        )
        user = messages[user_index] if user_index >= 0 else {}
        question = str(user.get("content", ""))
        dataset_context = user.get("dataset_context")
        datasets = dataset_context.get("datasets", []) if isinstance(dataset_context, dict) else []
        dataset = datasets[-1] if datasets else None
        tool_message = next(
            (item for item in reversed(messages[user_index + 1 :]) if item.get("role") == "tool"),
            None,
        )
        wants_chart = any(term in question.lower() for term in ("图", "chart", "visual"))

        if isinstance(tool_message, dict):
            try:
                observation = json.loads(str(tool_message.get("content", "{}")))
            except json.JSONDecodeError:
                return {"type": "final_answer", "content": "工具结果无法解析，分析未完成。"}
            if not observation.get("ok"):
                error = observation.get("error") or {}
                return {
                    "type": "final_answer",
                    "content": f"分析工具失败：{error.get('message', error.get('code', 'unknown error'))}",
                }
            tool_name = str(tool_message.get("name", ""))
            if wants_chart and tool_name != "generate_chart" and "generate_chart" in available:
                chart_type = "line" if tool_name == "trend_analysis" else "scatter" if tool_name == "scatter_data" else "bar"
                return {
                    "type": "tool_call",
                    "id": f"bridge_chart_{len(messages)}",
                    "name": "generate_chart",
                    "arguments": {
                        "sourceCallId": str(tool_message.get("tool_call_id")),
                        "chartType": chart_type,
                    },
                }
            if tool_name == "generate_chart":
                return {"type": "final_answer", "content": "分析完成，图表已生成。"}
            data = observation.get("data")
            summary = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            return {"type": "final_answer", "content": "分析完成：" + summary}

        if any(term in question.lower() for term in ("外部写", "mcp write", "external write")) and "mcp_mock__echo" in available:
            return {
                "type": "tool_call",
                "id": f"bridge_write_{len(messages)}",
                "name": "mcp_mock__echo",
                "arguments": {"text": question},
            }
        if not isinstance(dataset, dict):
            return {"type": "final_answer", "content": "Desktop Runtime 已完成本次请求。"}
        dataset_id = dataset.get("datasetId")
        columns = dataset.get("columns", [])
        if not isinstance(dataset_id, str) or not isinstance(columns, list):
            return {"type": "needs_user_input", "content": "数据集摘要不完整，请重新选择文件。"}
        named = [item for item in columns if isinstance(item, dict) and isinstance(item.get("name"), str)]
        number_columns = [item["name"] for item in named if item.get("type") == "number"]
        date_columns = [item["name"] for item in named if item.get("type") == "date"]
        text_columns = [item["name"] for item in named if item.get("type") == "text"]
        metric = next((name for name in number_columns if name in question), number_columns[0] if number_columns else None)
        group = next((name for name in text_columns if name in question), text_columns[0] if text_columns else None)
        date_field = next((name for name in date_columns if name in question), date_columns[0] if date_columns else None)
        operation = "average" if any(term in question for term in ("平均", "均值")) else "maximum" if "最大" in question else "minimum" if "最小" in question else "count" if any(term in question for term in ("计数", "数量")) else "sum"
        call: dict[str, Any] | None = None
        if metric and date_field and any(term in question for term in ("趋势", "变化", "按日期", "折线")):
            call = {"name": "trend_analysis", "arguments": {"datasetId": dataset_id, "dateField": date_field, "metric": metric, "operation": operation}}
        elif metric and group and any(term in question for term in ("按", "分组", "对比", "柱状")):
            call = {"name": "group_compare", "arguments": {"datasetId": dataset_id, "groupBy": group, "metric": metric, "operation": operation}}
        elif metric:
            call = {"name": "basic_stats", "arguments": {"datasetId": dataset_id, "metric": metric, "operation": operation}}
        elif "inspect_data" in available:
            call = {"name": "inspect_data", "arguments": {"datasetId": dataset_id}}
        if call is None or call["name"] not in available:
            return {"type": "needs_user_input", "content": "请明确要分析的字段和统计方式。"}
        return {
            "type": "tool_call",
            "id": f"bridge_analysis_{len(messages)}",
            **call,
        }


def runtime_root() -> Path:
    return Path(
        os.environ.get(
            "DATA_AGENT_RUNTIME_DIR",
            str(Path(tempfile.gettempdir()) / "data-analysis-agent-desktop"),
        )
    )


def session_database() -> Path:
    return runtime_root() / "sessions.sqlite3"


def approval_key() -> bytes:
    configured = os.environ.get("DATA_AGENT_APPROVAL_KEY")
    if configured:
        return configured.encode("ascii")
    root = runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "approval.key"
    try:
        return path.read_bytes().strip()
    except FileNotFoundError:
        key = Fernet.generate_key()
        try:
            with path.open("xb") as stream:
                stream.write(key)
        except FileExistsError:
            return path.read_bytes().strip()
        return key


def ensure_session(store: SQLiteSessionStore, thread_id: str) -> None:
    if store.get_session(thread_id) is not None:
        return
    try:
        store.create_session(thread_id)
    except SessionAlreadyExistsError:
        pass


def build_hitl_registry(store: SQLiteSessionStore, thread_id: str):
    manager = PersistentApprovalManager(
        SQLiteApprovalRepository(store, approval_key()),
        thread_id=thread_id,
        ttl_seconds=float(os.environ.get("DESKTOP_APPROVAL_TTL_SECONDS", "300")),
    )
    registry = build_default_registry()
    registry.approval_manager = manager
    server = MockMCPServer()
    report = MCPToolAdapter(
        MockMCPClient(server),
        server_id="mock",
        allowed_tools={"echo"},
        tool_policies={"echo": "mcp_write"},
    ).register_into(registry)
    if not report.ok:
        raise RuntimeError("Desktop HITL tool registration failed")
    return registry, server


def build_workflow(
    thread_id: str,
    store: SQLiteSessionStore,
    dataset: dict[str, str] | None = None,
) -> tuple[Workflow, ConversationRunner]:
    datasets = DatasetRegistry(runtime_root() / thread_id / "datasets")
    if dataset is not None:
        summary = datasets.register(
            dataset["path"],
            dataset_id=dataset["dataset_id"],
        )
    registry, _server = build_hitl_registry(store, thread_id)
    runner = ConversationRunner(
        AgentLoop(BridgeModel(), registry),
        dataset_registry=datasets,
        conversation_id=thread_id,
    )
    snapshot = SessionStateProjector.project(
        thread_id=thread_id,
        messages=store.get_messages(thread_id),
        events=store.get_events(thread_id),
        dataset_registry=datasets,
    )
    runner.state = snapshot.conversation_state
    if dataset is not None:
        runner.set_active_datasets([summary["datasetId"]])
    skills = SkillRuntime(runner, SkillRegistry())
    workflow = Workflow(
        router=RuleRouter(),
        nodes={
            "chat": ChatNode(),
            "analysis": AnalysisNode(runner, skill_runtime=skills),
            "calc": CalcNode(),
            "memory_recall": MemoryRecallNode(None),
        },
    )
    return workflow, runner


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


def chart_payloads(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Project only validated Chart Spec and non-path artifact metadata."""
    agent_state = result.get("data", {}).get("agent_state", {})
    entries = agent_state.get("execution_trace", []) if isinstance(agent_state, dict) else []
    payloads: list[dict[str, Any]] = []
    for entry in entries:
        data = entry.get("data") if isinstance(entry, dict) else None
        chart = data if isinstance(data, dict) and entry.get("tool_name") == "generate_chart" else None
        spec = chart.get("spec") if isinstance(chart, dict) else None
        artifact = chart.get("artifact") if isinstance(chart, dict) else None
        if not isinstance(spec, dict):
            continue
        public_artifact = {
            key: artifact[key]
            for key in ("mediaType", "width", "height", "sha256")
            if isinstance(artifact, dict) and key in artifact
        }
        payloads.append({"spec": spec, "artifact": public_artifact})
    return payloads


def _redact_message(message: dict[str, Any]) -> dict[str, Any]:
    public = copy.deepcopy(message)
    if public.get("role") == "assistant":
        for call in public.get("tool_calls", []):
            function = call.get("function", {}) if isinstance(call, dict) else {}
            if str(function.get("name", "")).startswith("mcp_"):
                function["arguments"] = "<sealed-pending-action>"
    return public


def persist_run(
    store: SQLiteSessionStore,
    runner: ConversationRunner,
    result: dict[str, Any],
    *,
    thread_id: str,
    run_id: str,
    query: str,
    trace_id: str,
) -> None:
    route = result.get("route")
    if route == "analysis" and runner.state.turns:
        persisted_messages = runner.state.turns[-1].messages
    else:
        persisted_messages = [
            {"role": "user", "content": query},
            {"role": "assistant", "content": result.get("response") or ""},
        ]
    for message in persisted_messages:
        if isinstance(message, dict) and message.get("role") in {"user", "assistant", "tool"}:
            store.append_message(
                thread_id,
                {**_redact_message(message), "turn_id": run_id},
                turn_id=run_id,
                trace_id=trace_id,
            )
    observability = result.get("data", {}).get("observability", {})
    for event in observability.get("events", []) if isinstance(observability, dict) else []:
        if not isinstance(event, dict) or event.get("event_type") == "approval_requested":
            continue
        store.append_event(
            thread_id,
            event,
            turn_id=run_id,
            trace_id=event.get("trace_id") if isinstance(event.get("trace_id"), str) else trace_id,
        )


def approval_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    agent_state = result.get("data", {}).get("agent_state", {})
    pending = agent_state.get("pending_approval") if isinstance(agent_state, dict) else None
    if not isinstance(pending, dict):
        return None
    public = {
        key: pending.get(key)
        for key in (
            "approval_id", "action_hash", "tool_name", "action_type", "risk_level",
            "rule_id", "status", "created_at", "expires_at",
        )
    }
    public["risk_summary"] = f"{pending.get('risk_level')} risk · {pending.get('action_type')}"
    return public


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
    store = SQLiteSessionStore(session_database())
    ensure_session(store, thread_id)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            workflow, runner = build_workflow(thread_id, store, command.get("_dataset"))
            result = workflow.invoke(
                {
                    "query": command["payload"]["message"],
                    "artifact_dir": str(runtime_root() / thread_id / "artifacts" / run_id),
                    "_trace_collector": collector,
                }
            )
        persist_run(
            store,
            runner,
            result,
            thread_id=thread_id,
            run_id=run_id,
            query=command["payload"]["message"],
            trace_id=collector.trace_id,
        )
        agent_state = result.get("data", {}).get("agent_state", {})
        for payload in chart_payloads(result):
            emitter.emit("chart_ready", payload)
        if result["status"] == "error":
            error = result.get("error") or {"code": "runtime_error", "message": "run failed"}
            partial_available = bool(
                isinstance(agent_state, dict)
                and (agent_state.get("execution_trace") or agent_state.get("final_answer"))
            )
            emitter.emit(
                "run_failed",
                {
                    "status": "failed",
                    "response": result.get("response"),
                    "partial": partial_available,
                },
                dict(error),
            )
            return 1
        if result["status"] == "needs_approval":
            pending = approval_payload(result)
            if pending is None:
                emitter.emit(
                    "run_failed",
                    {"status": "failed"},
                    {"code": "missing_approval", "message": "Runtime omitted approval details"},
                )
                return 1
            emitter.emit("approval_required", pending)
            return 0
        emitter.emit(
            "run_completed",
            {
                "status": result["status"],
                "route": result.get("route"),
                "response": result.get("response"),
                "partial": result["status"] in {"incomplete", "needs_input"},
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
    finally:
        store.close()


def approval_worker(command: dict[str, Any]) -> int:
    writer = JsonlWriter(sys.stdout)
    request_id = command["request_id"]
    run_id = command["run_id"]
    thread_id = command["thread_id"]
    trace_id = f"trace_{uuid.uuid4().hex}"
    emitter = RunEmitter(writer, request_id, run_id, thread_id, trace_id)
    emitter.emit("run_started", {"status": "resuming"})
    store = SQLiteSessionStore(session_database())
    try:
        if store.get_session(thread_id) is None:
            raise SessionNotFoundError(f"session not found: {thread_id}")
        registry, server = build_hitl_registry(store, thread_id)
        with contextlib.redirect_stdout(sys.stderr):
            result = registry.resolve_approval(
                approval_id=command["payload"]["approval_id"],
                action_hash=command["payload"]["action_hash"],
                decision=command["payload"]["decision"],
            )
        for event in result.trace_events:
            emitter.trace(event)
        decision = result.decision.to_dict() if result.decision is not None else None
        error = result.error
        status = decision.get("status") if isinstance(decision, dict) else None
        if error:
            code = str(error.get("code", "approval_failed"))
            if code == "approval_expired":
                status = "expired"
            elif status is None:
                status = "rejected"
        terminal = {
            "status": status or "rejected",
            "decision": decision,
            "executed": bool(server.calls),
        }
        emitter.emit("approval_resolved", terminal, error)
        return 0 if result.ok else 1
    except Exception as error:
        emitter.emit(
            "approval_resolved",
            {"status": "rejected", "executed": False},
            {"code": getattr(error, "code", type(error).__name__), "message": str(error)},
        )
        print(f"approval worker failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    finally:
        store.close()


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
        self.dataset_registries: dict[str, DatasetRegistry] = {}

    def serve(self) -> int:
        for raw in sys.stdin:
            if len(raw.encode("utf-8")) > MAX_LINE_BYTES:
                self._protocol_failure(None, "frame_too_large", "JSONL frame exceeds limit")
                continue
            try:
                command = validate_command(json.loads(raw))
                if command["type"] == "run.start":
                    self._start(command)
                elif command["type"] == "run.cancel":
                    self._cancel(command)
                elif command["type"] == "dataset.register":
                    self._register_dataset(command)
                elif command["type"] == "session.list":
                    self._list_sessions(command)
                elif command["type"] in {"session.get", "session.resume"}:
                    self._get_session(command)
                else:
                    self._resolve_approval(command)
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
        dataset_id = command["payload"].get("dataset_id")
        if dataset_id is not None:
            registry = self.dataset_registries.get(thread_id)
            if registry is None or not registry.contains(dataset_id):
                self.writer.write(
                    envelope(
                        "response",
                        request_id=command["request_id"],
                        run_id=None,
                        thread_id=thread_id,
                        trace_id=None,
                        sequence=0,
                        error={"code": "dataset_not_found", "message": "dataset is not registered for this thread"},
                    )
                )
                return
            worker_command["_dataset"] = {
                "dataset_id": dataset_id,
                "path": registry.resolve(dataset_id),
            }
        self._spawn_worker(worker_command, "--worker")

    def _spawn_worker(self, worker_command: dict[str, Any], mode: str) -> None:
        run_id = worker_command["run_id"]
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), mode],
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

    def _resolve_approval(self, command: dict[str, Any]) -> None:
        worker_command = dict(command)
        worker_command["run_id"] = f"run_{uuid.uuid4().hex}"
        self._spawn_worker(worker_command, "--approval-worker")

    def _register_dataset(self, command: dict[str, Any]) -> None:
        thread_id = command.get("thread_id") or f"thread_{uuid.uuid4().hex}"
        registry = self.dataset_registries.get(thread_id)
        if registry is None:
            registry = DatasetRegistry(runtime_root() / thread_id / "datasets")
            self.dataset_registries[thread_id] = registry
        try:
            with SQLiteSessionStore(session_database()) as store:
                ensure_session(store, thread_id)
            summary = registry.register(command["payload"]["file_path"])
        except DatasetRegistryError as error:
            self.writer.write(
                envelope(
                    "response",
                    request_id=command["request_id"],
                    run_id=None,
                    thread_id=thread_id,
                    trace_id=None,
                    sequence=0,
                    error={"code": error.code, "message": str(error)},
                )
            )
            return
        self.writer.write(
            envelope(
                "response",
                request_id=command["request_id"],
                run_id=None,
                thread_id=thread_id,
                trace_id=None,
                sequence=0,
                payload={"status": "selected", "dataset": summary},
            )
        )

    def _list_sessions(self, command: dict[str, Any]) -> None:
        with SQLiteSessionStore(session_database()) as store:
            items = []
            for record in store.list_sessions(limit=command["payload"].get("limit", 20)):
                messages = store.get_messages(record.thread_id)
                summary = ""
                for message in reversed(messages):
                    if message.get("role") not in {"user", "assistant"}:
                        continue
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        summary = content.strip()[:160]
                        break
                items.append({**record.to_dict(), "summary": summary})
        self.writer.write(envelope(
            "response", request_id=command["request_id"], run_id=None,
            thread_id=None, trace_id=None, sequence=0,
            payload={"sessions": items},
        ))

    def _get_session(self, command: dict[str, Any]) -> None:
        thread_id = command["thread_id"]
        try:
            with SQLiteSessionStore(session_database()) as store:
                record = store.get_session(thread_id)
                if record is None:
                    raise SessionNotFoundError(f"session not found: {thread_id}")
                messages = store.get_messages(thread_id)
                events = store.get_events(thread_id)
                datasets = self.dataset_registries.get(thread_id) or DatasetRegistry(
                    runtime_root() / thread_id / "datasets"
                )
                snapshot = SessionStateProjector.project(
                    thread_id=thread_id,
                    messages=messages,
                    events=events,
                    dataset_registry=datasets,
                )
                payload = {
                    "session": record.to_dict(),
                    "messages": messages,
                    "events": events,
                    "conversation": {
                        "thread_id": snapshot.conversation_state.conversation_id,
                        "turn_count": len(snapshot.conversation_state.turns),
                        "trace_ids": snapshot.trace_ids,
                    },
                }
            self.writer.write(envelope(
                "response", request_id=command["request_id"], run_id=None,
                thread_id=thread_id, trace_id=None, sequence=0, payload=payload,
            ))
        except SessionNotFoundError as error:
            self.writer.write(envelope(
                "response", request_id=command["request_id"], run_id=None,
                thread_id=thread_id, trace_id=None, sequence=0,
                error={"code": error.code, "message": str(error)},
            ))

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
                            payload={
                                "status": "resuming"
                                if message.get("payload", {}).get("status") == "resuming"
                                else "running"
                            },
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
    if len(sys.argv) > 1 and sys.argv[1] == "--approval-worker":
        raw = sys.stdin.readline()
        try:
            command = json.loads(raw)
        except json.JSONDecodeError:
            print("approval worker received invalid JSON", file=sys.stderr)
            return 2
        return approval_worker(command)
    supervisor = Supervisor()
    signal.signal(signal.SIGTERM, lambda *_args: (supervisor.shutdown(), sys.exit(0)))
    return supervisor.serve()


if __name__ == "__main__":
    raise SystemExit(main())
