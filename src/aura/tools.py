"""Typed and self-describing MCP Tool handlers for AURA (Section 12).

Implements the 10 governed AURA MCP tools:
1. review_call (Hero Tool)
2. review_batch
3. find_similar_calls
4. explain_decision
5. compare_decisions
6. get_audit_record
7. portfolio_summary
8. simulate_model_upgrade
9. validate_input_file
10. ingest_validated_calls
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from aura.audit_service import AuditService
from aura.database import initialize_database
from aura.errors import AuraError, ErrorCode
from aura.ingestion_service import IngestionService
from aura.metrics_service import MetricsService
from aura.processing_service import ProcessingService
from aura.repositories import AuraRepository


def _execute_governed_tool(
    tool_name: str,
    call_id: str | None,
    input_payload: dict[str, Any],
    fn: Any,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Execute a tool handler, record MCP activity in SQLite, and return structured output or error."""
    t0 = time.perf_counter()
    initialize_database(db_path=db_path, reset=False)
    repo = AuraRepository(db_path=db_path)
    corr_id = str(input_payload.get("correlation_id") or f"corr-{uuid.uuid4().hex[:12]}")

    try:
        result = fn(repo, corr_id)
        dur_ms = (time.perf_counter() - t0) * 1000.0
        repo.record_mcp_activity(
            correlation_id=corr_id,
            call_id=call_id,
            activity_type="TOOL CALL",
            operation_name=tool_name,
            status="Completed",
            duration_ms=dur_ms,
            input_payload=input_payload,
            output_payload={
                "status": "Completed",
                "summary_keys": list(result.keys())[:8] if isinstance(result, dict) else ["result"],
            },
        )
        return result
    except AuraError as exc:
        dur_ms = (time.perf_counter() - t0) * 1000.0
        err_dict = exc.to_dict()
        repo.record_mcp_activity(
            correlation_id=corr_id,
            call_id=call_id,
            activity_type="ERROR",
            operation_name=tool_name,
            status="Failed",
            duration_ms=dur_ms,
            input_payload=input_payload,
            output_payload=err_dict,
            error_message=exc.structured.user_message,
        )
        return {
            "status": "error",
            "error": err_dict,
        }
    except Exception as exc:
        dur_ms = (time.perf_counter() - t0) * 1000.0
        wrapped = AuraError(
            error_code=ErrorCode.MCP_TOOL_FAILURE,
            user_message=f"Tool '{tool_name}' encountered an unexpected execution error.",
            technical_message=str(exc),
            retryable=False,
            human_review_required=True,
            correlation_id=corr_id,
        )
        err_dict = wrapped.to_dict()
        repo.record_mcp_activity(
            correlation_id=corr_id,
            call_id=call_id,
            activity_type="ERROR",
            operation_name=tool_name,
            status="Failed",
            duration_ms=dur_ms,
            input_payload=input_payload,
            output_payload=err_dict,
            error_message=wrapped.structured.user_message,
        )
        return {
            "status": "error",
            "error": err_dict,
        }


def review_call(
    call_id: str,
    transcript: str,
    review_goal: str = "Complete governed call analysis",
    force_challenger: bool = False,
    correlation_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Process one customer-call transcript through the complete 17-step governed AURA workflow.

    WHEN TO USE:
        Use this hero tool whenever you need to analyze a single customer-call transcript
        end-to-end with model catalog verification, first-pass triage, policy-based routing,
        routine or specialist deep analysis, historical comparator lookup, challenger validation,
        decision consolidation, and full SQLite audit logging.

    WHEN NOT TO USE:
        Do not use this tool to process an entire batch job at once (use `review_batch` instead)
        or merely to read an existing audit log without re-analyzing (use `get_audit_record` or
        `explain_decision` instead).

    REQUIRED INPUT:
        - call_id (str): Unique identifier for the call (e.g., "SYN-CALL-0001").
        - transcript (str): Full text of the synthetic customer call transcript.

    OPTIONAL INPUT:
        - review_goal (str): Specific review objective for triage and analysis.
        - force_challenger (bool): Force independent challenger validation even if not policy-mandated.
        - correlation_id (str | None): Optional correlation ID for cross-system tracing.

    OUTPUT RETURNED:
        Dictionary containing `correlation_id`, `call_id`, `processing_status`, `first_pass_summary`,
        `detected_flags`, `complexity`, `route_selected`, `routing_reasons`, `specialist_used`,
        `historical_context_used`, `challenger_used`, `challenger_reason`, `final_decision`,
        `human_review_required`, `final_confidence`, and `audit_record_available`.

    READ / WRITE BEHAVIOR:
        READS: `model_catalog`, `routing_policies`, `governance_policies`, and historical `final_results`.
        WRITES: `calls`, `first_pass_results`, `specialist_results`, `challenger_results`,
        `final_results`, `audit_log`, and `mcp_activity`.

    POSSIBLE ERRORS & BOUNDARIES:
        Returns structured error with codes `AURA_ERR_VALIDATION_ERROR`, `AURA_ERR_EMPTY_TRANSCRIPT`,
        `AURA_ERR_TRANSCRIPT_TOO_LONG`, `AURA_ERR_INVALID_LLM_JSON`, or `AURA_ERR_LLM_TIMEOUT`.
    """
    payload = {
        "call_id": call_id,
        "transcript_preview": (transcript or "")[:120],
        "review_goal": review_goal,
        "force_challenger": force_challenger,
        "correlation_id": correlation_id,
    }

    def _run(repo: AuraRepository, corr_id: str) -> dict[str, Any]:
        svc = ProcessingService(repo)
        res = svc.review_call(
            call_id=call_id,
            transcript=transcript,
            review_goal=review_goal,
            force_challenger=force_challenger,
            correlation_id=corr_id,
        )
        return res.model_dump()

    return _execute_governed_tool("review_call", call_id, payload, _run, db_path=db_path)


def review_batch(
    job_id: str = "",
    maximum_calls: int = 25,
    stop_on_error: bool = False,
    use_cached_results: bool = False,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Execute governed batch processing for valid transcripts already ingested into SQLite.

    WHEN TO USE:
        Use this tool after calls have been ingested into SQLite (via `ingest_validated_calls`)
        to process up to `maximum_calls` transcripts sequentially under full AURA governance.

    WHEN NOT TO USE:
        Do not use this tool to validate a raw Excel file before ingestion (use `validate_input_file`)
        or to analyze an ad-hoc transcript not yet stored in SQLite (use `review_call`).

    REQUIRED INPUT:
        - job_id (str): Processing job identifier (pass empty string "" to process across all pending calls).
        - maximum_calls (int): Maximum number of calls to process in this invocation (1 to 500).
        - stop_on_error (bool): Whether to halt the batch immediately if any call fails.
        - use_cached_results (bool): Whether to reuse existing completed results in SQLite when available.

    OUTPUT RETURNED:
        Dictionary with `job_id`, `processed_count`, `successful_count`, `failed_count`,
        `skipped_cached_count`, `processing_status`, and per-call `results`.

    READ / WRITE BEHAVIOR:
        Stateless MCP execution. Reads and writes all job and call state in SQLite.

    POSSIBLE ERRORS & BOUNDARIES:
        Returns structured error on database lock (`AURA_ERR_DATABASE_LOCK`) or missing policy configuration.
    """
    clean_job_id = job_id.strip() if job_id else None
    payload = {
        "job_id": clean_job_id,
        "maximum_calls": maximum_calls,
        "stop_on_error": stop_on_error,
        "use_cached_results": use_cached_results,
    }

    def _run(repo: AuraRepository, _corr_id: str) -> dict[str, Any]:
        svc = ProcessingService(repo)
        return svc.review_batch(
            job_id=clean_job_id,
            maximum_calls=maximum_calls,
            stop_on_error=stop_on_error,
            use_cached_results=use_cached_results,
        )

    return _execute_governed_tool("review_batch", None, payload, _run, db_path=db_path)


def find_similar_calls(
    call_id: str,
    issue_category: str,
    issue_subcategory: str = "",
    maximum_results: int = 5,
    minimum_confidence: float = 0.65,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Retrieve relevant processed synthetic calls from SQLite to provide historical context.

    WHEN TO USE:
        Use this tool when analyzing a call to inspect how prior calls in the same `issue_category`
        or `issue_subcategory` were routed, resolved, or deflected.

    WHEN NOT TO USE:
        Do not treat historical patterns as deterministic rules for an individual call outcome,
        and do not use this tool to retrieve the full raw transcript of another customer's call.

    REQUIRED INPUT:
        - call_id (str): Current call identifier (explicitly excluded from comparator results).
        - issue_category (str): Normalized business category (e.g., "Billing", "Dispute", "Fraud").

    OPTIONAL INPUT:
        - issue_subcategory (str): Optional subcategory filter.
        - maximum_results (int): Maximum number of comparators to summarize (1 to 25).
        - minimum_confidence (float): Minimum confidence threshold for historical comparators (0.0 to 1.0).

    OUTPUT RETURNED:
        Dictionary containing `similar_call_count`, `selected_anonymized_call_ids`,
        `common_resolution_statuses`, `common_deflection_channels`, `common_route_outcomes`,
        and an explicit `governance_warning`.

    READ / WRITE BEHAVIOR:
        READ-ONLY query against `first_pass_results`, `specialist_results`, and `final_results`
        (plus writes an `mcp_activity` trace row). Never returns `call_id` as its own comparator.

    POSSIBLE ERRORS & BOUNDARIES:
        Returns empty counts safely if no historical calls match the filter criteria.
    """
    payload = {
        "call_id": call_id,
        "issue_category": issue_category,
        "issue_subcategory": issue_subcategory,
        "maximum_results": maximum_results,
        "minimum_confidence": minimum_confidence,
    }

    def _run(repo: AuraRepository, _corr_id: str) -> dict[str, Any]:
        svc = ProcessingService(repo)
        return svc._find_similar_context(
            call_id=call_id,
            issue_category=issue_category,
            issue_subcategory=issue_subcategory.strip() or None,
            maximum_results=maximum_results,
            minimum_confidence=minimum_confidence,
        )

    return _execute_governed_tool("find_similar_calls", call_id, payload, _run, db_path=db_path)


def explain_decision(
    call_id: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Explain a completed AURA governance decision using stored structured evidence, policies, and audit events.

    WHEN TO USE:
        Use this tool when a user, quality reviewer, or governance judge asks why a specific call
        was routed to routine or specialist analysis, why challenger validation was triggered,
        or why human review is required.

    WHEN NOT TO USE:
        Do not use this tool on a call that has not yet been ingested or processed (use `review_call` first).

    REQUIRED INPUT:
        - call_id (str): Unique identifier of the processed call.

    OUTPUT RETURNED:
        Dictionary containing `route_explanation`, `critical_evidence`, `policy_triggers`,
        `models_and_prompts`, `specialist_rationale`, `challenger_rationale`,
        `unresolved_disagreements`, `human_review_required`, and `human_review_reasons`.
        Never exposes private chain-of-thought.

    READ / WRITE BEHAVIOR:
        READ-ONLY query of decision and audit tables (plus `mcp_activity` trace logging).

    POSSIBLE ERRORS & BOUNDARIES:
        Returns `AURA_ERR_UNKNOWN_CALL_ID` if `call_id` does not exist in SQLite.
    """
    payload = {"call_id": call_id}

    def _run(repo: AuraRepository, _corr_id: str) -> dict[str, Any]:
        return AuditService(repo).explain_decision(call_id=call_id)

    return _execute_governed_tool("explain_decision", call_id, payload, _run, db_path=db_path)


def compare_decisions(
    call_id: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Compare the primary specialist decision with the independent challenger validation decision.

    WHEN TO USE:
        Use this tool to inspect field-by-field alignment or disagreement between `AURA_DEEP`
        (primary analysis) and `AURA_CHALLENGER` (independent validation) for a specific call.

    WHEN NOT TO USE:
        Do not use this tool to compare two models across an entire portfolio sample
        (use `simulate_model_upgrade` for portfolio-level shadow model comparisons).

    REQUIRED INPUT:
        - call_id (str): Unique identifier of the call.

    OUTPUT RETURNED:
        Dictionary containing `aligned_fields`, `disagreement_fields`, `primary_values`,
        `challenger_assessments`, `final_disposition`, and `human_review_status`.

    READ / WRITE BEHAVIOR:
        READ-ONLY query of `specialist_results`, `challenger_results`, and `final_results`
        (plus `mcp_activity` trace logging).

    POSSIBLE ERRORS & BOUNDARIES:
        Returns `AURA_ERR_UNKNOWN_CALL_ID` if `call_id` is not found in SQLite.
    """
    payload = {"call_id": call_id}

    def _run(repo: AuraRepository, _corr_id: str) -> dict[str, Any]:
        return AuditService(repo).compare_decisions(call_id=call_id)

    return _execute_governed_tool("compare_decisions", call_id, payload, _run, db_path=db_path)


def get_audit_record(
    call_id: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Retrieve the complete chronological audit history for a call from SQLite.

    WHEN TO USE:
        Use this read-only tool when inspecting full governance traceability for a call,
        including ordered audit events, model versions, prompt hashes/versions, policy URIs read,
        stage durations in milliseconds, and final disposition.

    WHEN NOT TO USE:
        Do not use this tool to modify or re-run a call review.

    REQUIRED INPUT:
        - call_id (str): Unique identifier of the call.

    OUTPUT RETURNED:
        Dictionary containing `ordered_audit_events`, `models_used`, `prompts_used`,
        `policies_read`, `tools_invoked`, `stage_durations_ms`, `successful_stages`,
        `failed_stages`, and `final_disposition`.

    READ / WRITE BEHAVIOR:
        Strictly READ-ONLY business query (records `mcp_activity` read trace).

    POSSIBLE ERRORS & BOUNDARIES:
        Returns `AURA_ERR_UNKNOWN_CALL_ID` if `call_id` is unknown.
    """
    payload = {"call_id": call_id}

    def _run(repo: AuraRepository, _corr_id: str) -> dict[str, Any]:
        return AuditService(repo).get_audit_record(call_id=call_id)

    return _execute_governed_tool("get_audit_record", call_id, payload, _run, db_path=db_path)


def portfolio_summary(
    job_id: str = "",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Calculate aggregate call-processing and governance metrics from SQLite.

    WHEN TO USE:
        Use this tool to retrieve executive dashboard statistics across all processed calls
        or a specific batch `job_id`, including routing percentages, specialist/challenger rates,
        risk-flag distributions, deflection channel counts, and workflow-derived estimates of
        avoided premium model calls.

    WHEN NOT TO USE:
        Do not use this tool to inspect transcript-level evidence for a single call
        (use `explain_decision` or `get_audit_record` instead).

    OPTIONAL INPUT:
        - job_id (str): Optional processing job ID filter (pass "" for all jobs).

    OUTPUT RETURNED:
        Dictionary with `total_calls_ingested`, `total_calls_processed`, `successful_calls`,
        `failed_calls`, `first_pass_only_calls`, `specialist_review_calls`, `challenger_review_calls`,
        `human_review_calls`, `routine_call_percentage`, `specialist_percentage`,
        `challenger_percentage`, `average_stage_durations_ms`, `premium_model_calls_avoided`
        (labeled as a workflow-derived estimate), `risk_flag_distribution`,
        `issue_category_distribution`, and `deflection_signal_distribution`.

    READ / WRITE BEHAVIOR:
        READ-ONLY aggregation from SQLite tables.

    POSSIBLE ERRORS & BOUNDARIES:
        Returns zeroed metrics safely if no calls have been processed yet.
    """
    clean_job_id = job_id.strip() if job_id else None
    payload = {"job_id": clean_job_id}

    def _run(repo: AuraRepository, _corr_id: str) -> dict[str, Any]:
        return MetricsService(repo).get_portfolio_summary(job_id=clean_job_id)

    return _execute_governed_tool("portfolio_summary", None, payload, _run, db_path=db_path)


def simulate_model_upgrade(
    production_model_id: str = "AURA_DEEP",
    candidate_model_id: str = "AURA_CANDIDATE_V2",
    sample_size: int = 20,
    sample_filter: str = "",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Compare stored production-model results with synthetic candidate-model results for upgrade evaluation.

    WHEN TO USE:
        Use this tool when evaluating a candidate model release (e.g., `AURA_CANDIDATE_V2`)
        against an active production model (e.g., `AURA_DEEP` or `AURA_FAST`) across a sample
        of processed synthetic calls.

    WHEN NOT TO USE:
        Do not use this tool to claim automatic production approval of a model. All recommendations
        are advisory governance signals (`insufficient_evidence`, `continue_shadow_testing`,
        `candidate_for_canary`, or `not_ready`).

    REQUIRED INPUT:
        - production_model_id (str): Active model ID in `aura://model-catalog`.
        - candidate_model_id (str): Candidate model ID in `aura://model-catalog`.
        - sample_size (int): Number of processed calls to compare (1 to 100).

    OPTIONAL INPUT:
        - sample_filter (str): Optional category or risk tier filter (e.g., "Fraud", "Dispute", "High").

    OUTPUT RETURNED:
        Dictionary with `calls_compared`, `overall_agreement_score`, `field_level_agreement`,
        `critical_disagreement_count`, `high_risk_disagreement_details`, `recommendation`,
        `recommendation_rules_explanation`, and `sample_limitations`.

    READ / WRITE BEHAVIOR:
        READS `model_catalog`, `calls`, and `final_results`; logs `mcp_activity`.

    POSSIBLE ERRORS & BOUNDARIES:
        Returns `AURA_ERR_UNKNOWN_MODEL_ID` if a model ID does not exist or `AURA_ERR_DISABLED_MODEL`
        if a retired/disabled model (such as `AURA_LEGACY_DISABLED`) is requested.
    """
    payload = {
        "production_model_id": production_model_id,
        "candidate_model_id": candidate_model_id,
        "sample_size": sample_size,
        "sample_filter": sample_filter,
    }

    def _run(repo: AuraRepository, _corr_id: str) -> dict[str, Any]:
        return MetricsService(repo).simulate_model_upgrade(
            production_model_id=production_model_id,
            candidate_model_id=candidate_model_id,
            sample_size=sample_size,
            sample_filter=sample_filter.strip() or None,
        )

    return _execute_governed_tool("simulate_model_upgrade", None, payload, _run, db_path=db_path)


def validate_input_file(
    file_path: str,
    replace_existing: bool = False,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate an uploaded Excel (.xlsx) or CSV (.csv) file before ingesting calls into SQLite.

    WHEN TO USE:
        Use this tool prior to ingestion to check for required columns (`call_id`, `transcript`),
        detect duplicate call identifiers, flag empty or over-length transcripts, and obtain
        row-level validation errors without modifying the `calls` table.

    WHEN NOT TO USE:
        Do not use this tool to persist calls into SQLite (use `ingest_validated_calls` after
        validation succeeds).

    REQUIRED INPUT:
        - file_path (str): Server-accessible path to the `.xlsx` or `.csv` file.
        - replace_existing (bool): Whether existing `call_id` records in SQLite are allowed to be overwritten.

    OUTPUT RETURNED:
        Dictionary with `valid_file`, `total_rows`, `valid_rows`, `invalid_rows`,
        `duplicate_identifiers`, `missing_required_columns`, `row_level_errors`, and `synthetic_data_label`.

    READ / WRITE BEHAVIOR:
        READ-ONLY validation (checks `calls` for existing IDs and logs `mcp_activity`).

    POSSIBLE ERRORS & BOUNDARIES:
        Returns `AURA_ERR_INVALID_FILE_TYPE` if the file does not exist or has an unsupported extension.
    """
    payload = {"file_path": file_path, "replace_existing": replace_existing}

    def _run(repo: AuraRepository, _corr_id: str) -> dict[str, Any]:
        summary, _ = IngestionService(repo).validate_file(
            file_path=file_path,
            replace_existing=replace_existing,
        )
        return summary.model_dump()

    return _execute_governed_tool("validate_input_file", None, payload, _run, db_path=db_path)


def ingest_validated_calls(
    file_path: str,
    replace_existing: bool = True,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate an Excel/CSV file, insert all valid calls into SQLite, and create a processing job.

    WHEN TO USE:
        Use this tool to load valid synthetic call rows from a server-accessible `.xlsx` or `.csv`
        file into the `calls` table and create a tracked `processing_jobs` entry for `review_batch`.

    WHEN NOT TO USE:
        Do not use this tool if you only want a dry-run validation check without writing to SQLite
        (use `validate_input_file` instead).

    REQUIRED INPUT:
        - file_path (str): Server-accessible path to the `.xlsx` or `.csv` file.
        - replace_existing (bool): If True, existing `call_id` records are updated; if False,
          duplicate IDs are rejected with row-level errors while remaining valid rows still load.

    OUTPUT RETURNED:
        Dictionary containing `job_id`, `source_file`, `total_rows`, `inserted_count`,
        `rejected_count`, `current_status`, and `validation_summary`.

    READ / WRITE BEHAVIOR:
        WRITES valid rows to `calls`, creates a row in `processing_jobs`, and logs `mcp_activity`.

    POSSIBLE ERRORS & BOUNDARIES:
        Returns `AURA_ERR_MISSING_EXCEL_COLUMNS` if `call_id` or `transcript` columns are absent,
        or `AURA_ERR_INVALID_FILE_TYPE` for unsupported file types.
    """
    payload = {"file_path": file_path, "replace_existing": replace_existing}

    def _run(repo: AuraRepository, _corr_id: str) -> dict[str, Any]:
        return IngestionService(repo).ingest_validated_calls(
            file_path=file_path,
            replace_existing=replace_existing,
        )

    return _execute_governed_tool("ingest_validated_calls", None, payload, _run, db_path=db_path)


ALL_TOOL_FUNCTIONS = [
    review_call,
    review_batch,
    find_similar_calls,
    explain_decision,
    compare_decisions,
    get_audit_record,
    portfolio_summary,
    simulate_model_upgrade,
    validate_input_file,
    ingest_validated_calls,
]
