"""Pydantic v2 schemas for AURA structured AI outputs, routing, and MCP contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class EvidenceSnippet(BaseModel):
    """Timestamped or speaker-attributed quote from the transcript."""

    timestamp: str = Field(default="00:00", description="Timestamp marker if present in transcript.")
    speaker: str = Field(default="Customer", description="Speaker identifier (Customer or Agent).")
    quote: str = Field(..., description="Direct excerpt from transcript supporting the finding.")
    fact_vs_allegation: Literal["Confirmed Fact", "Customer Allegation", "Agent Statement"] = Field(
        default="Confirmed Fact",
        description="Distinguishes confirmed facts from allegations.",
    )


class QualityDimensionAssessment(BaseModel):
    """Assessment of a single AURA quality framework dimension."""

    dimension_name: str = Field(..., description="Quality dimension name from aura://quality-framework.")
    rating: Literal["Strong", "Adequate", "Needs Improvement"] = Field(..., description="Normalized quality rating.")
    rationale: str = Field(..., description="Concise evidence-backed rationale.")


class FirstPassResult(BaseModel):
    """Schema for AURA_FAST first-pass call triage output."""

    call_id: str = Field(..., description="Unique call identifier.")
    summary: str = Field(..., description="Concise factual summary of the call.")
    complexity: int = Field(..., ge=1, le=5, description="Call complexity score from 1 (simple) to 5 (highly complex).")
    analysis_confidence: float = Field(..., ge=0.0, le=1.0, description="Model confidence score between 0.0 and 1.0.")
    primary_issue: str = Field(..., description="Normalized primary customer issue label.")
    issue_category: str = Field(..., description="Normalized business category (e.g., Billing, Fraud, Dispute, Payment).")
    issue_subcategory: str = Field(..., description="Normalized subcategory.")
    interaction_origin: str = Field(
        ...,
        description="Origin of the contact (e.g., First-Time Inquiry, Repeat Follow-Up, Self-Service Failure, Billing Statement Trigger, Post-Transaction Alert).",
    )
    sentiment_progression: str = Field(
        default="Neutral -> Neutral",
        description="Customer sentiment trajectory across start, middle, and end of call.",
    )
    dispute_flag: bool = Field(default=False, description="True if merchant or billing dispute is raised.")
    fraud_flag: bool = Field(default=False, description="True if unauthorized activity or fraud is suspected/alleged.")
    threat_flag: bool = Field(default=False, description="HIGHEST PRIORITY: True if verbal threat of harm is present.")
    self_harm_flag: bool = Field(default=False, description="HIGHEST PRIORITY: True if self-harm language is present.")
    customer_distress_flag: bool = Field(default=False, description="True if severe emotional distress is observed.")
    compliance_flag: bool = Field(
        default=False,
        description="Analytical indicator of potential compliance concern (not a legal determination).",
    )
    escalation_flag: bool = Field(default=False, description="True if supervisor or formal escalation is requested.")
    repeat_contact_risk_flag: bool = Field(default=False, description="True if likely to cause repeat contact.")
    deflection_candidate: bool = Field(default=False, description="True if call could have been handled via self-service.")
    needs_deeper_analysis: bool = Field(default=False, description="True if specialist deep analysis is recommended.")
    resolved_in_call_flag: bool = Field(default=True, description="True if the issue was resolved during the call.")
    evidence: list[EvidenceSnippet] = Field(default_factory=list, description="Supporting transcript evidence.")

    def active_flags(self) -> list[str]:
        """Return list of active boolean risk/routing flag names."""
        flag_fields = [
            "dispute_flag",
            "fraud_flag",
            "threat_flag",
            "self_harm_flag",
            "customer_distress_flag",
            "compliance_flag",
            "escalation_flag",
            "repeat_contact_risk_flag",
            "deflection_candidate",
            "needs_deeper_analysis",
        ]
        return [f for f in flag_fields if getattr(self, f, False)]


class RoutineAnalysisResult(BaseModel):
    """Schema for routine call completion analysis (Complexity 1-2 without material risk)."""

    call_id: str = Field(..., description="Unique call identifier.")
    analysis_type: Literal["routine_analysis"] = Field(default="routine_analysis")
    resolution_status: Literal["Resolved", "Partially Resolved", "Unresolved", "Escalated"] = Field(
        default="Resolved",
        description="Final resolution outcome of the call.",
    )
    first_contact_resolution: bool = Field(default=True, description="Whether resolved on first contact.")
    call_avoidable: bool = Field(default=False, description="Whether the call was avoidable.")
    deflection_eligible: bool = Field(default=False, description="Whether eligible for digital deflection.")
    deflection_channel: str = Field(
        default="None",
        description="Recommended deflection channel (e.g., Mobile App, Web Portal, IVR, Automated SMS, None).",
    )
    review_required: bool = Field(default=False, description="Whether human QA review is required.")
    analysis_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0.")
    quality_scores: list[QualityDimensionAssessment] = Field(
        default_factory=list,
        description="Quality framework ratings.",
    )
    coaching_note: str = Field(default="Standard routine handling confirmed.", description="Brief operational note.")
    compliance_disclaimer: str = Field(
        default="Analytical indicators only; not a legal determination.",
        description="Mandatory governance disclaimer.",
    )


class SpecialistAnalysisResult(BaseModel):
    """Schema for AURA_DEEP specialist analysis on complex or high-risk calls."""

    call_id: str = Field(..., description="Unique call identifier.")
    analysis_type: Literal["specialist_analysis"] = Field(default="specialist_analysis")
    resolution_status: Literal["Resolved", "Partially Resolved", "Unresolved", "Escalated"] = Field(
        ...,
        description="Specialist determination of call resolution.",
    )
    first_contact_resolution: bool = Field(..., description="True if resolved on first contact without prior attempts.")
    call_avoidable: bool = Field(..., description="True if contact was caused by process gap or avoidable friction.")
    deflection_eligible: bool = Field(..., description="True if digital self-service could safely handle this intent.")
    deflection_channel: str = Field(
        ...,
        description="Recommended channel (Mobile App, Web Portal, IVR, Secure Messaging, None - Live Agent Required).",
    )
    review_required: bool = Field(..., description="True if human review is recommended by specialist model.")
    analysis_confidence: float = Field(..., ge=0.0, le=1.0, description="Specialist confidence score.")
    risk_level: Literal["Low", "Moderate", "High", "Critical"] = Field(
        ...,
        description="Assessed risk tier based on evidence.",
    )
    root_cause: str = Field(..., description="Identified root cause (e.g., Process Gap, Knowledge Gap, Policy Dispute).")
    complaint_analysis: str = Field(..., description="Structured assessment of customer dissatisfaction or complaint.")
    dispute_analysis: str = Field(..., description="Structured assessment of merchant or billing dispute facts vs allegations.")
    fraud_analysis: str = Field(..., description="Structured assessment of unauthorized activity or identity risk signals.")
    compliance_analysis: str = Field(
        ...,
        description="Analytical compliance indicator assessment (explicitly not a legal determination).",
    )
    process_gap_identified: bool = Field(default=False, description="True if an internal process or system gap occurred.")
    knowledge_gap_identified: bool = Field(default=False, description="True if agent demonstrated a knowledge gap.")
    quality_scores: list[QualityDimensionAssessment] = Field(
        default_factory=list,
        description="Evaluations across the 5 AURA quality dimensions.",
    )
    recommended_actions: list[str] = Field(default_factory=list, description="Concrete next steps for operations/QA.")
    evidence: list[EvidenceSnippet] = Field(default_factory=list, description="Timestamped evidence snippets.")
    compliance_disclaimer: str = Field(
        default="Compliance signals are analytical indicators and not legal determinations.",
        description="Mandatory governance disclaimer.",
    )


class ChallengerAnalysisResult(BaseModel):
    """Schema for AURA_CHALLENGER independent validation of primary decisions."""

    call_id: str = Field(..., description="Unique call identifier.")
    challenger_agreement: bool = Field(
        ...,
        description="True if challenger agrees with the primary analysis on all material dimensions.",
    )
    review_required: bool = Field(
        ...,
        description="True if challenger determines human review is required.",
    )
    analysis_confidence: float = Field(..., ge=0.0, le=1.0, description="Challenger confidence score.")
    final_disposition: Literal[
        "Confirmed Primary Decision",
        "Modified Risk Elevation",
        "Escalated to Human Governance Review",
        "Flagged Safety Priority Review",
    ] = Field(..., description="Challenger disposition label.")
    challenged_resolution_status: Literal["Resolved", "Partially Resolved", "Unresolved", "Escalated"] = Field(
        ...,
        description="Challenger's independent assessment of resolution status.",
    )
    challenged_risk_level: Literal["Low", "Moderate", "High", "Critical"] = Field(
        ...,
        description="Challenger's independent assessment of risk level.",
    )
    resolution_challenge_note: str = Field(..., description="Independent evaluation of whether call was truly resolved.")
    escalation_challenge_note: str = Field(..., description="Evaluation of supervisor/escalation handling.")
    sentiment_challenge_note: str = Field(..., description="Independent check on customer emotional state at call close.")
    interaction_origin_challenge_note: str = Field(..., description="Verification of interaction origin classification.")
    agent_performance_challenge_note: str = Field(..., description="Challenge review of agent policy adherence and empathy.")
    deflection_challenge_note: str = Field(..., description="Verification that deflection recommendation is safe.")
    disagreement_fields: list[str] = Field(
        default_factory=list,
        description="List of specific fields where challenger disagrees with primary analysis.",
    )
    disagreement_rationale: str = Field(
        default="No material disagreement identified.",
        description="Explanation of any divergence between primary and challenger analyses.",
    )


class RoutingDecision(BaseModel):
    """Structured output from the AURA Routing Engine."""

    selected_route: Literal["routine_analysis", "specialist_analysis"] = Field(
        ...,
        description="Selected downstream analysis route.",
    )
    routing_reasons: list[str] = Field(..., description="Explicit policy rules that triggered this route.")
    policy_version: str = Field(..., description="Version of the routing policy used.")
    specialist_required: bool = Field(..., description="Whether AURA_DEEP specialist analysis is required.")
    challenger_required: bool = Field(..., description="Whether AURA_CHALLENGER review is required by pre-check.")
    challenger_reasons: list[str] = Field(
        default_factory=list,
        description="Reasons challenger validation was triggered.",
    )
    human_review_precondition: bool = Field(
        default=False,
        description="Whether safety/critical flags mandate human review regardless of downstream confidence.",
    )


class FinalConsolidatedResult(BaseModel):
    """Consolidated governed decision stored in final_results."""

    call_id: str = Field(..., description="Unique call identifier.")
    correlation_id: str = Field(..., description="Correlation ID for end-to-end auditability.")
    final_summary: str = Field(..., description="Executive governance summary of the call and review outcome.")
    final_route: Literal["routine_analysis", "specialist_analysis"] = Field(..., description="Executed route.")
    final_risk_level: Literal["Low", "Moderate", "High", "Critical"] = Field(..., description="Consolidated risk tier.")
    final_resolution_status: Literal["Resolved", "Partially Resolved", "Unresolved", "Escalated"] = Field(
        ...,
        description="Consolidated resolution status.",
    )
    primary_issue: str = Field(..., description="Normalized primary issue.")
    issue_category: str = Field(..., description="Normalized issue category.")
    issue_subcategory: str = Field(..., description="Normalized issue subcategory.")
    interaction_origin: str = Field(..., description="Interaction origin.")
    complexity: int = Field(..., ge=1, le=5, description="Call complexity score.")
    detected_flags: list[str] = Field(default_factory=list, description="Active risk and governance flags.")
    routing_reasons: list[str] = Field(default_factory=list, description="Policy reasons for route selection.")
    specialist_used: bool = Field(..., description="True if AURA_DEEP specialist model was invoked.")
    historical_context_used: bool = Field(default=False, description="True if similar historical calls were retrieved.")
    similar_calls_count: int = Field(default=0, description="Number of similar calls retrieved for context.")
    challenger_used: bool = Field(..., description="True if AURA_CHALLENGER model was invoked.")
    challenger_reason: str = Field(default="Not required by policy", description="Why challenger was or was not used.")
    challenger_agreement: bool | None = Field(default=None, description="Whether challenger agreed with primary.")
    disagreement_fields: list[str] = Field(default_factory=list, description="Fields with primary/challenger disagreement.")
    human_review_required: bool = Field(..., description="True if call must be routed to human reviewer.")
    human_review_reasons: list[str] = Field(default_factory=list, description="Reasons human review is required.")
    final_confidence: float = Field(..., ge=0.0, le=1.0, description="Consolidated confidence score.")
    deflection_eligible: bool = Field(default=False, description="Consolidated deflection eligibility.")
    deflection_channel: str = Field(default="None", description="Recommended deflection channel.")
    provisional_status: bool = Field(
        default=False,
        description="True if downstream failure required retaining a provisional result for human review.",
    )
    governance_notices: list[str] = Field(
        default_factory=lambda: [
            "Synthetic demonstration data only.",
            "Model outputs are analytical signals and not automated adverse actions.",
            "Compliance flags are analytical indicators and not legal determinations.",
            "Historical context patterns are informational and do not determine individual outcomes.",
        ],
        description="Mandatory responsible-AI governance notices.",
    )
    completed_at: str = Field(default_factory=utc_now_iso, description="UTC completion timestamp.")


class ReviewCallResponse(BaseModel):
    """Structured output returned by the hero MCP tool `review_call`."""

    correlation_id: str
    call_id: str
    processing_status: str
    first_pass_summary: str
    detected_flags: list[str]
    complexity: int
    route_selected: str
    routing_reasons: list[str]
    specialist_used: bool
    historical_context_used: bool
    challenger_used: bool
    challenger_reason: str
    final_decision: dict[str, Any]
    human_review_required: bool
    final_confidence: float
    audit_record_available: bool


class RowValidationError(BaseModel):
    """Row-level validation error during Excel/CSV ingestion."""

    row_index: int = Field(..., description="1-based row number in the uploaded file.")
    call_id: str | None = Field(default=None, description="Call ID if present.")
    error_code: str = Field(..., description="Canonical AURA error code.")
    message: str = Field(..., description="Human-readable validation failure description.")


class FileValidationSummary(BaseModel):
    """Summary returned by `validate_input_file`."""

    file_path: str
    valid_file: bool
    total_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_identifiers: list[str]
    missing_required_columns: list[str]
    row_level_errors: list[RowValidationError]
    synthetic_data_label: str = "SYNTHETIC DEMO DATA ONLY - Do not upload real PII, PCI, or credentials."
