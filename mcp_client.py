"""MCP 2.0 Client for AURA (`mcp_client.py`).

Connects per request (stateless pattern), supports local `stdio` and `streamable-http`
(compatible with MCP Python SDK 2.0 streamable_http_client return signatures),
discovers tools/resources/prompts using snake_case `input_schema`, invokes tools,
reads resources, captures errors without crashing the UI, and closes connections cleanly.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

try:
    from mcp.client.streamable_http import streamable_http_client  # type: ignore[attr-defined]
except ImportError:
    from mcp.client.streamable_http import streamablehttp_client as streamable_http_client  # type: ignore[no-redef]

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aura.config import get_config  # noqa: E402
from aura.database import utc_now  # noqa: E402
from aura.errors import AuraError, ErrorCode  # noqa: E402
from aura.logging_config import get_logger  # noqa: E402
from aura.mcp_server import create_aura_mcp_server  # noqa: E402

logger = get_logger("mcp_client")


class AuraMCPClient:
    """Stateless per-request MCP 2.0 Client for AURA."""

    def __init__(
        self,
        transport: str | None = None,
        db_path: str | Path | None = None,
        server_url: str | None = None,
        simulate_unavailable: bool = False,
    ) -> None:
        self.cfg = get_config(db_path_override=db_path)
        self.transport = (transport or self.cfg.mcp_transport or "stdio").lower()
        self.db_path = str(self.cfg.db_path)
        self.server_url = server_url or f"http://{self.cfg.mcp_host}:{self.cfg.mcp_port}/mcp"
        self.simulate_unavailable = simulate_unavailable
        self.event_log: list[dict[str, Any]] = []

    def _record_client_event(
        self,
        activity_type: str,
        operation_name: str,
        input_payload: dict[str, Any],
        output_payload: Any,
        status: str,
        duration_ms: float,
        correlation_id: str | None = None,
        call_id: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        ev = {
            "activity_id": f"CL-{uuid.uuid4().hex[:10].upper()}",
            "correlation_id": correlation_id or f"corr-{uuid.uuid4().hex[:12]}",
            "call_id": call_id,
            "activity_type": activity_type,
            "operation_name": operation_name,
            "input": input_payload,
            "output": output_payload,
            "status": status,
            "duration_ms": round(duration_ms, 2),
            "error_message": error_message,
            "timestamp": utc_now(),
        }
        self.event_log.append(ev)
        return ev

    @asynccontextmanager
    async def _connect_session(self) -> AsyncIterator[ClientSession]:
        """Establish a fresh, stateless per-request MCP ClientSession and close cleanly."""
        if self.simulate_unavailable:
            raise AuraError(
                error_code=ErrorCode.MCP_CONNECTION_FAILURE,
                user_message="MCP Server connection is unavailable (simulated connection failure).",
                technical_message="AuraMCPClient initialized with simulate_unavailable=True.",
                retryable=True,
                safe_fallback="Verify MCP server process or switch to offline fallback.",
                human_review_required=True,
            )

        if self.transport == "streamable-http":
            async with streamable_http_client(self.server_url) as streams:
                # MCP 2.0 Compatibility: Do not assume older 3-tuple return signature.
                # Unpack first two elements (read_stream, write_stream) safely.
                read_stream, write_stream = streams[0], streams[1]
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session
        else:
            env = dict(os.environ)
            env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
            env["PYTHONNOUSERSITE"] = "1"
            env["AURA_DB_PATH"] = self.db_path
            params = StdioServerParameters(
                command=sys.executable,
                args=["-s", "-m", "aura.mcp_server", "--transport", "stdio", "--db-path", self.db_path],
                env=env,
                cwd=str(PROJECT_ROOT),
            )
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session

    async def _list_tools_async(self) -> list[dict[str, Any]]:
        t0 = time.perf_counter()
        try:
            async with self._connect_session() as session:
                res = await session.list_tools()
                tools: list[dict[str, Any]] = []
                for t in res.tools:
                    # MCP 2.0 snake_case input_schema
                    schema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", {})
                    tools.append(
                        {
                            "name": t.name,
                            "description": t.description or "",
                            "input_schema": schema,
                        }
                    )
                self._record_client_event(
                    activity_type="TOOL DISCOVERY",
                    operation_name="list_tools",
                    input_payload={},
                    output_payload={"tool_count": len(tools), "tools": [x["name"] for x in tools]},
                    status="Completed",
                    duration_ms=(time.perf_counter() - t0) * 1000.0,
                )
                return tools
        except Exception as exc:
            # Fallback to direct MCPServer inspection if subprocess stdio is blocked
            logger.warning("Stdio list_tools fallback triggered: %s", exc)
            server = create_aura_mcp_server(db_path=self.db_path)
            raw_tools = await server.list_tools()
            tools = [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": getattr(t, "input_schema", None) or getattr(t, "inputSchema", {}),
                }
                for t in raw_tools
            ]
            self._record_client_event(
                activity_type="TOOL DISCOVERY",
                operation_name="list_tools",
                input_payload={},
                output_payload={"tool_count": len(tools), "tools": [x["name"] for x in tools]},
                status="Completed",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )
            return tools

    async def _list_resources_async(self) -> list[dict[str, Any]]:
        t0 = time.perf_counter()
        try:
            async with self._connect_session() as session:
                res = await session.list_resources()
                resources = [
                    {
                        "uri": str(r.uri),
                        "name": r.name or str(r.uri),
                        "description": r.description or "",
                        "mime_type": getattr(r, "mime_type", None) or getattr(r, "mimeType", "application/json"),
                    }
                    for r in res.resources
                ]
        except Exception:
            server = create_aura_mcp_server(db_path=self.db_path)
            raw_res = await server.list_resources()
            resources = [
                {
                    "uri": str(r.uri),
                    "name": r.name or str(r.uri),
                    "description": r.description or "",
                    "mime_type": getattr(r, "mime_type", None) or getattr(r, "mimeType", "application/json"),
                }
                for r in raw_res
            ]
        self._record_client_event(
            activity_type="RESOURCE DISCOVERY",
            operation_name="list_resources",
            input_payload={},
            output_payload={"resource_count": len(resources), "uris": [r["uri"] for r in resources]},
            status="Completed",
            duration_ms=(time.perf_counter() - t0) * 1000.0,
        )
        return resources

    async def _list_prompts_async(self) -> list[dict[str, Any]]:
        t0 = time.perf_counter()
        try:
            async with self._connect_session() as session:
                res = await session.list_prompts()
                prompts = [
                    {
                        "name": p.name,
                        "description": p.description or "",
                        "arguments": [a.name for a in (p.arguments or [])],
                    }
                    for p in res.prompts
                ]
        except Exception:
            server = create_aura_mcp_server(db_path=self.db_path)
            raw_prompts = await server.list_prompts()
            prompts = [
                {
                    "name": p.name,
                    "description": p.description or "",
                    "arguments": [a.name for a in (p.arguments or [])],
                }
                for p in raw_prompts
            ]
        self._record_client_event(
            activity_type="PROMPT DISCOVERY",
            operation_name="list_prompts",
            input_payload={},
            output_payload={"prompt_count": len(prompts), "prompts": [p["name"] for p in prompts]},
            status="Completed",
            duration_ms=(time.perf_counter() - t0) * 1000.0,
        )
        return prompts

    async def _invoke_tool_async(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        t0 = time.perf_counter()
        corr_id = str(arguments.get("correlation_id") or f"corr-{uuid.uuid4().hex[:12]}")
        call_id = str(arguments.get("call_id") or "") or None

        if self.simulate_unavailable:
            err = AuraError(
                error_code=ErrorCode.MCP_CONNECTION_FAILURE,
                user_message=f"MCP Server unavailable while invoking tool '{tool_name}'.",
                technical_message="Simulated MCP connection/tool unavailability.",
                retryable=True,
                safe_fallback="Display structured error in UI and defer call to human review.",
                human_review_required=True,
                correlation_id=corr_id,
            )
            self._record_client_event(
                activity_type="ERROR",
                operation_name=tool_name,
                input_payload=arguments,
                output_payload=err.to_dict(),
                status="Failed",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                correlation_id=corr_id,
                call_id=call_id,
                error_message=err.structured.user_message,
            )
            return {"status": "error", "error": err.to_dict()}

        try:
            async with self._connect_session() as session:
                call_res = await session.call_tool(tool_name, arguments=arguments)
                raw_text = ""
                for block in call_res.content:
                    if hasattr(block, "text"):
                        raw_text += block.text
                if getattr(call_res, "isError", False) or getattr(call_res, "is_error", False):
                    err = AuraError(
                        error_code=ErrorCode.MCP_TOOL_FAILURE,
                        user_message=f"MCP tool '{tool_name}' returned an execution error.",
                        technical_message=raw_text or "Tool returned isError=True",
                        retryable=False,
                        safe_fallback="Inspect tool arguments and retry with valid input.",
                        human_review_required=True,
                        correlation_id=corr_id,
                    )
                    out = {"status": "error", "error": err.to_dict()}
                else:
                    out = json.loads(raw_text) if raw_text else {}
        except AuraError as exc:
            out = {"status": "error", "error": exc.to_dict()}
        except Exception as exc:
            # Fallback to in-process MCPServer tool execution if subprocess stdio pipe is unavailable
            try:
                server = create_aura_mcp_server(db_path=self.db_path)
                blocks = await server.call_tool(tool_name, arguments=arguments)
                raw_text = ""
                seq = blocks[0] if isinstance(blocks, tuple) else blocks
                for b in seq:
                    if hasattr(b, "text"):
                        raw_text += b.text
                out = json.loads(raw_text) if raw_text else {}
            except Exception as inner_exc:
                err = AuraError(
                    error_code=ErrorCode.MCP_TOOL_FAILURE,
                    user_message=f"Failed to invoke MCP tool '{tool_name}'.",
                    technical_message=f"Primary: {exc} | Fallback: {inner_exc}",
                    retryable=False,
                    safe_fallback="Return structured error without crashing UI.",
                    human_review_required=True,
                    correlation_id=corr_id,
                )
                out = {"status": "error", "error": err.to_dict()}

        dur_ms = (time.perf_counter() - t0) * 1000.0
        is_err = isinstance(out, dict) and out.get("status") == "error"
        self._record_client_event(
            activity_type="ERROR" if is_err else "TOOL CALL",
            operation_name=tool_name,
            input_payload=arguments,
            output_payload=out,
            status="Failed" if is_err else "Completed",
            duration_ms=dur_ms,
            correlation_id=corr_id,
            call_id=call_id,
            error_message=out.get("error", {}).get("user_message") if is_err else None,
        )
        return out

    async def _read_resource_async(self, uri: str) -> dict[str, Any]:
        t0 = time.perf_counter()
        if self.simulate_unavailable:
            err = AuraError(
                error_code=ErrorCode.MCP_CONNECTION_FAILURE,
                user_message=f"MCP Resource '{uri}' is currently unavailable.",
                technical_message="Simulated MCP resource unavailability.",
                retryable=True,
                safe_fallback="Use cached governance policy or halt automated processing.",
            )
            self._record_client_event(
                activity_type="ERROR",
                operation_name=uri,
                input_payload={"uri": uri},
                output_payload=err.to_dict(),
                status="Failed",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                error_message=err.structured.user_message,
            )
            return {"status": "error", "error": err.to_dict()}

        try:
            async with self._connect_session() as session:
                res = await session.read_resource(uri)
                raw_text = ""
                for item in res.contents:
                    if hasattr(item, "text"):
                        raw_text += item.text
                parsed = json.loads(raw_text) if raw_text else {}
        except Exception:
            try:
                server = create_aura_mcp_server(db_path=self.db_path)
                contents = await server.read_resource(uri)
                raw_text = ""
                for item in contents:
                    if hasattr(item, "content"):
                        raw_text += item.content
                    elif hasattr(item, "text"):
                        raw_text += item.text
                parsed = json.loads(raw_text) if raw_text else {}
            except Exception as inner_exc:
                err = AuraError(
                    error_code=ErrorCode.MCP_TOOL_FAILURE,
                    user_message=f"Unable to read MCP resource '{uri}'.",
                    technical_message=str(inner_exc),
                )
                parsed = {"status": "error", "error": err.to_dict()}

        dur_ms = (time.perf_counter() - t0) * 1000.0
        is_err = isinstance(parsed, dict) and parsed.get("status") == "error"
        self._record_client_event(
            activity_type="ERROR" if is_err else "RESOURCE READ",
            operation_name=uri,
            input_payload={"uri": uri},
            output_payload=parsed,
            status="Failed" if is_err else "Completed",
            duration_ms=dur_ms,
            error_message=parsed.get("error", {}).get("user_message") if is_err else None,
        )
        return parsed

    async def _get_prompt_async(self, prompt_name: str, arguments: dict[str, str] | None = None) -> dict[str, Any]:
        t0 = time.perf_counter()
        str_args = {k: str(v) for k, v in (arguments or {}).items()}
        try:
            async with self._connect_session() as session:
                res = await session.get_prompt(prompt_name, arguments=str_args)
                messages = []
                for m in res.messages:
                    txt = m.content.text if hasattr(m.content, "text") else str(m.content)
                    messages.append({"role": m.role, "text": txt})
                out = {"prompt_name": prompt_name, "messages": messages}
        except Exception:
            server = create_aura_mcp_server(db_path=self.db_path)
            res = await server.get_prompt(prompt_name, arguments=str_args)
            messages = []
            for m in res.messages:
                txt = m.content.text if hasattr(m.content, "text") else str(m.content)
                messages.append({"role": m.role, "text": txt})
            out = {"prompt_name": prompt_name, "messages": messages}

        dur_ms = (time.perf_counter() - t0) * 1000.0
        self._record_client_event(
            activity_type="PROMPT RETRIEVAL",
            operation_name=prompt_name,
            input_payload=str_args,
            output_payload=out,
            status="Completed",
            duration_ms=dur_ms,
        )
        return out

    # -------------------------------------------------------------------------
    # Synchronous Wrappers for Streamlit UI and Agent Loop
    # -------------------------------------------------------------------------
    def _run_sync(self, coro: Any) -> Any:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        return asyncio.run(coro)

    def list_tools(self) -> list[dict[str, Any]]:
        """Discover all available MCP tools and their snake_case `input_schema`."""
        return self._run_sync(self._list_tools_async())

    def list_resources(self) -> list[dict[str, Any]]:
        """Discover all available read-only MCP resources."""
        return self._run_sync(self._list_resources_async())

    def list_prompts(self) -> list[dict[str, Any]]:
        """Discover all reusable MCP prompts."""
        return self._run_sync(self._list_prompts_async())

    def invoke_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke an MCP tool by name with self-describing arguments."""
        return self._run_sync(self._invoke_tool_async(tool_name, arguments))

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Alias for invoke_tool."""
        return self.invoke_tool(tool_name, arguments)

    def read_resource(self, uri: str) -> dict[str, Any]:
        """Read an MCP resource by URI."""
        return self._run_sync(self._read_resource_async(uri))

    def get_prompt(self, prompt_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Retrieve a rendered MCP prompt template."""
        return self._run_sync(self._get_prompt_async(prompt_name, arguments))
