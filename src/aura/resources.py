"""Read-only MCP Resources for AURA (Section 10).

Exposes 8 governed enterprise resources:
- aura://model-catalog
- aura://routing-policy
- aura://challenger-policy
- aura://quality-framework
- aura://compliance-framework
- aura://output-schema
- aura://prompt-catalog
- aura://portfolio-summary
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from aura.database import initialize_database
from aura.metrics_service import MetricsService
from aura.repositories import AuraRepository
from aura.schemas import (
    ChallengerAnalysisResult,
    FinalConsolidatedResult,
    FirstPassResult,
    RoutineAnalysisResult,
    SpecialistAnalysisResult,
)


RESOURCE_METADATA: list[dict[str, str]] = [
    {
        "uri": "aura://model-catalog",
        "name": "AURA Governed Model Catalog",
        "description": (
            "Read-only catalog of available AI models (AURA_FAST, AURA_DEEP, AURA_CHALLENGER, candidates), "
            "including versions, roles, capabilities, cost/latency tiers, approval status, and enabled flags."
        ),
        "mime_type": "application/json",
    },
    {
        "uri": "aura://routing-policy",
        "name": "AURA Call Routing Policy",
        "description": (
            "Active SQLite-persisted routing rules governing when transcripts route to routine analysis "
            "(complexity 1-2) versus specialist analysis (complexity 4-5, borderline complexity 3 with flags, "
            "or mandatory risk indicators)."
        ),
        "mime_type": "application/json",
    },
    {
        "uri": "aura://challenger-policy",
        "name": "AURA Challenger & Human Review Governance Policy",
        "description": (
            "Active governance policy defining challenger confidence thresholds, mandatory challenger triggers, "
            "disagreement rules, critical-risk conditions, and mandatory human-review conditions."
        ),
        "mime_type": "application/json",
    },
    {
        "uri": "aura://quality-framework",
        "name": "AURA Contact Center Quality Evaluation Framework",
        "description": (
            "Configured non-duplicate quality evaluation dimensions: Next Step Clarity, Control of the Call, "
            "Option Framing, Objection Handling, and Empathy and Tone."
        ),
        "mime_type": "application/json",
    },
    {
        "uri": "aura://compliance-framework",
        "name": "AURA Analytical Compliance Indicator Guidance",
        "description": (
            "Configured review guidance and analytical indicators for complaint risk, misleading statements, "
            "harassment indicators, repeated-contact concerns, escalation, fraud, disputes, vulnerable-customer "
            "support, severe distress, threat, and self-harm. Explicitly analytical indicators, not legal determinations."
        ),
        "mime_type": "application/json",
    },
    {
        "uri": "aura://output-schema",
        "name": "AURA Structured Output JSON Schemas",
        "description": (
            "JSON Schema 2020-12 definitions and field descriptions for FirstPassResult, RoutineAnalysisResult, "
            "SpecialistAnalysisResult, ChallengerAnalysisResult, and FinalConsolidatedResult."
        ),
        "mime_type": "application/json",
    },
    {
        "uri": "aura://prompt-catalog",
        "name": "AURA Governed Prompt Version Catalog",
        "description": (
            "Active prompt names, semantic versions, roles, and SHA-256 verification hashes used by AURA stages. "
            "Exposes governance metadata only (never secrets or private chain-of-thought)."
        ),
        "mime_type": "application/json",
    },
    {
        "uri": "aura://portfolio-summary",
        "name": "AURA Live Portfolio Governance Summary",
        "description": (
            "Real-time aggregate processing, routing, risk-flag, deflection, and workflow-derived premium model "
            "call avoidance metrics queried from SQLite."
        ),
        "mime_type": "application/json",
    },
]


def read_aura_resource(uri: str, db_path: str | Path | None = None) -> dict[str, Any]:
    """Read an AURA governance resource by URI and record the MCP RESOURCE READ activity."""
    t0 = time.perf_counter()
    initialize_database(db_path=db_path, reset=False)
    repo = AuraRepository(db_path=db_path)
    corr_id = f"corr-{uuid.uuid4().hex[:12]}"

    clean_uri = uri.strip()
    payload: dict[str, Any]

    if clean_uri == "aura://model-catalog":
        models = repo.get_model_catalog(enabled_only=False)
        catalog_version = models[0]["catalog_version"] if models else "2026.09.1"
        payload = {
            "resource_uri": clean_uri,
            "catalog_version": catalog_version,
            "models": models,
        }
    elif clean_uri == "aura://routing-policy":
        rec = repo.get_active_routing_policy()
        payload = {
            "resource_uri": clean_uri,
            "policy_id": rec["policy_id"],
            "policy_version": rec["policy_version"],
            "policy_name": rec["policy_name"],
            "active": bool(rec["active"]),
            "routing_rules": rec["policy"].get("rules", {}),
            "descriptions": rec["policy"].get("descriptions", {}),
        }
    elif clean_uri == "aura://challenger-policy":
        rec = repo.get_active_governance_policy()
        payload = {
            "resource_uri": clean_uri,
            "policy_id": rec["policy_id"],
            "policy_version": rec["policy_version"],
            "policy_name": rec["policy_name"],
            "active": bool(rec["active"]),
            "challenger_rules": rec["policy"].get("rules", {}),
        }
    elif clean_uri == "aura://quality-framework":
        fw = repo.get_framework_resource("aura://quality-framework")
        payload = fw.get("content", {})
    elif clean_uri == "aura://compliance-framework":
        fw = repo.get_framework_resource("aura://compliance-framework")
        payload = fw.get("content", {})
    elif clean_uri == "aura://output-schema":
        payload = {
            "resource_uri": clean_uri,
            "schemas": {
                "first_pass_results": FirstPassResult.model_json_schema(),
                "routine_analysis": RoutineAnalysisResult.model_json_schema(),
                "specialist_analysis": SpecialistAnalysisResult.model_json_schema(),
                "challenger_analysis": ChallengerAnalysisResult.model_json_schema(),
                "final_consolidated_results": FinalConsolidatedResult.model_json_schema(),
            },
        }
    elif clean_uri == "aura://prompt-catalog":
        prompts = repo.get_prompt_catalog()
        payload = {
            "resource_uri": clean_uri,
            "governance_note": "Exposes prompt version metadata and hashes only. No secrets or chain-of-thought.",
            "prompts": prompts,
        }
    elif clean_uri == "aura://portfolio-summary":
        metrics = MetricsService(repo).get_portfolio_summary()
        payload = {
            "resource_uri": clean_uri,
            **metrics,
        }
    else:
        raise ValueError(f"Unknown AURA MCP resource URI: {clean_uri}")

    dur_ms = (time.perf_counter() - t0) * 1000.0
    repo.record_mcp_activity(
        correlation_id=corr_id,
        activity_type="RESOURCE READ",
        operation_name=clean_uri,
        status="Completed",
        duration_ms=dur_ms,
        input_payload={"resource_uri": clean_uri},
        output_payload={"resource_uri": clean_uri, "keys": list(payload.keys())},
    )
    return payload


def read_aura_resource_json(uri: str, db_path: str | Path | None = None) -> str:
    """Return formatted JSON string for an AURA resource URI."""
    return json.dumps(read_aura_resource(uri=uri, db_path=db_path), indent=2)
