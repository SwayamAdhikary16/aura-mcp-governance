"""Core governed orchestration workflow for AURA call review (`review_call` and `review_batch`).

Executes the 17-step governed AURA pipeline while persisting every stage,
MCP activity event, and audit record in SQLite.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from aura.config import get_config
from aura.consolidator import consolidate_decision
from aura.errors import AuraError, ErrorCode
from aura.ingestion_service import sanitize_transcript
from aura.llm_provider import get_llm_provider
from aura.logging_config import get_logger
from aura.repositories import AuraRepository
from aura.routing_engine import RoutingEngine
from aura.schemas import (
    ChallengerAnalysisResult,
    ReviewCallResponse,
    RoutineAnalysisResult,
    SpecialistAnalysisResult,
)

logger = get_logger("processing_service")

PIPELINE_STAGES = [
    "Transcript Loaded",
    "Model Catalog Read",
    "First Pass",
    "Routing Policy Read",
    "Routine or Specialist Analysis",
    "Similar Calls Retrieved",
    "Challenger Policy Read",
    "Challenger Review",
    "Final Decision",
    "Audit Stored",
]


class ProcessingService:
    """Stateless orchestrator for single-call and batch governed call analysis."""

    def __init__(self, repo: AuraRepository) -> None:
        self.repo = repo
        self.routing_engine = RoutingEngine(repo)
        self.cfg = get_config()

    def _find_similar_context(
        self,
        call_id: str,
        issue_category: str,
        issue_subcategory: str | None = None,
        maximum_results: int = 5,
        minimum_confidence: float = 0.65,
    ) -> dict[str, Any]:
        """Retrieve anonymized historical context from SQLite excluding the current call."""
        matches = self.repo.find_similar_calls(
            call_id=call_id,
            issue_category=issue_category,
            issue_subcategory=issue_subcategory,
            maximum_results=maximum_results,
            minimum_confidence=minimum_confidence,
        )
        res_counts: dict[str, int] = {}
        deflect_counts: dict[str, int] = {}
        route_counts: dict[str, int] = {}
        anonymized_ids: list[str] = []

        for m in matches:
            anonymized_ids.append(f"HIST-{m['call_id'][-4:]}")
            r_stat = m.get("final_resolution_status") or "Resolved"
            res_counts[r_stat] = res_counts.get(r_stat, 0) + 1
            d_chan = m.get("deflection_channel") or "None"
            deflect_counts[d_chan] = deflect_counts.get(d_chan, 0) + 1
            f_rt = m.get("final_route") or "routine_analysis"
            route_counts[f_rt] = route_counts.get(f_rt, 0) + 1

        return {
            "call_id": call_id,
            "similar_call_count": len(matches),
            "selected_anonymized_call_ids": anonymized_ids,
            "common_resolution_statuses": res_counts,
            "common_deflection_channels": deflect_counts,
            "common_route_outcomes": route_counts,
            "governance_warning": (
                "IMPORTANT: Historical call patterns provide operational context only and "
                "do NOT determine individual call outcomes."
            ),
        }

    def review_call(
        self,
        call_id: str,
        transcript: str,
        review_goal: str | None = None,
        force_challenger: bool = False,
        correlation_id: str | None = None,
        stage_callback: Callable[[str, str, dict[str, Any]], None] | None = None,
    ) -> ReviewCallResponse:
        """Process one transcript through the complete 17-step governed AURA workflow."""
        corr_id = correlation_id or f"corr-{uuid.uuid4().hex[:12]}"
        clean_call_id = (call_id or "").strip()
        raw_transcript = (transcript or "").strip()

        def notify_stage(stage: str, status: str, meta: dict[str, Any] | None = None) -> None:
            if stage_callback:
                stage_callback(stage, status, meta or {})

        # Step 1: Validate the request
        if not clean_call_id:
            raise AuraError(
                error_code=ErrorCode.VALIDATION_ERROR,
                user_message="A valid non-empty 'call_id' is required to review a call.",
                technical_message="review_call invoked with empty call_id.",
                correlation_id=corr_id,
            )
        if not raw_transcript:
            raise AuraError(
                error_code=ErrorCode.EMPTY_TRANSCRIPT,
                user_message=f"Transcript for call '{clean_call_id}' cannot be empty.",
                technical_message=f"Empty transcript submitted for call_id={clean_call_id}.",
                correlation_id=corr_id,
            )
        if len(raw_transcript) > self.cfg.max_transcript_length:
            raise AuraError(
                error_code=ErrorCode.TRANSCRIPT_TOO_LONG,
                user_message=(
                    f"Transcript length ({len(raw_transcript)} chars) exceeds maximum allowed "
                    f"limit ({self.cfg.max_transcript_length} chars)."
                ),
                technical_message=f"Transcript length={len(raw_transcript)} > {self.cfg.max_transcript_length}",
                correlation_id=corr_id,
            )

        # Check for absurd / non-call / out-of-domain transcript content
        lower_t = raw_transcript.lower()
        absurd_markers = [
            "pepperoni pizza",
            "bake a cake",
            "weather forecast",
            "weather in ",
            "dogecoin",
            "bitcoin price",
            "asdfghjkl",
            "[absurd_input]",
        ]
        if any(m in lower_t for m in absurd_markers) or len(raw_transcript.strip()) < 12:
            raise AuraError(
                error_code=ErrorCode.VALIDATION_ERROR,
                user_message=(
                    f"Transcript for '{clean_call_id}' was rejected by AURA Domain Guardrail: "
                    "Input appears to be an absurd, corrupted, or out-of-domain text rather than a customer-service call transcript."
                ),
                technical_message=(
                    f"Domain guardrail blocked review_call for call_id={clean_call_id}: "
                    "non-call or absurd transcript content detected before LLM invocation."
                ),
                retryable=True,
                human_review_required=False,
                correlation_id=corr_id,
            )

        sanitized_transcript = sanitize_transcript(raw_transcript)
        t0 = time.perf_counter()

        # Ensure call exists in SQLite
        if not self.repo.call_exists(clean_call_id):
            self.repo.upsert_call(
                call_id=clean_call_id,
                transcript=sanitized_transcript,
                source_file="mcp_review_call",
                source_system="AURA_MCP_CLIENT",
            )
        self.repo.update_call_stage(clean_call_id, "Running", "Transcript Loaded")
        self.repo.record_audit_event(
            correlation_id=corr_id,
            call_id=clean_call_id,
            event_type="STAGE_COMPLETE",
            stage_name="Transcript Loaded",
            actor_type="AURA_ORCHESTRATOR",
            tool_name="review_call",
            status="Completed",
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            input_summary={"call_id": clean_call_id, "transcript_chars": len(sanitized_transcript)},
            output_summary={"sanitized": True},
        )
        notify_stage("Transcript Loaded", "Completed", {"call_id": clean_call_id})

        # Step 2 & 3: Read active model catalog and record MCP activity
        t_cat = time.perf_counter()
        self.repo.update_call_stage(clean_call_id, "Running", "Model Catalog Read")
        fast_model = self.repo.get_validated_model("AURA_FAST")
        deep_model = self.repo.get_validated_model("AURA_DEEP")
        chal_model = self.repo.get_validated_model("AURA_CHALLENGER")
        cat_ms = (time.perf_counter() - t_cat) * 1000.0

        self.repo.record_mcp_activity(
            correlation_id=corr_id,
            call_id=clean_call_id,
            activity_type="RESOURCE READ",
            operation_name="aura://model-catalog",
            status="Completed",
            duration_ms=cat_ms,
            input_payload={"resource_uri": "aura://model-catalog"},
            output_payload={
                "active_models": [fast_model["model_id"], deep_model["model_id"], chal_model["model_id"]],
                "catalog_version": fast_model["catalog_version"],
            },
        )
        self.repo.record_audit_event(
            correlation_id=corr_id,
            call_id=clean_call_id,
            event_type="RESOURCE_READ",
            stage_name="Model Catalog Read",
            actor_type="AURA_ORCHESTRATOR",
            resource_uri="aura://model-catalog",
            status="Completed",
            duration_ms=cat_ms,
            output_summary={"catalog_version": fast_model["catalog_version"]},
        )
        notify_stage("Model Catalog Read", "Completed", {"catalog_version": fast_model["catalog_version"]})

        provider = get_llm_provider()

        def on_json_retry(schema_name: str, err_msg: str) -> None:
            self.repo.record_mcp_activity(
                correlation_id=corr_id,
                call_id=clean_call_id,
                activity_type="RETRY",
                operation_name=f"repair_json_response:{schema_name}",
                status="Retried",
                duration_ms=1.5,
                input_payload={"schema": schema_name},
                output_payload={"retry_reason": err_msg[:200]},
                error_message=err_msg[:200],
            )
            self.repo.record_audit_event(
                correlation_id=corr_id,
                call_id=clean_call_id,
                event_type="JSON_REPAIR_RETRY",
                stage_name="First Pass",
                actor_type="LLM_PROVIDER",
                model_id=fast_model["model_id"],
                model_version=fast_model["model_version"],
                status="Retried",
                error_code=ErrorCode.INVALID_LLM_JSON.value,
                output_summary={"repair_attempted_for": schema_name},
            )

        # Step 4 & 5: Run First-Pass Analysis & Persist
        t_fp = time.perf_counter()
        self.repo.update_call_stage(clean_call_id, "Running", "First Pass")
        try:
            first_pass, fp_repaired = provider.run_first_pass(
                call_id=clean_call_id,
                transcript=sanitized_transcript,
                review_goal=review_goal,
                on_retry_callback=on_json_retry,
            )
        except AuraError as exc:
            fp_ms = (time.perf_counter() - t_fp) * 1000.0
            self.repo.update_call_stage(
                clean_call_id,
                "Failed",
                "First Pass",
                error_code=exc.structured.error_code,
                error_message=exc.structured.user_message,
            )
            self.repo.record_mcp_activity(
                correlation_id=corr_id,
                call_id=clean_call_id,
                activity_type="ERROR",
                operation_name="run_first_pass",
                status="Failed",
                duration_ms=fp_ms,
                error_message=exc.structured.user_message,
            )
            self.repo.record_audit_event(
                correlation_id=corr_id,
                call_id=clean_call_id,
                event_type="STAGE_ERROR",
                stage_name="First Pass",
                actor_type="LLM_PROVIDER",
                model_id=fast_model["model_id"],
                model_version=fast_model["model_version"],
                prompt_name="first_pass_prompt",
                prompt_version="2.1.0",
                status="Failed",
                duration_ms=fp_ms,
                error_code=exc.structured.error_code,
                output_summary=exc.to_dict(),
            )
            notify_stage("First Pass", "Failed", exc.to_dict())
            raise

        self.repo.save_first_pass_result(first_pass)
        fp_ms = (time.perf_counter() - t_fp) * 1000.0
        self.repo.record_mcp_activity(
            correlation_id=corr_id,
            call_id=clean_call_id,
            activity_type="DATABASE WRITE",
            operation_name="save_first_pass_result",
            status="Completed",
            duration_ms=fp_ms,
            input_payload={"call_id": clean_call_id, "complexity": first_pass.complexity},
            output_payload={
                "primary_issue": first_pass.primary_issue,
                "active_flags": first_pass.active_flags(),
                "json_repaired": fp_repaired,
            },
        )
        self.repo.record_audit_event(
            correlation_id=corr_id,
            call_id=clean_call_id,
            event_type="STAGE_COMPLETE",
            stage_name="First Pass",
            actor_type="LLM_PROVIDER",
            model_id=fast_model["model_id"],
            model_version=fast_model["model_version"],
            prompt_name="first_pass_prompt",
            prompt_version="2.1.0",
            status="Completed",
            duration_ms=fp_ms,
            output_summary={
                "complexity": first_pass.complexity,
                "confidence": first_pass.analysis_confidence,
                "flags": first_pass.active_flags(),
                "json_repaired": fp_repaired,
            },
        )
        notify_stage("First Pass", "Completed", {"complexity": first_pass.complexity})

        # Step 6 & 7: Read Active Routing Policy & Determine Route
        t_rp = time.perf_counter()
        self.repo.update_call_stage(clean_call_id, "Running", "Routing Policy Read")
        routing_decision = self.routing_engine.evaluate_routing(
            first_pass=first_pass,
            force_challenger=force_challenger,
        )
        rp_ms = (time.perf_counter() - t_rp) * 1000.0
        self.repo.record_mcp_activity(
            correlation_id=corr_id,
            call_id=clean_call_id,
            activity_type="RESOURCE READ",
            operation_name="aura://routing-policy",
            status="Completed",
            duration_ms=rp_ms,
            input_payload={"resource_uri": "aura://routing-policy"},
            output_payload=routing_decision.model_dump(),
        )
        self.repo.record_audit_event(
            correlation_id=corr_id,
            call_id=clean_call_id,
            event_type="POLICY_EVALUATION",
            stage_name="Routing Policy Read",
            actor_type="ROUTING_ENGINE",
            resource_uri="aura://routing-policy",
            status="Completed",
            duration_ms=rp_ms,
            route_reason="; ".join(routing_decision.routing_reasons),
            output_summary=routing_decision.model_dump(),
        )
        notify_stage("Routing Policy Read", "Completed", {"route": routing_decision.selected_route})

        # Step 10 (Contextual pre-fetch before Specialist or recorded after Routine): Retrieve Similar Calls
        t_sim = time.perf_counter()
        self.repo.update_call_stage(clean_call_id, "Running", "Similar Calls Retrieved")
        historical_context: dict[str, Any] = {}
        if routing_decision.specialist_required or first_pass.complexity >= 3:
            historical_context = self._find_similar_context(
                call_id=clean_call_id,
                issue_category=first_pass.issue_category,
                issue_subcategory=first_pass.issue_subcategory,
            )
            sim_ms = (time.perf_counter() - t_sim) * 1000.0
            self.repo.record_mcp_activity(
                correlation_id=corr_id,
                call_id=clean_call_id,
                activity_type="TOOL CALL",
                operation_name="find_similar_calls",
                status="Completed",
                duration_ms=sim_ms,
                input_payload={
                    "call_id": clean_call_id,
                    "issue_category": first_pass.issue_category,
                },
                output_payload={
                    "similar_call_count": historical_context.get("similar_call_count", 0),
                    "selected_anonymized_call_ids": historical_context.get("selected_anonymized_call_ids", []),
                },
            )
            self.repo.record_audit_event(
                correlation_id=corr_id,
                call_id=clean_call_id,
                event_type="HISTORICAL_CONTEXT",
                stage_name="Similar Calls Retrieved",
                actor_type="AURA_ORCHESTRATOR",
                tool_name="find_similar_calls",
                status="Completed",
                duration_ms=sim_ms,
                output_summary={"similar_call_count": historical_context.get("similar_call_count", 0)},
            )
            notify_stage("Similar Calls Retrieved", "Completed", historical_context)
        else:
            sim_ms = (time.perf_counter() - t_sim) * 1000.0
            self.repo.record_audit_event(
                correlation_id=corr_id,
                call_id=clean_call_id,
                event_type="STAGE_SKIPPED",
                stage_name="Similar Calls Retrieved",
                actor_type="AURA_ORCHESTRATOR",
                status="Skipped",
                duration_ms=sim_ms,
                route_reason="Routine low-complexity call did not require historical comparator retrieval.",
            )
            notify_stage("Similar Calls Retrieved", "Skipped", {})

        # Step 8 & 9: Routine or Specialist Analysis
        t_spec = time.perf_counter()
        self.repo.update_call_stage(clean_call_id, "Running", "Routine or Specialist Analysis")
        primary_result: SpecialistAnalysisResult | RoutineAnalysisResult | None = None
        provisional_fallback_reason: str | None = None

        if routing_decision.specialist_required:
            try:
                primary_result, _ = provider.run_specialist_analysis(
                    call_id=clean_call_id,
                    transcript=sanitized_transcript,
                    first_pass=first_pass,
                    historical_context=historical_context,
                    on_retry_callback=on_json_retry,
                )
                self.repo.save_specialist_or_routine_result(primary_result)
                spec_ms = (time.perf_counter() - t_spec) * 1000.0
                self.repo.record_mcp_activity(
                    correlation_id=corr_id,
                    call_id=clean_call_id,
                    activity_type="DATABASE WRITE",
                    operation_name="save_specialist_result",
                    status="Completed",
                    duration_ms=spec_ms,
                    input_payload={"call_id": clean_call_id, "analysis_type": "specialist_analysis"},
                    output_payload={
                        "resolution_status": primary_result.resolution_status,
                        "risk_level": primary_result.risk_level,
                    },
                )
                self.repo.record_audit_event(
                    correlation_id=corr_id,
                    call_id=clean_call_id,
                    event_type="STAGE_COMPLETE",
                    stage_name="Routine or Specialist Analysis",
                    actor_type="LLM_PROVIDER",
                    model_id=deep_model["model_id"],
                    model_version=deep_model["model_version"],
                    prompt_name="split_analysis_prompt",
                    prompt_version="2.1.0",
                    status="Completed",
                    duration_ms=spec_ms,
                    output_summary={
                        "analysis_type": "specialist_analysis",
                        "risk_level": primary_result.risk_level,
                        "resolution_status": primary_result.resolution_status,
                    },
                )
                notify_stage("Routine or Specialist Analysis", "Completed", {"type": "specialist_analysis"})
            except AuraError as spec_err:
                spec_ms = (time.perf_counter() - t_spec) * 1000.0
                provisional_fallback_reason = spec_err.structured.user_message
                self.repo.record_mcp_activity(
                    correlation_id=corr_id,
                    call_id=clean_call_id,
                    activity_type="ERROR",
                    operation_name="run_specialist_analysis",
                    status="Failed",
                    duration_ms=spec_ms,
                    error_message=spec_err.structured.user_message,
                )
                self.repo.record_audit_event(
                    correlation_id=corr_id,
                    call_id=clean_call_id,
                    event_type="STAGE_ERROR_FALLBACK",
                    stage_name="Routine or Specialist Analysis",
                    actor_type="LLM_PROVIDER",
                    model_id=deep_model["model_id"],
                    model_version=deep_model["model_version"],
                    prompt_name="split_analysis_prompt",
                    prompt_version="2.1.0",
                    status="Failed",
                    duration_ms=spec_ms,
                    error_code=spec_err.structured.error_code,
                    output_summary={"provisional_fallback": provisional_fallback_reason},
                )
                notify_stage("Routine or Specialist Analysis", "Failed", spec_err.to_dict())
        else:
            primary_result, _ = provider.run_routine_analysis(
                call_id=clean_call_id,
                transcript=sanitized_transcript,
                first_pass=first_pass,
                on_retry_callback=on_json_retry,
            )
            self.repo.save_specialist_or_routine_result(primary_result)
            spec_ms = (time.perf_counter() - t_spec) * 1000.0
            self.repo.record_mcp_activity(
                correlation_id=corr_id,
                call_id=clean_call_id,
                activity_type="DATABASE WRITE",
                operation_name="save_routine_result",
                status="Completed",
                duration_ms=spec_ms,
                input_payload={"call_id": clean_call_id, "analysis_type": "routine_analysis"},
                output_payload={"resolution_status": primary_result.resolution_status},
            )
            self.repo.record_audit_event(
                correlation_id=corr_id,
                call_id=clean_call_id,
                event_type="STAGE_COMPLETE",
                stage_name="Routine or Specialist Analysis",
                actor_type="LLM_PROVIDER",
                model_id=fast_model["model_id"],
                model_version=fast_model["model_version"],
                prompt_name="single_analysis_prompt",
                prompt_version="2.1.0",
                status="Completed",
                duration_ms=spec_ms,
                output_summary={
                    "analysis_type": "routine_analysis",
                    "resolution_status": primary_result.resolution_status,
                },
            )
            notify_stage("Routine or Specialist Analysis", "Completed", {"type": "routine_analysis"})

        # Step 11 & 12: Read Challenger Policy & Evaluate Challenger Need
        t_cp = time.perf_counter()
        self.repo.update_call_stage(clean_call_id, "Running", "Challenger Policy Read")
        if primary_result is not None:
            chal_needed, chal_reasons = self.routing_engine.evaluate_challenger_after_primary(
                first_pass=first_pass,
                primary_result=primary_result,
                initial_decision=routing_decision,
                force_challenger=force_challenger,
            )
        else:
            chal_needed = False
            chal_reasons = ["Skipped Challenger because primary specialist failed (already provisional human review)"]

        cp_ms = (time.perf_counter() - t_cp) * 1000.0
        self.repo.record_mcp_activity(
            correlation_id=corr_id,
            call_id=clean_call_id,
            activity_type="RESOURCE READ",
            operation_name="aura://challenger-policy",
            status="Completed",
            duration_ms=cp_ms,
            input_payload={"resource_uri": "aura://challenger-policy"},
            output_payload={"challenger_needed": chal_needed, "reasons": chal_reasons},
        )
        self.repo.record_audit_event(
            correlation_id=corr_id,
            call_id=clean_call_id,
            event_type="POLICY_EVALUATION",
            stage_name="Challenger Policy Read",
            actor_type="ROUTING_ENGINE",
            resource_uri="aura://challenger-policy",
            status="Completed",
            duration_ms=cp_ms,
            route_reason="; ".join(chal_reasons) if chal_reasons else "Challenger not required by policy",
            output_summary={"challenger_needed": chal_needed, "reasons": chal_reasons},
        )
        notify_stage("Challenger Policy Read", "Completed", {"challenger_needed": chal_needed})

        # Step 13: Run Challenger Review when needed
        t_chal = time.perf_counter()
        self.repo.update_call_stage(clean_call_id, "Running", "Challenger Review")
        challenger_result: ChallengerAnalysisResult | None = None
        challenger_used = False
        challenger_reason_str = "; ".join(chal_reasons) if chal_reasons else "Not required by challenger policy"

        if chal_needed and primary_result is not None:
            challenger_used = True
            try:
                challenger_result, _ = provider.run_challenger_analysis(
                    call_id=clean_call_id,
                    transcript=sanitized_transcript,
                    first_pass=first_pass,
                    primary_result=primary_result,
                    on_retry_callback=on_json_retry,
                )
                self.repo.save_challenger_result(challenger_result)
                chal_ms = (time.perf_counter() - t_chal) * 1000.0
                self.repo.record_mcp_activity(
                    correlation_id=corr_id,
                    call_id=clean_call_id,
                    activity_type="DATABASE WRITE",
                    operation_name="save_challenger_result",
                    status="Completed",
                    duration_ms=chal_ms,
                    input_payload={"call_id": clean_call_id},
                    output_payload={
                        "challenger_agreement": challenger_result.challenger_agreement,
                        "final_disposition": challenger_result.final_disposition,
                    },
                )
                self.repo.record_audit_event(
                    correlation_id=corr_id,
                    call_id=clean_call_id,
                    event_type="STAGE_COMPLETE",
                    stage_name="Challenger Review",
                    actor_type="LLM_PROVIDER",
                    model_id=chal_model["model_id"],
                    model_version=chal_model["model_version"],
                    prompt_name="challenger_prompt",
                    prompt_version="2.1.0",
                    status="Completed",
                    duration_ms=chal_ms,
                    route_reason=challenger_reason_str,
                    output_summary={
                        "challenger_agreement": challenger_result.challenger_agreement,
                        "final_disposition": challenger_result.final_disposition,
                    },
                )
                notify_stage("Challenger Review", "Completed", challenger_result.model_dump())
            except AuraError as chal_err:
                # Section 22.H: Retain the primary result as provisional and require human review
                chal_ms = (time.perf_counter() - t_chal) * 1000.0
                provisional_fallback_reason = chal_err.structured.user_message
                self.repo.record_mcp_activity(
                    correlation_id=corr_id,
                    call_id=clean_call_id,
                    activity_type="ERROR",
                    operation_name="run_challenger_analysis",
                    status="Failed",
                    duration_ms=chal_ms,
                    error_message=chal_err.structured.user_message,
                )
                self.repo.record_audit_event(
                    correlation_id=corr_id,
                    call_id=clean_call_id,
                    event_type="STAGE_ERROR_FALLBACK",
                    stage_name="Challenger Review",
                    actor_type="LLM_PROVIDER",
                    model_id=chal_model["model_id"],
                    model_version=chal_model["model_version"],
                    prompt_name="challenger_prompt",
                    prompt_version="2.1.0",
                    status="Failed",
                    duration_ms=chal_ms,
                    error_code=chal_err.structured.error_code,
                    output_summary={
                        "provisional_fallback": "Retained primary result as provisional; human review required.",
                    },
                )
                notify_stage("Challenger Review", "Failed", chal_err.to_dict())
        else:
            chal_ms = (time.perf_counter() - t_chal) * 1000.0
            self.repo.record_audit_event(
                correlation_id=corr_id,
                call_id=clean_call_id,
                event_type="STAGE_SKIPPED",
                stage_name="Challenger Review",
                actor_type="AURA_ORCHESTRATOR",
                status="Skipped",
                duration_ms=chal_ms,
                route_reason=challenger_reason_str,
            )
            notify_stage("Challenger Review", "Skipped", {})

        # Step 14 & 15: Consolidate Final Decision & Persist
        t_fin = time.perf_counter()
        self.repo.update_call_stage(clean_call_id, "Running", "Final Decision")
        final_result = consolidate_decision(
            call_id=clean_call_id,
            correlation_id=corr_id,
            first_pass=first_pass,
            routing_decision=routing_decision,
            primary_result=primary_result,
            challenger_result=challenger_result,
            challenger_used=challenger_used,
            challenger_reason=challenger_reason_str,
            historical_context=historical_context,
            provisional_fallback_reason=provisional_fallback_reason,
        )
        self.repo.save_final_result(final_result)
        fin_ms = (time.perf_counter() - t_fin) * 1000.0
        self.repo.record_mcp_activity(
            correlation_id=corr_id,
            call_id=clean_call_id,
            activity_type="DATABASE WRITE",
            operation_name="save_final_result",
            status="Completed",
            duration_ms=fin_ms,
            input_payload={"call_id": clean_call_id},
            output_payload={
                "final_route": final_result.final_route,
                "final_risk_level": final_result.final_risk_level,
                "human_review_required": final_result.human_review_required,
            },
        )
        self.repo.record_audit_event(
            correlation_id=corr_id,
            call_id=clean_call_id,
            event_type="STAGE_COMPLETE",
            stage_name="Final Decision",
            actor_type="CONSOLIDATOR",
            status="Completed",
            duration_ms=fin_ms,
            output_summary={
                "final_route": final_result.final_route,
                "final_risk_level": final_result.final_risk_level,
                "human_review_required": final_result.human_review_required,
                "final_confidence": final_result.final_confidence,
            },
        )
        notify_stage("Final Decision", "Completed", final_result.model_dump())

        # Step 16: Write Final Audit Trail Marker
        t_aud = time.perf_counter()
        final_status_label = (
            "Human Review Required" if final_result.human_review_required else "Completed"
        )
        self.repo.update_call_stage(clean_call_id, final_status_label, "Audit Stored")
        aud_ms = (time.perf_counter() - t_aud) * 1000.0
        self.repo.record_audit_event(
            correlation_id=corr_id,
            call_id=clean_call_id,
            event_type="WORKFLOW_COMPLETED",
            stage_name="Audit Stored",
            actor_type="AURA_ORCHESTRATOR",
            tool_name="review_call",
            status="Completed",
            duration_ms=aud_ms,
            output_summary={"final_status": final_status_label},
        )
        notify_stage("Audit Stored", final_status_label, {"status": final_status_label})

        # Step 17: Return structured ReviewCallResponse
        return ReviewCallResponse(
            correlation_id=corr_id,
            call_id=clean_call_id,
            processing_status=final_status_label,
            first_pass_summary=first_pass.summary,
            detected_flags=first_pass.active_flags(),
            complexity=first_pass.complexity,
            route_selected=final_result.final_route,
            routing_reasons=routing_decision.routing_reasons,
            specialist_used=final_result.specialist_used,
            historical_context_used=final_result.historical_context_used,
            challenger_used=final_result.challenger_used,
            challenger_reason=final_result.challenger_reason,
            final_decision=final_result.model_dump(),
            human_review_required=final_result.human_review_required,
            final_confidence=final_result.final_confidence,
            audit_record_available=True,
        )

    def review_batch(
        self,
        job_id: str | None = None,
        maximum_calls: int = 25,
        stop_on_error: bool = False,
        use_cached_results: bool = False,
    ) -> dict[str, Any]:
        """Execute stateless batch processing for valid calls stored in SQLite."""
        calls = self.repo.list_calls(job_id=job_id, limit=max(1, min(maximum_calls, 500)))
        if not calls:
            return {
                "job_id": job_id or "DEFAULT",
                "processed_count": 0,
                "successful_count": 0,
                "failed_count": 0,
                "skipped_cached_count": 0,
                "processing_status": "No Calls Found",
                "results": [],
            }

        processed = 0
        successful = 0
        failed = 0
        skipped_cached = 0
        summaries: list[dict[str, Any]] = []

        if job_id:
            self.repo.update_processing_job(
                job_id=job_id,
                processed_calls=0,
                successful_calls=0,
                failed_calls=0,
                processing_status="Running",
            )

        for call_row in calls[:maximum_calls]:
            cid = call_row["call_id"]
            if use_cached_results:
                existing_final = self.repo.get_final_result(cid)
                if existing_final:
                    skipped_cached += 1
                    successful += 1
                    processed += 1
                    summaries.append(
                        {
                            "call_id": cid,
                            "status": call_row.get("processing_status", "Completed"),
                            "cached": True,
                            "route": existing_final["final_route"],
                        }
                    )
                    continue

            try:
                res = self.review_call(
                    call_id=cid,
                    transcript=call_row["transcript"],
                )
                processed += 1
                successful += 1
                summaries.append(
                    {
                        "call_id": cid,
                        "status": res.processing_status,
                        "cached": False,
                        "route": res.route_selected,
                        "human_review_required": res.human_review_required,
                    }
                )
            except AuraError as exc:
                processed += 1
                failed += 1
                summaries.append(
                    {
                        "call_id": cid,
                        "status": "Failed",
                        "error_code": exc.structured.error_code,
                        "error_message": exc.structured.user_message,
                    }
                )
                if stop_on_error:
                    break

            if job_id:
                self.repo.update_processing_job(
                    job_id=job_id,
                    processed_calls=processed,
                    successful_calls=successful,
                    failed_calls=failed,
                    processing_status="Running",
                )

        final_job_status = "Completed" if failed == 0 else ("Completed with Errors" if successful > 0 else "Failed")
        if job_id:
            self.repo.update_processing_job(
                job_id=job_id,
                processed_calls=processed,
                successful_calls=successful,
                failed_calls=failed,
                processing_status=final_job_status,
                completed=True,
            )

        return {
            "job_id": job_id or "AD_HOC_BATCH",
            "processed_count": processed,
            "successful_count": successful,
            "failed_count": failed,
            "skipped_cached_count": skipped_cached,
            "processing_status": final_job_status,
            "results": summaries,
        }
