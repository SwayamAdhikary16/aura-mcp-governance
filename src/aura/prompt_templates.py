"""Reusable MCP Prompts for AURA (Section 11).

Exposes 5 governed prompt templates that help MCP clients formulate structured
requests for AURA tools without replacing tool execution:
1. review_customer_call
2. investigate_high_risk_call
3. explain_aura_decision
4. summarize_portfolio_impact
5. compare_candidate_model
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from aura.database import initialize_database
from aura.repositories import AuraRepository


PROMPT_CATALOG_METADATA: list[dict[str, Any]] = [
    {
        "name": "review_customer_call",
        "description": (
            "Formulate a complete governed review request for a single customer call transcript "
            "using the `review_call` MCP tool."
        ),
        "arguments": ["call_id", "transcript", "review_goal", "force_challenger"],
    },
    {
        "name": "investigate_high_risk_call",
        "description": (
            "Formulate a deep specialist and challenger investigation request for a sensitive, "
            "disputed, fraud-related, compliance-related, escalated, or emotionally severe interaction."
        ),
        "arguments": ["call_id", "transcript", "risk_focus"],
    },
    {
        "name": "explain_aura_decision",
        "description": (
            "Formulate a business-readable explanation request for a completed call decision "
            "using stored audit records, policy triggers, and evidence via `explain_decision`."
        ),
        "arguments": ["call_id"],
    },
    {
        "name": "summarize_portfolio_impact",
        "description": (
            "Formulate a portfolio governance summary request covering routing efficiency, "
            "specialist/challenger usage, errors, and workflow-derived premium model call avoidance."
        ),
        "arguments": ["job_id"],
    },
    {
        "name": "compare_candidate_model",
        "description": (
            "Formulate a shadow-evaluation comparison request between a production model and "
            "a candidate model over a synthetic sample using `simulate_model_upgrade`."
        ),
        "arguments": ["production_model_id", "candidate_model_id", "sample_size"],
    },
]


def render_mcp_prompt(
    prompt_name: str,
    arguments: dict[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> str:
    """Render a reusable MCP prompt and log a PROMPT RETRIEVAL event in SQLite."""
    t0 = time.perf_counter()
    initialize_database(db_path=db_path, reset=False)
    repo = AuraRepository(db_path=db_path)
    args = arguments or {}
    corr_id = f"corr-{uuid.uuid4().hex[:12]}"
    call_id = str(args.get("call_id") or "") or None

    if prompt_name == "review_customer_call":
        cid = args.get("call_id", "SYN-CALL-0001")
        transcript = args.get("transcript", "[Paste synthetic transcript here]")
        goal = args.get("review_goal", "Complete governed triage, routing, and quality/compliance review")
        force_chal = bool(args.get("force_challenger", False))
        rendered = (
            f"Please execute a governed AURA review for Call ID '{cid}'.\n"
            f"- Review Goal: {goal}\n"
            f"- Force Challenger Validation: {force_chal}\n"
            f"- Required Tool: Invoke `review_call` with call_id='{cid}', force_challenger={force_chal}, "
            f"and the following synthetic transcript:\n\n{transcript}"
        )
    elif prompt_name == "investigate_high_risk_call":
        cid = args.get("call_id", "SYN-CALL-0012")
        transcript = args.get("transcript", "[Paste high-risk synthetic transcript here]")
        focus = args.get("risk_focus", "Fraud, Compliance, Dispute, Escalation, and Customer Safety")
        rendered = (
            f"Conduct a high-risk governed investigation for Call ID '{cid}' with focus on: {focus}.\n"
            "1. Read `aura://compliance-framework` and `aura://challenger-policy`.\n"
            f"2. Invoke `review_call` for call_id='{cid}' with force_challenger=True.\n"
            f"3. Invoke `compare_decisions` and `explain_decision` for call_id='{cid}'.\n"
            "4. Note that compliance indicators are analytical signals and not legal determinations.\n\n"
            f"TRANSCRIPT:\n{transcript}"
        )
    elif prompt_name == "explain_aura_decision":
        cid = args.get("call_id", "SYN-CALL-0001")
        rendered = (
            f"Provide a concise, leadership-ready explanation of the AURA governance decision for Call ID '{cid}'.\n"
            f"1. Invoke `explain_decision` with call_id='{cid}'.\n"
            f"2. Invoke `get_audit_record` with call_id='{cid}'.\n"
            "3. Summarize the route selected, policy triggers, transcript evidence, model/prompt versions, "
            "and whether human review is required (without exposing hidden chain-of-thought)."
        )
    elif prompt_name == "summarize_portfolio_impact":
        jid = args.get("job_id") or ""
        job_clause = f" for job_id='{jid}'" if jid else " across all processed jobs"
        rendered = (
            f"Summarize the AURA portfolio governance impact{job_clause}.\n"
            "1. Invoke `portfolio_summary`" + (f" with job_id='{jid}'." if jid else ".") + "\n"
            "2. Highlight routine vs. specialist vs. challenger routing percentages, risk-flag distribution, "
            "human-review rate, and the workflow-derived estimate of avoided premium model calls."
        )
    elif prompt_name == "compare_candidate_model":
        prod_id = args.get("production_model_id", "AURA_DEEP")
        cand_id = args.get("candidate_model_id", "AURA_CANDIDATE_V2")
        sample_size = int(args.get("sample_size", 20))
        rendered = (
            f"Evaluate candidate model upgrade readiness comparing production model '{prod_id}' "
            f"against candidate model '{cand_id}' over a sample of {sample_size} synthetic calls.\n"
            f"1. Read `aura://model-catalog` to inspect both models.\n"
            f"2. Invoke `simulate_model_upgrade` with production_model_id='{prod_id}', "
            f"candidate_model_id='{cand_id}', and sample_size={sample_size}.\n"
            "3. Report field-level agreement, critical disagreements, and the governed recommendation "
            "(explicitly noting that simulation never grants automatic production approval)."
        )
    else:
        raise ValueError(f"Unknown AURA MCP prompt: {prompt_name}")

    dur_ms = (time.perf_counter() - t0) * 1000.0
    repo.record_mcp_activity(
        correlation_id=corr_id,
        call_id=call_id,
        activity_type="PROMPT RETRIEVAL",
        operation_name=prompt_name,
        status="Completed",
        duration_ms=dur_ms,
        input_payload=args,
        output_payload={"prompt_name": prompt_name, "rendered_length": len(rendered)},
    )
    return rendered
