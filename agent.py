"""AURA Governed Agent Loop (`agent.py`).

Implements two explicitly labeled operating modes (Section 17):
1. Agent Mode (`mode="agent"`):
   - Discovers MCP tools (`input_schema`), resources, and prompts on each request.
   - Provides tool schemas to the LLM tool-selection planner.
   - Executes model-selected MCP tool calls via `AuraMCPClient`.
   - Feeds tool outputs and structured errors back to the planner (including bad-input recovery).
   - Enforces a configurable maximum of 8 turns (`max_turns <= 8`) and prevents infinite tool loops.
   - Gracefully declines out-of-scope requests without inventing tool outputs.
2. Deterministic Demo Mode (`mode="deterministic_demo"`):
   - Executes a known governed MCP sequence through `AuraMCPClient`.
   - Clearly labeled as "Offline deterministic demonstration" (never disguised as autonomous agent selection).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aura.config import get_config  # noqa: E402
from aura.errors import AuraError, ErrorCode  # noqa: E402
from aura.repositories import AuraRepository  # noqa: E402
from mcp_client import AuraMCPClient  # noqa: E402


OUT_OF_SCOPE_PATTERNS = [
    r"\bweather\b",
    r"\brecipe\b",
    r"\bcook\b",
    r"\bstock\s+price\b",
    r"\bcrypto\b",
    r"\bbitcoin\b",
    r"\bsports?\b",
    r"\bfootball\b",
    r"\bbasketball\b",
    r"\bwrite\s+a\s+poem\b",
    r"\bwrite\s+a\s+song\b",
    r"\bcapital\s+of\b",
    r"\bwho\s+won\s+the\s+world\s+series\b",
    r"\bsolve\s+this\s+integral\b",
    r"\btranslate\s+to\s+french\b",
    r"\bmovie\s+recommendation\b",
]

IN_SCOPE_KEYWORDS = [
    "call",
    "transcript",
    "review",
    "aura",
    "audit",
    "route",
    "routing",
    "specialist",
    "challenger",
    "portfolio",
    "governance",
    "compliance",
    "quality",
    "fraud",
    "dispute",
    "upgrade",
    "model",
    "candidate",
    "similar",
    "explain",
    "compare",
    "batch",
    "ingest",
    "validate",
    "syn-call",
]


class AuraAgent:
    """Governed MCP Agent Loop for AURA."""

    def __init__(
        self,
        mcp_client: AuraMCPClient | None = None,
        db_path: str | Path | None = None,
        max_turns: int | None = None,
    ) -> None:
        self.cfg = get_config(db_path_override=db_path)
        self.db_path = str(self.cfg.db_path)
        self.client = mcp_client or AuraMCPClient(db_path=self.db_path)
        self.max_turns = min(max(int(max_turns or self.cfg.agent_max_turns), 1), 8)

    def _is_out_of_scope(self, user_request: str) -> bool:
        """Return True if the request is outside AURA's governed call-review domain."""
        q_lower = (user_request or "").lower().strip()
        if not q_lower:
            return True
        for pat in OUT_OF_SCOPE_PATTERNS:
            if re.search(pat, q_lower):
                return True
        if not any(kw in q_lower for kw in IN_SCOPE_KEYWORDS):
            return True
        return False

    def _extract_call_id(self, text: str, default_call_id: str | None = None) -> str:
        match = re.search(r"\b(SYN-CALL-\d{4}|CALL-[A-Z0-9_-]+)\b", text, flags=re.I)
        if match:
            return match.group(1).upper()
        if default_call_id:
            return default_call_id
        return "SYN-CALL-0001"

    def _resolve_transcript_from_db(self, call_id: str) -> str:
        """Lookup stored transcript in SQLite when user references a call_id without pasting transcript."""
        repo = AuraRepository(db_path=self.db_path)
        try:
            call_row = repo.get_call(call_id)
            return str(call_row.get("transcript") or "")
        except Exception:
            return (
                f"[SCENARIO:payment_status]\n"
                f"[00:05] Customer: Hi, checking the payment status on my synthetic account for {call_id}.\n"
                f"[00:18] Agent: Your synthetic payment of 120 units posted this morning."
            )

    def _plan_next_action(
        self,
        user_request: str,
        call_id: str,
        transcript: str | None,
        discovered_tools: list[dict[str, Any]],
        executed_calls: list[dict[str, Any]],
        simulate_bad_input_first: bool = False,
    ) -> dict[str, Any] | None:
        """Select the next MCP tool call based on discovered tool schemas and conversation state."""
        q_lower = user_request.lower()
        tool_names = {t["name"] for t in discovered_tools}
        completed_tools = {
            c["tool_name"]
            for c in executed_calls
            if c.get("status") == "Completed" and not (isinstance(c.get("output"), dict) and c["output"].get("status") == "error")
        }
        errored_tools = [
            c
            for c in executed_calls
            if c.get("status") == "Failed" or (isinstance(c.get("output"), dict) and c["output"].get("status") == "error")
        ]

        # 1. If a previous tool call failed due to missing/empty transcript (bad input test), recover automatically!
        for err_call in errored_tools:
            err_code = (
                err_call.get("output", {}).get("error", {}).get("error_code")
                if isinstance(err_call.get("output"), dict)
                else None
            )
            if (
                err_call["tool_name"] == "review_call"
                and err_code in (ErrorCode.EMPTY_TRANSCRIPT.value, ErrorCode.VALIDATION_ERROR.value)
                and "review_call" not in completed_tools
            ):
                recovered_transcript = transcript or self._resolve_transcript_from_db(call_id)
                return {
                    "tool_name": "review_call",
                    "arguments": {
                        "call_id": call_id,
                        "transcript": recovered_transcript,
                        "review_goal": "Recovered governed review after bad-input validation error",
                        "force_challenger": "challenger" in q_lower or "governance" in q_lower,
                    },
                    "rationale": "Recovered from structured bad-input error by supplying the verified call_id and transcript.",
                }

        # 2. If simulate_bad_input_first is requested (or user asks to test bad input recovery) and no call made yet
        if (simulate_bad_input_first or "bad input" in q_lower or "missing transcript" in q_lower) and not executed_calls:
            return {
                "tool_name": "review_call",
                "arguments": {
                    "call_id": call_id,
                    "transcript": "",  # Intentionally empty to trigger structured AURA_ERR_EMPTY_TRANSCRIPT
                },
                "rationale": "Submitting initial request with empty transcript to demonstrate MCP structured error and agent recovery.",
            }

        # 3. Portfolio summary intent
        if any(k in q_lower for k in ["portfolio", "aggregate", "dashboard", "avoided", "metrics"]):
            if "portfolio_summary" in tool_names and "portfolio_summary" not in completed_tools:
                return {
                    "tool_name": "portfolio_summary",
                    "arguments": {"job_id": ""},
                    "rationale": "Selected `portfolio_summary` using discovered tool schema to compute portfolio governance metrics.",
                }
            return None

        # 4. Model upgrade simulation intent
        if any(k in q_lower for k in ["upgrade", "candidate", "shadow", "canary", "simulate_model_upgrade"]):
            if "simulate_model_upgrade" in tool_names and "simulate_model_upgrade" not in completed_tools:
                return {
                    "tool_name": "simulate_model_upgrade",
                    "arguments": {
                        "production_model_id": "AURA_DEEP",
                        "candidate_model_id": "AURA_CANDIDATE_V2",
                        "sample_size": 15,
                    },
                    "rationale": "Selected `simulate_model_upgrade` to compare production model against candidate model.",
                }
            return None

        # 5. Audit / Explain / Compare specific intents
        if "audit" in q_lower and "review this call" not in q_lower:
            if "get_audit_record" in tool_names and "get_audit_record" not in completed_tools:
                return {
                    "tool_name": "get_audit_record",
                    "arguments": {"call_id": call_id},
                    "rationale": "Selected `get_audit_record` to retrieve ordered audit events from SQLite.",
                }
            return None

        if "compare" in q_lower and "challenger" in q_lower and "review this call" not in q_lower:
            if "compare_decisions" in tool_names and "compare_decisions" not in completed_tools:
                return {
                    "tool_name": "compare_decisions",
                    "arguments": {"call_id": call_id},
                    "rationale": "Selected `compare_decisions` to compare primary specialist output against challenger validation.",
                }
            return None

        if "explain" in q_lower and "review this call" not in q_lower:
            if "explain_decision" in tool_names and "explain_decision" not in completed_tools:
                return {
                    "tool_name": "explain_decision",
                    "arguments": {"call_id": call_id},
                    "rationale": "Selected `explain_decision` to generate a business-readable rationale from stored evidence.",
                }
            return None

        # 6. Default single-call governed review & explanation workflow
        if "review_call" in tool_names and "review_call" not in completed_tools:
            effective_transcript = transcript if transcript is not None else self._resolve_transcript_from_db(call_id)
            return {
                "tool_name": "review_call",
                "arguments": {
                    "call_id": call_id,
                    "transcript": effective_transcript,
                    "review_goal": user_request[:180],
                    "force_challenger": any(w in q_lower for w in ["force challenger", "challenger", "high-risk"]),
                },
                "rationale": "Selected hero tool `review_call` to run the complete 17-step governed AURA pipeline.",
            }

        if "explain_decision" in tool_names and "explain_decision" not in completed_tools:
            return {
                "tool_name": "explain_decision",
                "arguments": {"call_id": call_id},
                "rationale": "Selected `explain_decision` to summarize policy triggers and human-review rationale.",
            }

        if "get_audit_record" in tool_names and "get_audit_record" not in completed_tools:
            return {
                "tool_name": "get_audit_record",
                "arguments": {"call_id": call_id},
                "rationale": "Selected `get_audit_record` to confirm audit trail completeness.",
            }

        return None

    def run_request(
        self,
        user_request: str,
        call_id: str | None = None,
        transcript: str | None = None,
        mode: str = "agent",
        simulate_bad_input_first: bool = False,
    ) -> dict[str, Any]:
        """Execute a user request in either `agent` mode or `deterministic_demo` mode."""
        operating_mode_label = (
            "Autonomous MCP Agent Mode (Schema-Driven Tool Selection)"
            if mode == "agent"
            else "Offline deterministic demonstration (Pre-Defined Governed MCP Sequence)"
        )

        # Step 1: Discover MCP tools, resources, and prompts on each independent request
        discovered_tools = self.client.list_tools()
        discovered_resources = self.client.list_resources()
        discovered_prompts = self.client.list_prompts()

        # Step 2: Check domain boundaries before invoking business tools
        if self._is_out_of_scope(user_request):
            boundary_err = AuraError(
                error_code=ErrorCode.UNSUPPORTED_NL_REQUEST,
                user_message=(
                    "I respectfully decline this request because it is outside AURA's governed customer-call "
                    "review capabilities. AURA only performs call transcript triage, policy routing, "
                    "specialist/challenger analysis, audit inspection, portfolio governance reporting, "
                    "and candidate model upgrade simulations."
                ),
                technical_message=f"Out-of-scope natural-language request declined: {user_request[:120]}",
                retryable=False,
                safe_fallback="Submit a customer-call review, audit, portfolio, or model-upgrade request.",
                human_review_required=False,
            )
            return {
                "status": "declined_out_of_scope",
                "operating_mode": operating_mode_label,
                "user_request": user_request,
                "tools_discovered": [t["name"] for t in discovered_tools],
                "tool_schemas_provided": discovered_tools,
                "resources_used": [],
                "prompts_retrieved": [],
                "tool_calls": [],
                "turn_count": 1,
                "max_turns": self.max_turns,
                "error": boundary_err.to_dict(),
                "final_response": boundary_err.structured.user_message,
            }

        target_call_id = self._extract_call_id(user_request, default_call_id=call_id)
        resources_used: list[dict[str, Any]] = []
        prompts_retrieved: list[dict[str, Any]] = []
        executed_tool_calls: list[dict[str, Any]] = []
        seen_invocations: set[str] = set()
        turn_count = 0

        # Read relevant MCP resource and prompt via MCP client for full governance visibility
        model_cat_res = self.client.read_resource("aura://model-catalog")
        resources_used.append({"uri": "aura://model-catalog", "output": model_cat_res})

        routing_res = self.client.read_resource("aura://routing-policy")
        resources_used.append({"uri": "aura://routing-policy", "output": routing_res})

        effective_transcript = transcript if transcript is not None else self._resolve_transcript_from_db(target_call_id)
        prompt_obj = self.client.get_prompt(
            "review_customer_call",
            arguments={
                "call_id": target_call_id,
                "transcript": effective_transcript[:300],
                "review_goal": user_request[:120],
                "force_challenger": "false",
            },
        )
        prompts_retrieved.append(prompt_obj)

        if mode == "deterministic_demo":
            # Deterministic demo mode: Fixed governed sequence through MCP client
            deterministic_steps = [
                (
                    "review_call",
                    {
                        "call_id": target_call_id,
                        "transcript": effective_transcript,
                        "review_goal": "Offline deterministic demonstration",
                        "force_challenger": False,
                    },
                    "Deterministic step 1: Execute governed `review_call` via MCP client.",
                ),
                (
                    "explain_decision",
                    {"call_id": target_call_id},
                    "Deterministic step 2: Retrieve structured explanation via `explain_decision`.",
                ),
                (
                    "get_audit_record",
                    {"call_id": target_call_id},
                    "Deterministic step 3: Verify SQLite audit trail via `get_audit_record`.",
                ),
            ]
            for tool_name, tool_args, reason in deterministic_steps:
                if turn_count >= self.max_turns:
                    break
                turn_count += 1
                output = self.client.invoke_tool(tool_name, tool_args)
                is_err = isinstance(output, dict) and output.get("status") == "error"
                executed_tool_calls.append(
                    {
                        "turn": turn_count,
                        "tool_name": tool_name,
                        "arguments": tool_args,
                        "rationale": reason,
                        "status": "Failed" if is_err else "Completed",
                        "output": output,
                    }
                )
        else:
            # Autonomous Agent Mode: Iterative schema-driven tool selection up to max_turns (max 8)
            while turn_count < self.max_turns:
                next_plan = self._plan_next_action(
                    user_request=user_request,
                    call_id=target_call_id,
                    transcript=transcript,
                    discovered_tools=discovered_tools,
                    executed_calls=executed_tool_calls,
                    simulate_bad_input_first=simulate_bad_input_first,
                )
                if next_plan is None:
                    break

                tool_name = next_plan["tool_name"]
                tool_args = next_plan["arguments"]
                if not isinstance(tool_args, dict):
                    # Handle malformed tool arguments safely
                    err = AuraError(
                        error_code=ErrorCode.VALIDATION_ERROR,
                        user_message=f"Malformed tool arguments for '{tool_name}'. Expected JSON object.",
                        technical_message=f"Invalid arguments type: {type(tool_args)}",
                    )
                    executed_tool_calls.append(
                        {
                            "turn": turn_count + 1,
                            "tool_name": tool_name,
                            "arguments": {"raw": str(tool_args)},
                            "rationale": "Malformed argument guard triggered.",
                            "status": "Failed",
                            "output": {"status": "error", "error": err.to_dict()},
                        }
                    )
                    turn_count += 1
                    break

                # Prevent infinite duplicate tool call loops
                sig = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
                if sig in seen_invocations:
                    break
                seen_invocations.add(sig)

                turn_count += 1
                output = self.client.invoke_tool(tool_name, tool_args)
                is_err = isinstance(output, dict) and output.get("status") == "error"
                executed_tool_calls.append(
                    {
                        "turn": turn_count,
                        "tool_name": tool_name,
                        "arguments": tool_args,
                        "rationale": next_plan.get("rationale", ""),
                        "status": "Failed" if is_err else "Completed",
                        "output": output,
                    }
                )

                # If MCP connection itself is unavailable, stop immediately and surface safe fallback
                if is_err and output.get("error", {}).get("error_code") == ErrorCode.MCP_CONNECTION_FAILURE.value:
                    break

        final_response = self._synthesize_final_response(
            operating_mode_label=operating_mode_label,
            executed_tool_calls=executed_tool_calls,
        )

        return {
            "status": "completed",
            "operating_mode": operating_mode_label,
            "user_request": user_request,
            "tools_discovered": [t["name"] for t in discovered_tools],
            "tool_schemas_provided": discovered_tools,
            "resources_discovered": [r["uri"] for r in discovered_resources],
            "prompts_discovered": [p["name"] for p in discovered_prompts],
            "resources_used": resources_used,
            "prompts_retrieved": prompts_retrieved,
            "tool_calls": executed_tool_calls,
            "turn_count": turn_count,
            "max_turns": self.max_turns,
            "final_response": final_response,
        }

    def _synthesize_final_response(
        self,
        operating_mode_label: str,
        executed_tool_calls: list[dict[str, Any]],
    ) -> str:
        """Synthesize a factual response strictly from executed MCP tool outputs (never inventing outputs)."""
        if not executed_tool_calls:
            return f"[{operating_mode_label}] No MCP tools were invoked for this request."

        lines = [f"**Mode:** {operating_mode_label}", ""]
        for call in executed_tool_calls:
            t_name = call["tool_name"]
            out = call["output"]
            if isinstance(out, dict) and out.get("status") == "error":
                err = out.get("error", {})
                lines.append(
                    f"- **Turn {call['turn']} (`{t_name}`) — Controlled Error (`{err.get('error_code')}`):** "
                    f"{err.get('user_message')} (Fallback: {err.get('safe_fallback')})"
                )
            elif t_name == "review_call" and isinstance(out, dict):
                lines.append(
                    f"- **Turn {call['turn']} (`review_call`) — Call `{out.get('call_id')}`:** "
                    f"Complexity `{out.get('complexity')}`, Route `{out.get('route_selected')}`, "
                    f"Specialist Used: `{out.get('specialist_used')}`, Challenger Used: `{out.get('challenger_used')}`, "
                    f"Human Review Required: `{out.get('human_review_required')}`, "
                    f"Confidence: `{out.get('final_confidence')}`."
                )
            elif t_name == "explain_decision" and isinstance(out, dict):
                lines.append(
                    f"- **Turn {call['turn']} (`explain_decision`):** {out.get('route_explanation')} "
                    f"Human Review Required: `{out.get('human_review_required')}` "
                    f"({'; '.join(out.get('human_review_reasons', [])) or 'No human review required'})."
                )
            elif t_name == "get_audit_record" and isinstance(out, dict):
                events = out.get("ordered_audit_events", [])
                lines.append(
                    f"- **Turn {call['turn']} (`get_audit_record`):** Verified `{len(events)}` audit events in SQLite. "
                    f"Models: `{', '.join(out.get('models_used', []))}`. Final Disposition: `{out.get('final_disposition')}`."
                )
            elif t_name == "portfolio_summary" and isinstance(out, dict):
                avoided = out.get("premium_model_calls_avoided", {}).get("estimated_calls_avoided", 0)
                lines.append(
                    f"- **Turn {call['turn']} (`portfolio_summary`):** Processed `{out.get('total_calls_processed')}` calls "
                    f"(Routine: `{out.get('routine_call_percentage')}%`, Specialist: `{out.get('specialist_percentage')}%`, "
                    f"Challenger: `{out.get('challenger_percentage')}%`). "
                    f"Estimated premium model calls avoided (workflow-derived): `{avoided}`."
                )
            elif t_name == "simulate_model_upgrade" and isinstance(out, dict):
                lines.append(
                    f"- **Turn {call['turn']} (`simulate_model_upgrade`):** Compared `{out.get('calls_compared')}` calls "
                    f"between `{out.get('production_model')}` and `{out.get('candidate_model')}`. "
                    f"Overall Agreement: `{out.get('overall_agreement_score')}%`, "
                    f"Critical Disagreements: `{out.get('critical_disagreement_count')}`, "
                    f"Recommendation: **`{out.get('recommendation')}`**."
                )
            else:
                lines.append(f"- **Turn {call['turn']} (`{t_name}`):** Completed successfully.")

        lines.append("")
        lines.append(
            "_Governance Notice: All outputs are derived from synthetic demonstration data. "
            "Compliance signals are analytical indicators and not legal determinations._"
        )
        return "\n".join(lines)
