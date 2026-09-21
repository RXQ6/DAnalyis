"""Official MCP Python SDK stdio facade for the synchronous MCPClient contract."""

from __future__ import annotations

import asyncio
import concurrent.futures
import copy
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .contracts import (
    MCPCallResult,
    MCPListToolsResult,
    MCPProtocolError,
    MCPRemoteError,
)


@dataclass
class _Command:
    kind: Literal["list_tools", "call_tool", "stop"]
    payload: dict[str, Any] = field(default_factory=dict)
    result: concurrent.futures.Future[Any] = field(
        default_factory=concurrent.futures.Future
    )


class MCPStdioClient:
    """Run the official async SDK Client behind the existing synchronous facade."""

    def __init__(
        self,
        command: str,
        *,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | Path | None = None,
        startup_timeout_seconds: float = 10.0,
    ) -> None:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("MCP stdio command cannot be empty")
        if startup_timeout_seconds <= 0:
            raise ValueError("MCP startup timeout must be positive")
        self.command = command
        self.args = list(args or [])
        self.env = None if env is None else dict(env)
        self.cwd = None if cwd is None else str(Path(cwd).resolve())
        self.startup_timeout_seconds = float(startup_timeout_seconds)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[_Command] | None = None
        self._active_task: asyncio.Task[Any] | None = None
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None
        self._closed = False
        self._thread = threading.Thread(
            target=self._thread_main,
            daemon=True,
            name="mcp-sdk-stdio-client",
        )
        self._thread.start()
        if not self._ready.wait(self.startup_timeout_seconds):
            self._closed = True
            raise MCPRemoteError("MCP stdio Client startup timed out")
        if self._startup_error is not None:
            self._closed = True
            raise MCPRemoteError("MCP stdio Client could not connect") from self._startup_error

    def list_tools(
        self,
        *,
        cursor: str | None = None,
        timeout_seconds: float,
    ) -> MCPListToolsResult:
        raw = self._submit(
            _Command("list_tools", {"cursor": cursor}), timeout_seconds
        )
        if not isinstance(raw, dict):
            raise MCPProtocolError("SDK list_tools result is invalid")
        return raw

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> MCPCallResult:
        raw = self._submit(
            _Command(
                "call_tool",
                {"name": name, "arguments": copy.deepcopy(arguments)},
            ),
            timeout_seconds,
        )
        if not isinstance(raw, dict):
            raise MCPProtocolError("SDK call_tool result is invalid")
        return raw

    def cancel_pending(self) -> None:
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._cancel_active)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._submit(_Command("stop"), self.startup_timeout_seconds, allow_closed=True)
        except Exception:
            self.cancel_pending()
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(lambda: None)
        self._thread.join(self.startup_timeout_seconds)

    def _submit(
        self,
        command: _Command,
        timeout_seconds: float,
        *,
        allow_closed: bool = False,
    ) -> Any:
        if self._closed and not allow_closed:
            raise MCPRemoteError("MCP stdio Client is closed")
        loop = self._loop
        queue = self._queue
        if loop is None or queue is None or not loop.is_running():
            raise MCPRemoteError("MCP stdio Client is unavailable")
        loop.call_soon_threadsafe(queue.put_nowait, command)
        try:
            return command.result.result(timeout_seconds)
        except concurrent.futures.TimeoutError as error:
            self.cancel_pending()
            raise TimeoutError("MCP SDK request timed out") from error
        except (MCPProtocolError, MCPRemoteError):
            raise
        except Exception as error:
            raise MCPRemoteError("MCP SDK request failed") from error

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except BaseException as error:
            self._startup_error = error
            self._ready.set()

    async def _run(self) -> None:
        try:
            from mcp import Client, StdioServerParameters
        except ImportError as error:
            self._startup_error = error
            self._ready.set()
            return

        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env,
            cwd=self.cwd,
        )
        try:
            async with Client(params) as client:
                self._ready.set()
                while True:
                    command = await self._queue.get()
                    if command.kind == "stop":
                        command.result.set_result(None)
                        return
                    operation = asyncio.create_task(self._execute(client, command))
                    self._active_task = operation
                    try:
                        value = await operation
                    except asyncio.CancelledError:
                        if not command.result.done():
                            command.result.set_exception(
                                TimeoutError("MCP SDK request was cancelled")
                            )
                    except BaseException as error:
                        if not command.result.done():
                            command.result.set_exception(error)
                    else:
                        if not command.result.done():
                            command.result.set_result(value)
                    finally:
                        self._active_task = None
        except BaseException as error:
            self._startup_error = error
            self._ready.set()
            raise

    async def _execute(self, client: Any, command: _Command) -> dict[str, Any]:
        if command.kind == "list_tools":
            result = await client.list_tools(cursor=command.payload["cursor"])
            return {
                "tools": [
                    item.model_dump(by_alias=True, exclude_none=True)
                    for item in result.tools
                ],
                **(
                    {"nextCursor": result.next_cursor}
                    if result.next_cursor is not None
                    else {}
                ),
            }
        result = await client.call_tool(
            command.payload["name"], command.payload["arguments"]
        )
        return result.model_dump(by_alias=True, exclude_none=True)

    def _cancel_active(self) -> None:
        if self._active_task is not None and not self._active_task.done():
            self._active_task.cancel()

