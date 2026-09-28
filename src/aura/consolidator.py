"""Decision consolidation engine for AURA.

Consolidates First-Pass, Routing, Routine/Specialist, Historical Context,
and Challenger outputs into a governed FinalConsolidatedResult.
Handles provisional fallbacks safely when downstream specialist or challenger stages fail.
"""

from __future__ import annotations

from typing import Any

from aura.schemas import (
    ChallengerAnalysisResult,
    FinalConsolidatedResult,
    FirstPassResult,
    RoutineAnalysisResult,
    RoutingDecision,
    SpecialistAnalysisResult,
)


RISK_ORDER = {"Low": 1, "Moderate": 2, "High": 3, "Critical": 4}


def consolidate_decision(
    call_id: str,
    correlation_id: str,
    first_pass: FirstPassResult,
    routing_decision: RoutingDecision,
    primary_result: SpecialistAnalysisResult | RoutineAnalysisResult | None,
    challenger_result: ChallengerAnalysisResult | None,
    challenger_used: bool,
    challenger_reason: str,
    historical_context: dict[str, Any] | None = None,
    provisional_fallback_reason: str | None = None,
) -> FinalConsolidatedResult:
    """Consolidate all stage outputs and governance rules into FinalConsolidatedResult."""
    human_review_reasons: list[str] = []

    if first_pass.threat_flag:
        human_review_reasons.append("HIGHEST PRIORITY SAFETY FLAG: Verbal threat indicator detected.")
    if first_pass.self_harm_flag:
        human_review_reasons.append(
            "HIGHEST PRIORITY SAFETY FLAG: Self-harm indicator detected (AI is not an emergency-response authority)."
        )
    if routing_decision.human_review_precondition and not human_review_reasons:
        human_review_reasons.append("Mandatory human-review precondition triggered by routing policy.")

    # Determine primary resolution, risk, confidence, and deflection
    if isinstance(primary_result, SpecialistAnalysisResult):
        final_resolution = primary_result.resolution_status
        final_risk = primary_result.risk_level
        final_conf = primary_result.analysis_confidence
        deflection_eligible = primary_result.deflection_eligible
        deflection_channel = primary_result.deflection_channel
        if primary_result.review_required:
            human_review_reasons.append("Specialist analysis recommended human governance review.")
    elif isinstance(primary_result, RoutineAnalysisResult):
        final_resolution = primary_result.resolution_status
        final_risk = "Low"
        final_conf = primary_result.analysis_confidence
        deflection_eligible = primary_result.deflection_eligible
        deflection_channel = primary_result.deflection_channel
        if primary_result.review_required:
            human_review_reasons.append("Routine analysis flagged call for human review.")
    else:
        # Specialist failed — retain first-pass as provisional
        final_resolution = "Resolved" if first_pass.resolved_in_call_flag else "Unresolved"
        final_risk = "Critical" if (first_pass.threat_flag or first_pass.self_harm_flag) else (
            "High" if (first_pass.fraud_flag or first_pass.compliance_flag) else "Moderate"
        )
        final_conf = round(first_pass.analysis_confidence * 0.85, 2)
        deflection_eligible = False
        deflection_channel = "None - Provisional Human Review"
        human_review_reasons.append(
            provisional_fallback_reason
            or "Primary specialist analysis unavailable; retained first-pass triage as provisional."
        )

    # Apply Challenger override / disagreement rules if Challenger ran
    challenger_agreement: bool | None = None
    disagreement_fields: list[str] = []

    if challenger_result is not None:
        challenger_agreement = challenger_result.challenger_agreement
        disagreement_fields = list(challenger_result.disagreement_fields)

        # Conservative risk elevation: take the higher risk level between Primary and Challenger
        if RISK_ORDER.get(challenger_result.challenged_risk_level, 1) > RISK_ORDER.get(final_risk, 1):
            final_risk = challenger_result.challenged_risk_level

        if not challenger_result.challenger_agreement:
            final_resolution = challenger_result.challenged_resolution_status
            deflection_eligible = False
            deflection_channel = "None - Disagreement Hold"
            human_review_reasons.append(
                f"Challenger disagreed with primary decision on fields: {', '.join(disagreement_fields)}. "
                f"{challenger_result.disagreement_rationale}"
            )
        if challenger_result.review_required:
            msg = f"Challenger disposition '{challenger_result.final_disposition}' requires human review."
            if msg not in human_review_reasons:
                human_review_reasons.append(msg)

        final_conf = round((final_conf + challenger_result.analysis_confidence) / 2.0, 2)
    elif provisional_fallback_reason:
        if provisional_fallback_reason not in human_review_reasons:
            human_review_reasons.append(provisional_fallback_reason)

    if final_conf < 0.70:
        human_review_reasons.append(f"Consolidated confidence ({final_conf:.2f}) is below governance threshold (0.70).")

    if (first_pass.fraud_flag or first_pass.compliance_flag) and final_resolution != "Resolved":
        msg = "High-risk fraud or compliance indicator combined with non-resolved status requires human review."
        if msg not in human_review_reasons:
            human_review_reasons.append(msg)

    human_review_required = bool(human_review_reasons)
    hist_count = int((historical_context or {}).get("similar_call_count", 0))
    hist_used = hist_count > 0

    summary_parts = [
        f"Call {call_id} ({first_pass.primary_issue}) completed via '{routing_decision.selected_route}'.",
        f"Risk: {final_risk} | Resolution: {final_resolution} | Confidence: {final_conf:.2f}.",
    ]
    if routing_decision.specialist_required:
        summary_parts.append(f"Specialist invoked (historical comparators: {hist_count}).")
    if challenger_used:
        summary_parts.append(
            f"Challenger invoked ({'Agreed' if challenger_agreement else 'Disagreed/Provisional'})."
        )
    if provisional_fallback_reason:
        summary_parts.append(f"PROVISIONAL FALLBACK: {provisional_fallback_reason}")
    if human_review_required:
        summary_parts.append("Routed to Human Governance Review.")

    return FinalConsolidatedResult(
        call_id=call_id,
        correlation_id=correlation_id,
        final_summary=" ".join(summary_parts),
        final_route=routing_decision.selected_route,
        final_risk_level=final_risk,  # type: ignore[arg-type]
        final_resolution_status=final_resolution,  # type: ignore[arg-type]
        primary_issue=first_pass.primary_issue,
        issue_category=first_pass.issue_category,
        issue_subcategory=first_pass.issue_subcategory,
        interaction_origin=first_pass.interaction_origin,
        complexity=first_pass.complexity,
        detected_flags=first_pass.active_flags(),
        routing_reasons=routing_decision.routing_reasons,
        specialist_used=routing_decision.specialist_required and primary_result is not None,
        historical_context_used=hist_used,
        similar_calls_count=hist_count,
        challenger_used=challenger_used,
        challenger_reason=challenger_reason,
        challenger_agreement=challenger_agreement,
        disagreement_fields=disagreement_fields,
        human_review_required=human_review_required,
        human_review_reasons=human_review_reasons,
        final_confidence=final_conf,
        deflection_eligible=deflection_eligible,
        deflection_channel=deflection_channel,
        provisional_status=bool(provisional_fallback_reason),
    )
