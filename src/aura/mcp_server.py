"""Stateless MCP 2.0 Server for AURA (AI Unified Review Assistant).

Follows post-July-2026 MCP Python SDK 2.0 design:
- Uses `MCPServer` class (not deprecated `FastMCP` constructor patterns).
- Passes `transport`, `host`, and `port` to `mcp_server.run(...)` rather than the constructor.
- Ensures snake_case Python fields including `input_schema` on tool metadata.
- Remains 100% stateless across requests; all state is persisted in SQLite.
- Never writes application logs to stdout so stdio JSON-RPC frames remain uncorrupted.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional, Union

import mcp.types as mcp_types

# Ensure snake_case `input_schema` property is available on mcp.types.Tool across SDK builds
if not hasattr(mcp_types.Tool, "input_schema"):
    mcp_types.Tool.input_schema = property(lambda self: getattr(self, "inputSchema", {}))  # type: ignore[attr-defined]

try:
    from mcp.server import MCPServer as _SDKMCPServer  # type: ignore[attr-defined]
except ImportError:
    try:
        from mcp.server.mcpserver import MCPServer as _SDKMCPServer  # type: ignore[import-not-found]
    except ImportError:
        from mcp.server.fastmcp import FastMCP as _LegacyBase

        class _SDKMCPServer(_LegacyBase):
            """MCP 2.0 `MCPServer` interface adapter when running on a pre-2.0 environment."""

            def __init__(self, name: str, instructions: Optional[str] = None) -> None:
                super().__init__(name=name, instructions=instructions, stateless_http=True)

            def run(
                self,
                transport: str = "stdio",
                host: str = "127.0.0.1",
                port: int = 8080,
                **kwargs: Any,
            ) -> None:
                if hasattr(self, "settings"):
                    self.settings.host = host
                    self.settings.port = port
                    self.settings.stateless_http = True
                super().run(transport=transport, **kwargs)  # type: ignore[arg-type]


from aura.config import get_config  # noqa: E402
from aura.database import initialize_database  # noqa: E402
from aura.logging_config import configure_logging, get_logger  # noqa: E402
from aura.prompt_templates import render_mcp_prompt  # noqa: E402
from aura.resources import read_aura_resource_json  # noqa: E402
from aura.tools import (  # noqa: E402
    compare_decisions as tool_compare_decisions,
    explain_decision as tool_explain_decision,
    find_similar_calls as tool_find_similar_calls,
    get_audit_record as tool_get_audit_record,
    ingest_validated_calls as tool_ingest_validated_calls,
    portfolio_summary as tool_portfolio_summary,
    review_batch as tool_review_batch,
    review_call as tool_review_call,
    simulate_model_upgrade as tool_simulate_model_upgrade,
    validate_input_file as tool_validate_input_file,
)

configure_logging()
logger = get_logger("mcp_server")


class MCPServer(_SDKMCPServer):
    """Stateless MCP 2.0 Server class accepting transport, host, and port in `.run()`."""

    def __init__(self, name: str, instructions: Optional[str] = None) -> None:
        super().__init__(name=name, instructions=instructions)


def create_aura_mcp_server(db_path: Optional[Union[str, Path]] = None) -> MCPServer:
    """Create and configure the stateless AURA MCPServer instance."""
    initialize_database(db_path=db_path, reset=False)

    server = MCPServer(
        name="AURA-Governance-MCP-Server",
        instructions=(
            "AURA (AI Unified Review Assistant) is a stateless MCP 2.0 governance and orchestration server "
            "for customer-call transcripts. All business state is stored in SQLite. Compliance signals are "
            "analytical indicators and not legal determinations."
        ),
    )

    # =========================================================================
    # 1. Register MCP Tools (Section 12)
    # =========================================================================

    @server.tool(
        name="review_call",
        description=(
            "Hero Tool: Process one customer-call transcript through the complete 17-step governed AURA "
            "workflow (model catalog check, first-pass triage, routing policy evaluation, routine or "
            "specialist deep analysis, historical comparator lookup, challenger validation, consolidation, "
            "and SQLite audit logging). Writes results to SQLite and returns structured decision."
        ),
    )
    def mcp_review_call(
        call_id: str,
        transcript: str,
        review_goal: str = "Complete governed call analysis",
        force_challenger: bool = False,
        correlation_id: str = "",
    ) -> str:
        """Process one transcript through the complete governed AURA workflow.

        Use when analyzing a single customer call transcript end-to-end.
        Do not use for bulk batch jobs (use `review_batch`) or read-only audit queries (`get_audit_record`).
        Writes stage outputs and audit records to SQLite.
        """
        result = tool_review_call(
            call_id=call_id,
            transcript=transcript,
            review_goal=review_goal,
            force_challenger=force_challenger,
            correlation_id=correlation_id.strip() or None,
            db_path=db_path,
        )
        return json.dumps(result, indent=2)

    @server.tool(
        name="review_batch",
        description=(
            "Stateless batch processor: Execute governed AURA processing for valid transcripts already "
            "ingested into SQLite under `job_id`. Stores all progress and results in SQLite."
        ),
    )
    def mcp_review_batch(
        job_id: str = "",
        maximum_calls: int = 25,
        stop_on_error: bool = False,
        use_cached_results: bool = False,
    ) -> str:
        """Start or execute processing for valid transcripts already ingested into SQLite.

        Use after `ingest_validated_calls` to process a batch of calls.
        Do not use for raw file validation (`validate_input_file`).
        Reads and writes call and job state in SQLite.
        """
        result = tool_review_batch(
            job_id=job_id,
            maximum_calls=maximum_calls,
            stop_on_error=stop_on_error,
            use_cached_results=use_cached_results,
            db_path=db_path,
        )
        return json.dumps(result, indent=2)

    @server.tool(
        name="find_similar_calls",
        description=(
            "Read-only comparator lookup: Retrieve relevant processed synthetic calls from SQLite "
            "(excluding `call_id` itself) to provide informational historical context on resolution, "
            "routing, and deflection patterns."
        ),
    )
    def mcp_find_similar_calls(
        call_id: str,
        issue_category: str,
        issue_subcategory: str = "",
        maximum_results: int = 5,
        minimum_confidence: float = 0.65,
    ) -> str:
        """Retrieve relevant processed synthetic calls from SQLite to provide historical context.

        Use when contextualizing a call against historical category patterns.
        Never retrieves the same `call_id` as its own comparator. Historical patterns are context, not determinations.
        """
        result = tool_find_similar_calls(
            call_id=call_id,
            issue_category=issue_category,
            issue_subcategory=issue_subcategory,
            maximum_results=maximum_results,
            minimum_confidence=minimum_confidence,
            db_path=db_path,
        )
        return json.dumps(result, indent=2)

    @server.tool(
        name="explain_decision",
        description=(
            "Read-only governance explanation: Return a concise, business-readable explanation of a "
            "completed AURA decision using stored structured evidence, policy triggers, model/prompt "
            "versions, and human-review reasons (without private chain-of-thought)."
        ),
    )
    def mcp_explain_decision(call_id: str) -> str:
        """Explain a completed AURA result using stored structured evidence, policies, and audit events.

        Use when explaining why a call took a specific route or required human review.
        Returns `AURA_ERR_UNKNOWN_CALL_ID` if `call_id` is not found in SQLite.
        """
        result = tool_explain_decision(call_id=call_id, db_path=db_path)
        return json.dumps(result, indent=2)

    @server.tool(
        name="compare_decisions",
        description=(
            "Read-only challenger comparator: Compare the primary specialist decision (`AURA_DEEP`) "
            "with the independent challenger validation decision (`AURA_CHALLENGER`) for `call_id`."
        ),
    )
    def mcp_compare_decisions(call_id: str) -> str:
        """Compare the primary specialist decision with the challenger decision for `call_id`.

        Returns aligned fields, disagreement fields, primary values, challenger assessments,
        final disposition, and human-review status.
        """
        result = tool_compare_decisions(call_id=call_id, db_path=db_path)
        return json.dumps(result, indent=2)

    @server.tool(
        name="get_audit_record",
        description=(
            "Read-only audit log retrieval: Return the ordered chronological audit history for `call_id`, "
            "including models used, prompts used, policies read, tools invoked, stage durations, and final disposition."
        ),
    )
    def mcp_get_audit_record(call_id: str) -> str:
        """Retrieve the stored audit history for a call from SQLite.

        Strictly read-only business operation. Returns `AURA_ERR_UNKNOWN_CALL_ID` if `call_id` is unknown.
        """
        result = tool_get_audit_record(call_id=call_id, db_path=db_path)
        return json.dumps(result, indent=2)

    @server.tool(
        name="portfolio_summary",
        description=(
            "Read-only portfolio analytics: Calculate aggregate call-processing, routing efficiency, "
            "risk-flag distribution, deflection channel distribution, and workflow-derived premium-model "
            "call avoidance metrics from SQLite."
        ),
    )
    def mcp_portfolio_summary(job_id: str = "") -> str:
        """Calculate processing and governance metrics from SQLite across all jobs or a specific `job_id`."""
        result = tool_portfolio_summary(job_id=job_id, db_path=db_path)
        return json.dumps(result, indent=2)

    @server.tool(
        name="simulate_model_upgrade",
        description=(
            "Shadow upgrade evaluator: Compare stored production-model results against synthetic "
            "candidate-model results over a sample of processed calls and return field-level agreement, "
            "critical disagreements, and a governed rollout recommendation."
        ),
    )
    def mcp_simulate_model_upgrade(
        production_model_id: str = "AURA_DEEP",
        candidate_model_id: str = "AURA_CANDIDATE_V2",
        sample_size: int = 20,
        sample_filter: str = "",
    ) -> str:
        """Compare stored production-model results with synthetic candidate-model results.

        Never claims automatic production approval. Returns `AURA_ERR_UNKNOWN_MODEL_ID` or
        `AURA_ERR_DISABLED_MODEL` if an invalid or retired model is requested.
        """
        result = tool_simulate_model_upgrade(
            production_model_id=production_model_id,
            candidate_model_id=candidate_model_id,
            sample_size=sample_size,
            sample_filter=sample_filter,
            db_path=db_path,
        )
        return json.dumps(result, indent=2)

    @server.tool(
        name="validate_input_file",
        description=(
            "Pre-ingestion file validator: Validate an uploaded Excel (.xlsx) or CSV (.csv) file "
            "for required columns (`call_id`, `transcript`), duplicates, empty transcripts, and length limits."
        ),
    )
    def mcp_validate_input_file(
        file_path: str,
        replace_existing: bool = False,
    ) -> str:
        """Validate an uploaded Excel or CSV file before ingestion without modifying `calls`."""
        result = tool_validate_input_file(
            file_path=file_path,
            replace_existing=replace_existing,
            db_path=db_path,
        )
        return json.dumps(result, indent=2)

    @server.tool(
        name="ingest_validated_calls",
        description=(
            "Call ingestion tool: Validate an Excel (.xlsx) or CSV (.csv) file, insert all valid synthetic "
            "calls into SQLite, and create a `processing_jobs` entry for batch execution."
        ),
    )
    def mcp_ingest_validated_calls(
        file_path: str,
        replace_existing: bool = True,
    ) -> str:
        """Insert validated calls into SQLite and create a processing job."""
        result = tool_ingest_validated_calls(
            file_path=file_path,
            replace_existing=replace_existing,
            db_path=db_path,
        )
        return json.dumps(result, indent=2)

    # =========================================================================
    # 2. Register MCP Resources (Section 10)
    # =========================================================================

    @server.resource(
        "aura://model-catalog",
        name="AURA Governed Model Catalog",
        description="Available AI models, versions, roles, capabilities, cost/latency tiers, approval status, and enabled flags.",
        mime_type="application/json",
    )
    def res_model_catalog() -> str:
        return read_aura_resource_json("aura://model-catalog", db_path=db_path)

    @server.resource(
        "aura://routing-policy",
        name="AURA Call Routing Policy",
        description="Active SQLite routing policy governing routine vs. specialist analysis and critical risk triggers.",
        mime_type="application/json",
    )
    def res_routing_policy() -> str:
        return read_aura_resource_json("aura://routing-policy", db_path=db_path)

    @server.resource(
        "aura://challenger-policy",
        name="AURA Challenger & Human Review Governance Policy",
        description="Challenger confidence thresholds, mandatory triggers, disagreement rules, and human-review conditions.",
        mime_type="application/json",
    )
    def res_challenger_policy() -> str:
        return read_aura_resource_json("aura://challenger-policy", db_path=db_path)

    @server.resource(
        "aura://quality-framework",
        name="AURA Contact Center Quality Evaluation Framework",
        description="Non-duplicate quality dimensions: Next Step Clarity, Control of the Call, Option Framing, Objection Handling, Empathy and Tone.",
        mime_type="application/json",
    )
    def res_quality_framework() -> str:
        return read_aura_resource_json("aura://quality-framework", db_path=db_path)

    @server.resource(
        "aura://compliance-framework",
        name="AURA Analytical Compliance Indicator Guidance",
        description="Configured analytical compliance indicators and explicit legal non-determination disclaimer.",
        mime_type="application/json",
    )
    def res_compliance_framework() -> str:
        return read_aura_resource_json("aura://compliance-framework", db_path=db_path)

    @server.resource(
        "aura://output-schema",
        name="AURA Structured Output JSON Schemas",
        description="JSON schemas for FirstPassResult, RoutineAnalysisResult, SpecialistAnalysisResult, ChallengerAnalysisResult, and FinalConsolidatedResult.",
        mime_type="application/json",
    )
    def res_output_schema() -> str:
        return read_aura_resource_json("aura://output-schema", db_path=db_path)

    @server.resource(
        "aura://prompt-catalog",
        name="AURA Governed Prompt Version Catalog",
        description="Active prompt names, versions, roles, and SHA-256 verification hashes (no secrets or chain-of-thought).",
        mime_type="application/json",
    )
    def res_prompt_catalog() -> str:
        return read_aura_resource_json("aura://prompt-catalog", db_path=db_path)

    @server.resource(
        "aura://portfolio-summary",
        name="AURA Live Portfolio Governance Summary",
        description="Current aggregate call processing, routing, risk, and avoided-premium-call metrics from SQLite.",
        mime_type="application/json",
    )
    def res_portfolio_summary() -> str:
        return read_aura_resource_json("aura://portfolio-summary", db_path=db_path)

    # =========================================================================
    # 3. Register MCP Prompts (Section 11)
    # =========================================================================

    @server.prompt(
        name="review_customer_call",
        description="Create a complete governed review request for a single customer call transcript.",
    )
    def prompt_review_customer_call(
        call_id: str,
        transcript: str,
        review_goal: str = "Complete governed review",
        force_challenger: bool = False,
    ) -> str:
        return render_mcp_prompt(
            "review_customer_call",
            {
                "call_id": call_id,
                "transcript": transcript,
                "review_goal": review_goal,
                "force_challenger": force_challenger,
            },
            db_path=db_path,
        )

    @server.prompt(
        name="investigate_high_risk_call",
        description="Request deep specialist and challenger investigation of a sensitive, disputed, fraud, compliance, or safety-flagged call.",
    )
    def prompt_investigate_high_risk_call(
        call_id: str,
        transcript: str,
        risk_focus: str = "Fraud, Compliance, Dispute, Escalation, and Safety",
    ) -> str:
        return render_mcp_prompt(
            "investigate_high_risk_call",
            {
                "call_id": call_id,
                "transcript": transcript,
                "risk_focus": risk_focus,
            },
            db_path=db_path,
        )

    @server.prompt(
        name="explain_aura_decision",
        description="Request a business-readable explanation of a completed decision using stored audit records and evidence.",
    )
    def prompt_explain_aura_decision(call_id: str) -> str:
        return render_mcp_prompt("explain_aura_decision", {"call_id": call_id}, db_path=db_path)

    @server.prompt(
        name="summarize_portfolio_impact",
        description="Request a portfolio summary of routing efficiency, specialist usage, challenger usage, errors, and avoided premium calls.",
    )
    def prompt_summarize_portfolio_impact(job_id: str = "") -> str:
        return render_mcp_prompt("summarize_portfolio_impact", {"job_id": job_id}, db_path=db_path)

    @server.prompt(
        name="compare_candidate_model",
        description="Request shadow comparison of a production model and candidate model using a selected synthetic sample.",
    )
    def prompt_compare_candidate_model(
        production_model_id: str = "AURA_DEEP",
        candidate_model_id: str = "AURA_CANDIDATE_V2",
        sample_size: int = 20,
    ) -> str:
        return render_mcp_prompt(
            "compare_candidate_model",
            {
                "production_model_id": production_model_id,
                "candidate_model_id": candidate_model_id,
                "sample_size": sample_size,
            },
            db_path=db_path,
        )

    return server


def main() -> None:
    """Entry point for running the AURA MCP 2.0 Server via stdio or streamable-http."""
    cfg = get_config()
    parser = argparse.ArgumentParser(description="Run the stateless AURA MCP 2.0 Server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=cfg.mcp_transport,
        help="MCP transport protocol (default: stdio).",
    )
    parser.add_argument("--host", default=cfg.mcp_host, help="Host for streamable-http transport.")
    parser.add_argument("--port", type=int, default=cfg.mcp_port, help="Port for streamable-http transport.")
    parser.add_argument("--db-path", default=None, help="Optional custom SQLite database path.")
    args = parser.parse_args()

    server = create_aura_mcp_server(db_path=args.db_path)
    logger.info(
        "Starting AURA MCPServer (transport=%s, host=%s, port=%d)",
        args.transport,
        args.host,
        args.port,
    )
    # MCP 2.0 Requirement #7: Pass transport, host, and port to .run() rather than constructor
    server.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
