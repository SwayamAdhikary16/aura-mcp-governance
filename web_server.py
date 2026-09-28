"""Interactive HTTP + Live MCP 2.0 API Server for the AURA 7-Tab Judging Dashboard.

Run:
    .venv/bin/python web_server.py
Then open:
    http://127.0.0.1:8501/aura_dashboard.html
"""

from __future__ import annotations

import base64
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sys
from pathlib import Path
import webbrowser

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR / "src") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "src"))

from agent import AuraAgent  # noqa: E402
from mcp_client import AuraMCPClient  # noqa: E402
from aura.repositories import AuraRepository  # noqa: E402


class AuraHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self.path = "/aura_dashboard.html"
        return super().do_GET()

    def _resolve_upload_path(self, payload: dict) -> str:
        """Save base64 uploaded file if provided, else default to data/synthetic_calls.xlsx."""
        file_name = payload.get("file_name")
        file_b64 = payload.get("file_base64")
        if file_name and file_b64:
            upload_dir = ROOT_DIR / "data" / "uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
            safe_name = Path(file_name).name
            dest = upload_dir / safe_name
            dest.write_bytes(base64.b64decode(file_b64))
            return str(dest)
        return str(ROOT_DIR / "data" / "synthetic_calls.xlsx")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            payload = json.loads(raw_body)
        except Exception:
            payload = {}

        client = AuraMCPClient(transport="stdio")
        repo = AuraRepository()
        response_data: dict = {"status": "error", "message": f"Unknown endpoint {self.path}"}

        try:
            if self.path == "/api/validate_file":
                target_path = self._resolve_upload_path(payload)
                replace_existing = bool(payload.get("replace_existing", True))
                val_res = client.invoke_tool(
                    "validate_input_file",
                    {"file_path": target_path, "replace_existing": replace_existing},
                )
                response_data = {
                    "status": "ok",
                    "validation": val_res,
                    "mcp_activity": repo.list_mcp_activity(limit=80),
                }
            elif self.path == "/api/ingest_calls":
                target_path = self._resolve_upload_path(payload)
                replace_existing = bool(payload.get("replace_existing", True))
                ing_res = client.invoke_tool(
                    "ingest_validated_calls",
                    {"file_path": target_path, "replace_existing": replace_existing},
                )
                portfolio = client.invoke_tool("portfolio_summary", {"job_id": ""})
                response_data = {
                    "status": "ok",
                    "ingestion": ing_res,
                    "portfolio": portfolio,
                    "calls_rows": repo.list_calls(limit=105),
                    "mcp_activity": repo.list_mcp_activity(limit=80),
                }
            elif self.path == "/api/review_batch":
                max_calls = int(payload.get("maximum_calls", 10))
                use_cached = bool(payload.get("use_cached_results", False))
                batch_res = client.invoke_tool(
                    "review_batch",
                    {
                        "job_id": payload.get("job_id", ""),
                        "maximum_calls": max_calls,
                        "stop_on_error": False,
                        "use_cached_results": use_cached,
                    },
                )
                portfolio = client.invoke_tool("portfolio_summary", {"job_id": ""})
                response_data = {
                    "status": "ok",
                    "batch_result": batch_res,
                    "portfolio": portfolio,
                    "calls_rows": repo.list_calls(limit=105),
                    "mcp_activity": repo.list_mcp_activity(limit=80),
                }
            elif self.path == "/api/review_call":
                cid = payload.get("call_id", "SYN-CALL-0001")
                try:
                    call_row = repo.get_call(cid)
                except Exception:
                    call_row = None
                transcript = payload.get("transcript") if "transcript" in payload and payload.get("transcript") is not None else (call_row["transcript"] if call_row else "")
                force_chal = bool(payload.get("force_challenger", False))
                rev = client.invoke_tool(
                    "review_call",
                    {
                        "call_id": cid,
                        "transcript": transcript,
                        "review_goal": payload.get("review_goal", "Governed MCP 2.0 call review"),
                        "force_challenger": force_chal,
                    },
                )
                if isinstance(rev, dict) and rev.get("status") == "error":
                    response_data = {
                        "status": "mcp_error",
                        "error_payload": rev,
                        "mcp_activity": repo.list_mcp_activity(limit=80),
                    }
                else:
                    response_data = {
                        "status": "ok",
                        "review_call": rev,
                        "call": repo.get_call(cid) if repo.call_exists(cid) else {"call_id": cid, "transcript": transcript},
                        "first_pass": repo.get_first_pass_result(cid),
                        "specialist": repo.get_specialist_result(cid),
                        "challenger": repo.get_challenger_result(cid),
                        "final": repo.get_final_result(cid),
                        "explain": client.invoke_tool("explain_decision", {"call_id": cid}),
                        "compare": client.invoke_tool("compare_decisions", {"call_id": cid}),
                        "audit": client.invoke_tool("get_audit_record", {"call_id": cid}),
                        "mcp_activity": repo.list_mcp_activity(limit=80),
                    }
            elif self.path == "/api/run_agent":
                agent = AuraAgent(mcp_client=client)
                res = agent.run_request(
                    user_request=payload.get("user_request", "Review this call and explain the governance decision."),
                    call_id=payload.get("call_id", "SYN-CALL-0006"),
                    mode=payload.get("mode", "agent"),
                    simulate_bad_input_first=bool(payload.get("simulate_bad_input_first", False)),
                )
                response_data = {
                    "status": "ok",
                    "agent_result": res,
                    "mcp_activity": repo.list_mcp_activity(limit=80),
                }
            elif self.path == "/api/simulate_upgrade":
                sim = client.invoke_tool(
                    "simulate_model_upgrade",
                    {
                        "production_model_id": payload.get("production_model_id", "AURA_DEEP"),
                        "candidate_model_id": payload.get("candidate_model_id", "AURA_CANDIDATE_V2"),
                        "sample_size": int(payload.get("sample_size", 20)),
                    },
                )
                response_data = {
                    "status": "ok",
                    "simulation": sim,
                    "mcp_activity": repo.list_mcp_activity(limit=80),
                }
        except Exception as exc:
            response_data = {"status": "error", "message": str(exc)}

        body_bytes = json.dumps(response_data, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)


def main() -> None:
    os.chdir(ROOT_DIR)
    host, port = "127.0.0.1", 8501
    url = f"http://{host}:{port}/aura_dashboard.html"
    print(f"[AURA WEB UI] Serving Live AURA 7-Tab Judging Dashboard at: {url}")
    print(
        "[AURA WEB UI] Live MCP 2.0 POST endpoints active: "
        "/api/validate_file, /api/ingest_calls, /api/review_batch, /api/review_call, /api/run_agent, /api/simulate_upgrade"
    )
    try:
        webbrowser.open(url)
    except Exception:
        pass
    server = ThreadingHTTPServer((host, port), AuraHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[AURA WEB UI] Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
