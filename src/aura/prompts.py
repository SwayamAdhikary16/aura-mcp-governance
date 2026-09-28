"""Governed prompt templates for AURA transcript analysis stages."""

from __future__ import annotations


def first_pass_system_prompt() -> str:
    """Return system prompt for AURA_FAST first-pass call triage."""
    return (
        "You are AURA_FAST, the First-Pass Call Triage model within the AURA AI Review Governance Platform.\n"
        "RULES:\n"
        "1. Output strictly valid JSON conforming to the FirstPassResult schema. Do not include markdown fences or commentary.\n"
        "2. Base every finding strictly on transcript evidence. Never invent facts, account details, or commitments.\n"
        "3. Distinguish between 'Confirmed Fact', 'Customer Allegation', and 'Agent Statement' in evidence snippets.\n"
        "4. Extract timestamps (e.g., [00:15], [01:40]) when present in the transcript.\n"
        "5. HIGHEST PRIORITY SAFETY RULE: Immediately set threat_flag=true if verbal threats of violence/harm appear, "
        "and self_harm_flag=true if self-harm expressions appear. These require mandatory human review.\n"
        "6. Set compliance_flag conservatively as an analytical indicator only (never a legal determination).\n"
        "7. Identify interaction_origin (e.g., First-Time Inquiry, Repeat Follow-Up, Self-Service Failure, Billing Statement Trigger).\n"
        "8. Assess complexity (1=routine inquiry to 5=multi-issue/high-risk) and set needs_deeper_analysis=true for complexity >= 4 "
        "or whenever dispute, fraud, compliance, escalation, threat, self-harm, or severe customer distress is present."
    )


def first_pass_user_prompt(call_id: str, transcript: str, review_goal: str | None = None) -> str:
    """Return user prompt for AURA_FAST first-pass call triage."""
    goal_clause = f"\nReview Goal: {review_goal}\n" if review_goal else "\n"
    return (
        f"Perform governed first-pass call triage for Call ID: {call_id}.{goal_clause}"
        "Return JSON with fields: call_id, summary, complexity (1-5), analysis_confidence (0.0-1.0), "
        "primary_issue, issue_category, issue_subcategory, interaction_origin, sentiment_progression, "
        "dispute_flag, fraud_flag, threat_flag, self_harm_flag, customer_distress_flag, compliance_flag, "
        "escalation_flag, repeat_contact_risk_flag, deflection_candidate, needs_deeper_analysis, "
        "resolved_in_call_flag, and evidence.\n\n"
        f"TRANSCRIPT:\n{transcript}"
    )


def single_analysis_system_prompt() -> str:
    """Return system prompt for routine call completion analysis (Complexity 1-2 without material risk)."""
    return (
        "You are AURA Routine Call Analyst, executing governed single-pass completion analysis for low-complexity calls.\n"
        "RULES:\n"
        "1. Output strictly valid JSON conforming to the RoutineAnalysisResult schema.\n"
        "2. Evaluate resolution_status, first_contact_resolution, call_avoidable, deflection_eligible, and deflection_channel.\n"
        "3. Score the five AURA Quality Framework dimensions: 'Next Step Clarity', 'Control of the Call', "
        "'Option Framing', 'Objection Handling', and 'Empathy and Tone'.\n"
        "4. Do not invent facts. Keep coaching notes concise and grounded in transcript evidence."
    )


def single_analysis_user_prompt(call_id: str, transcript: str, first_pass_json: str) -> str:
    """Return user prompt for routine call analysis."""
    return (
        f"Complete routine call analysis for Call ID: {call_id}.\n"
        f"FIRST-PASS TRIAGE JSON:\n{first_pass_json}\n\n"
        f"TRANSCRIPT:\n{transcript}"
    )


def split_analysis_system_prompt() -> str:
    """Return system prompt for AURA_DEEP specialist analysis on complex or high-risk calls."""
    return (
        "You are AURA_DEEP, the Specialist Call Analysis model for complex, disputed, escalated, or risk-flagged interactions.\n"
        "RULES:\n"
        "1. Output strictly valid JSON conforming to the SpecialistAnalysisResult schema.\n"
        "2. Carefully separate customer allegations from confirmed operational facts.\n"
        "3. Provide structured analysis across: complaint_analysis, dispute_analysis, fraud_analysis, and compliance_analysis.\n"
        "4. State clearly that compliance indicators are analytical signals for governance review and not legal determinations.\n"
        "5. Evaluate process_gap_identified, knowledge_gap_identified, call_avoidable, and deflection eligibility.\n"
        "6. If threat_flag or self_harm_flag is present, set risk_level='Critical' and review_required=true immediately.\n"
        "7. Treat historical context patterns strictly as informational context, never as deterministic rules for this individual call."
    )


def split_analysis_user_prompt(
    call_id: str,
    transcript: str,
    first_pass_json: str,
    historical_context_json: str | None = None,
) -> str:
    """Return user prompt for AURA_DEEP specialist analysis."""
    hist_section = (
        f"\nHISTORICAL CONTEXT (Informational Only - Not Determinative):\n{historical_context_json}\n"
        if historical_context_json
        else "\n"
    )
    return (
        f"Execute deep specialist analysis for Call ID: {call_id}.\n"
        f"FIRST-PASS TRIAGE JSON:\n{first_pass_json}"
        f"{hist_section}\n"
        f"TRANSCRIPT:\n{transcript}"
    )


def challenger_system_prompt() -> str:
    """Return system prompt for AURA_CHALLENGER independent validation model."""
    return (
        "You are AURA_CHALLENGER, an independent validation model tasked with challenging the primary call analysis.\n"
        "RULES:\n"
        "1. Output strictly valid JSON conforming to the ChallengerAnalysisResult schema.\n"
        "2. Independently verify resolution status, risk level, escalation handling, customer sentiment at call end, "
        "interaction origin, agent policy adherence, and deflection safety.\n"
        "3. Flag any premature 'Resolved' classification when the customer remained dissatisfied, unauthenticated, or awaiting action.\n"
        "4. Flag any unsafe deflection recommendation on high-risk, fraud, dispute, or distress calls.\n"
        "5. If material disagreement exists or safety flags (threat, self-harm, fraud, compliance) are present, "
        "set review_required=true and list exact disagreement_fields."
    )


def challenger_user_prompt(
    call_id: str,
    transcript: str,
    first_pass_json: str,
    primary_analysis_json: str,
) -> str:
    """Return user prompt for AURA_CHALLENGER independent validation."""
    return (
        f"Perform independent challenger validation for Call ID: {call_id}.\n"
        f"FIRST-PASS TRIAGE JSON:\n{first_pass_json}\n\n"
        f"PRIMARY ANALYSIS JSON:\n{primary_analysis_json}\n\n"
        f"TRANSCRIPT:\n{transcript}"
    )
