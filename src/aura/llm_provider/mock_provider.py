"""Deterministic offline Mock LLM Provider for AURA."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from aura.errors import AuraError, ErrorCode
from aura.llm_provider.base import BaseLLMProvider
from aura.schemas import (
    ChallengerAnalysisResult,
    EvidenceSnippet,
    FirstPassResult,
    QualityDimensionAssessment,
    RoutineAnalysisResult,
    SpecialistAnalysisResult,
)


class MockLLMProvider(BaseLLMProvider):
    """Deterministic mock provider supporting all 21 synthetic scenarios and fault-injection tests."""

    provider_name = "mock"

    def __init__(self) -> None:
        self._repair_cache: dict[str, str] = {}

    def _extract_evidence(self, transcript: str, allegation: bool = False) -> list[EvidenceSnippet]:
        lines = [ln.strip() for ln in transcript.splitlines() if ln.strip()]
        snippets: list[EvidenceSnippet] = []
        pattern = re.compile(r"^\[(?P<ts>\d{2}:\d{2})\]\s*(?P<spk>Customer|Agent|Representative):\s*(?P<txt>.+)$", re.I)

        for line in lines:
            if line.startswith("[SCENARIO:") or line.startswith("[SIMULATE_"):
                continue
            m = pattern.match(line)
            if m:
                spk = "Customer" if m.group("spk").lower().startswith("cust") else "Agent"
                fact_type = (
                    "Customer Allegation"
                    if (spk == "Customer" and allegation)
                    else ("Agent Statement" if spk == "Agent" else "Confirmed Fact")
                )
                snippets.append(
                    EvidenceSnippet(
                        timestamp=m.group("ts"),
                        speaker=spk,
                        quote=m.group("txt")[:220],
                        fact_vs_allegation=fact_type,  # type: ignore[arg-type]
                    )
                )
            elif len(snippets) < 2:
                snippets.append(
                    EvidenceSnippet(
                        timestamp="00:15",
                        speaker="Customer",
                        quote=line[:220],
                        fact_vs_allegation="Customer Allegation" if allegation else "Confirmed Fact",
                    )
                )
            if len(snippets) >= 3:
                break

        if not snippets:
            snippets.append(
                EvidenceSnippet(
                    timestamp="00:10",
                    speaker="Customer",
                    quote=transcript[:180].strip() or "Synthetic call interaction.",
                    fact_vs_allegation="Confirmed Fact",
                )
            )
        return snippets

    def _detect_profile(self, call_id: str, transcript: str) -> dict[str, Any]:
        text_lower = transcript.lower()

        if "[simulate_llm_timeout]" in text_lower:
            raise AuraError(
                error_code=ErrorCode.LLM_TIMEOUT,
                user_message="The LLM provider timed out while analyzing the transcript.",
                technical_message=f"Simulated LLM timeout for call_id={call_id}.",
                retryable=True,
                safe_fallback="Mark call for retry or route to human review.",
                human_review_required=True,
            )

        profile: dict[str, Any] = {
            "scenario": "payment_status",
            "complexity": 1,
            "confidence": 0.93,
            "primary_issue": "Payment Status Inquiry",
            "issue_category": "Payment",
            "issue_subcategory": "Payment Posting Status",
            "interaction_origin": "First-Time Inquiry",
            "sentiment": "Neutral -> Satisfied",
            "dispute_flag": False,
            "fraud_flag": False,
            "threat_flag": False,
            "self_harm_flag": False,
            "customer_distress_flag": False,
            "compliance_flag": False,
            "escalation_flag": False,
            "repeat_contact_risk_flag": False,
            "deflection_candidate": True,
            "deflection_channel": "Mobile App",
            "needs_deeper_analysis": False,
            "resolved_in_call_flag": True,
            "resolution_status": "Resolved",
            "risk_level": "Low",
            "challenger_disagree": False,
            "process_gap": False,
            "knowledge_gap": False,
        }

        if "[scenario:self_harm_language]" in text_lower or any(
            k in text_lower for k in ["end my life", "hurt myself", "no reason to keep living", "self-harm"]
        ):
            profile.update(
                {
                    "scenario": "self_harm_language",
                    "complexity": 5,
                    "confidence": 0.96,
                    "primary_issue": "Customer Safety & Self-Harm Indicator",
                    "issue_category": "Safety & Vulnerability",
                    "issue_subcategory": "Self-Harm Expression",
                    "interaction_origin": "First-Time Inquiry",
                    "sentiment": "Distressed -> Critical Concern",
                    "self_harm_flag": True,
                    "customer_distress_flag": True,
                    "deflection_candidate": False,
                    "deflection_channel": "None - Live Agent Required",
                    "needs_deeper_analysis": True,
                    "resolved_in_call_flag": False,
                    "resolution_status": "Escalated",
                    "risk_level": "Critical",
                }
            )
        elif "[scenario:threat_language]" in text_lower or any(
            k in text_lower for k in ["burn the building", "come down to your office and hurt", "violent threat", "threaten violence"]
        ):
            profile.update(
                {
                    "scenario": "threat_language",
                    "complexity": 5,
                    "confidence": 0.95,
                    "primary_issue": "Physical Threat Indicator",
                    "issue_category": "Safety & Security",
                    "issue_subcategory": "Verbal Threat",
                    "interaction_origin": "Repeat Follow-Up",
                    "sentiment": "Hostile -> Hostile",
                    "threat_flag": True,
                    "escalation_flag": True,
                    "deflection_candidate": False,
                    "deflection_channel": "None - Live Agent Required",
                    "needs_deeper_analysis": True,
                    "resolved_in_call_flag": False,
                    "resolution_status": "Escalated",
                    "risk_level": "Critical",
                }
            )
        elif "[scenario:suspected_fraud]" in text_lower or any(
            k in text_lower
            for k in [
                "unauthorized charge",
                "unauthorized fraud",
                "unauthorized transaction",
                "didn't make this purchase",
                "stolen card",
                "stole my identity",
                "suspected fraud",
                "identity theft",
                "fraud investigation",
                "fraud claim",
            ]
        ):
            profile.update(
                {
                    "scenario": "suspected_fraud",
                    "complexity": 5,
                    "confidence": 0.90,
                    "primary_issue": "Suspected Unauthorized Transaction",
                    "issue_category": "Fraud",
                    "issue_subcategory": "Unauthorized Card Activity",
                    "interaction_origin": "Post-Transaction Alert",
                    "sentiment": "Anxious -> Reassured",
                    "fraud_flag": True,
                    "dispute_flag": True,
                    "deflection_candidate": False,
                    "deflection_channel": "None - Live Agent Required",
                    "needs_deeper_analysis": True,
                    "resolved_in_call_flag": False,
                    "resolution_status": "Escalated",
                    "risk_level": "High",
                }
            )
        elif "[scenario:compliance_concern]" in text_lower or any(
            k in text_lower for k in ["misleading disclosure", "promised no interest ever", "harassing calls", "regulatory complaint", "cfpb"]
        ):
            profile.update(
                {
                    "scenario": "compliance_concern",
                    "complexity": 5,
                    "confidence": 0.88,
                    "primary_issue": "Disclosure & Fair Treatment Concern",
                    "issue_category": "Compliance",
                    "issue_subcategory": "Disclosure / Conduct Indicator",
                    "interaction_origin": "Billing Statement Trigger",
                    "sentiment": "Frustrated -> Dissatisfied",
                    "compliance_flag": True,
                    "escalation_flag": True,
                    "deflection_candidate": False,
                    "deflection_channel": "None - Live Agent Required",
                    "needs_deeper_analysis": True,
                    "resolved_in_call_flag": False,
                    "resolution_status": "Escalated",
                    "risk_level": "High",
                }
            )
        elif "[scenario:challenger_disagreement_scenario]" in text_lower or "challenger_disagreement" in text_lower:
            profile.update(
                {
                    "scenario": "challenger_disagreement_scenario",
                    "complexity": 4,
                    "confidence": 0.68,
                    "primary_issue": "Disputed Promotional Financing Expiration",
                    "issue_category": "Dispute",
                    "issue_subcategory": "Promotional Interest Dispute",
                    "interaction_origin": "Billing Statement Trigger",
                    "sentiment": "Confused -> Quietly Dissatisfied",
                    "dispute_flag": True,
                    "compliance_flag": True,
                    "repeat_contact_risk_flag": True,
                    "deflection_candidate": False,
                    "deflection_channel": "None - Live Agent Required",
                    "needs_deeper_analysis": True,
                    "resolved_in_call_flag": True,
                    "resolution_status": "Resolved",
                    "risk_level": "Moderate",
                    "challenger_disagree": True,
                }
            )
        elif "[scenario:customer_distress]" in text_lower or any(
            k in text_lower for k in ["lost my job", "hospital", "crying", "severe hardship", "overwhelmed and panicking"]
        ):
            profile.update(
                {
                    "scenario": "customer_distress",
                    "complexity": 4,
                    "confidence": 0.89,
                    "primary_issue": "Financial Hardship & Customer Distress",
                    "issue_category": "Hardship & Vulnerability",
                    "issue_subcategory": "Payment Assistance Request",
                    "interaction_origin": "First-Time Inquiry",
                    "sentiment": "Distressed -> Supported",
                    "customer_distress_flag": True,
                    "deflection_candidate": False,
                    "deflection_channel": "None - Live Agent Required",
                    "needs_deeper_analysis": True,
                    "resolved_in_call_flag": True,
                    "resolution_status": "Partially Resolved",
                    "risk_level": "High",
                }
            )
        elif "[scenario:merchant_dispute]" in text_lower or any(
            k in text_lower
            for k in [
                "merchant double charged",
                "double billed",
                "damaged merchandise",
                "arrived broken",
                "undelivered merchandise",
                "merchant refused refund",
                "merchant billing dispute",
                "disputing a",
                "dispute a",
                "chargeback",
            ]
        ):
            profile.update(
                {
                    "scenario": "merchant_dispute",
                    "complexity": 4,
                    "confidence": 0.91,
                    "primary_issue": "Merchant Billing Dispute",
                    "issue_category": "Dispute",
                    "issue_subcategory": "Merchant Chargeback",
                    "interaction_origin": "Billing Statement Trigger",
                    "sentiment": "Frustrated -> Cooperative",
                    "dispute_flag": True,
                    "deflection_candidate": False,
                    "deflection_channel": "Web Portal",
                    "needs_deeper_analysis": True,
                    "resolved_in_call_flag": True,
                    "resolution_status": "Partially Resolved",
                    "risk_level": "Moderate",
                }
            )
        elif "[scenario:complaint]" in text_lower or "formal complaint" in text_lower:
            profile.update(
                {
                    "scenario": "complaint",
                    "complexity": 4,
                    "confidence": 0.90,
                    "primary_issue": "Service Quality Formal Complaint",
                    "issue_category": "Complaint",
                    "issue_subcategory": "Service Handling Dissatisfaction",
                    "interaction_origin": "Repeat Follow-Up",
                    "sentiment": "Angry -> Guarded",
                    "escalation_flag": True,
                    "repeat_contact_risk_flag": True,
                    "deflection_candidate": False,
                    "deflection_channel": "None - Live Agent Required",
                    "needs_deeper_analysis": True,
                    "resolved_in_call_flag": False,
                    "resolution_status": "Unresolved",
                    "risk_level": "Moderate",
                }
            )
        elif "[scenario:supervisor_request]" in text_lower or "speak to a supervisor" in text_lower or "manager right now" in text_lower:
            profile.update(
                {
                    "scenario": "supervisor_request",
                    "complexity": 4,
                    "confidence": 0.91,
                    "primary_issue": "Supervisor Escalation Request",
                    "issue_category": "Escalation",
                    "issue_subcategory": "Supervisor Transfer",
                    "interaction_origin": "Repeat Follow-Up",
                    "sentiment": "Frustrated -> Escalated",
                    "escalation_flag": True,
                    "deflection_candidate": False,
                    "deflection_channel": "None - Live Agent Required",
                    "needs_deeper_analysis": True,
                    "resolved_in_call_flag": False,
                    "resolution_status": "Escalated",
                    "risk_level": "Moderate",
                }
            )
        elif "[scenario:ambiguous_multi_intent_call]" in text_lower or any(
            k in text_lower for k in ["multi-intent", "multi-promo", "retro interest", "deferred interest"]
        ):
            profile.update(
                {
                    "scenario": "ambiguous_multi_intent_call",
                    "complexity": 4,
                    "confidence": 0.69,
                    "primary_issue": "Multi-Intent Billing, Address, and Dispute Inquiry",
                    "issue_category": "Account Servicing",
                    "issue_subcategory": "Multi-Intent Complex Servicing",
                    "interaction_origin": "Repeat Follow-Up",
                    "sentiment": "Confused -> Partially Satisfied",
                    "dispute_flag": True,
                    "repeat_contact_risk_flag": True,
                    "deflection_candidate": False,
                    "deflection_channel": "None - Live Agent Required",
                    "needs_deeper_analysis": True,
                    "resolved_in_call_flag": False,
                    "resolution_status": "Partially Resolved",
                    "risk_level": "Moderate",
                }
            )
        elif "[scenario:process_gap]" in text_lower or "process gap" in text_lower:
            profile.update(
                {
                    "scenario": "process_gap",
                    "complexity": 3,
                    "confidence": 0.85,
                    "primary_issue": "Back-Office Workflow Delay",
                    "issue_category": "Operations",
                    "issue_subcategory": "Process Gap Delay",
                    "interaction_origin": "Repeat Follow-Up",
                    "sentiment": "Impatient -> Neutral",
                    "repeat_contact_risk_flag": True,
                    "needs_deeper_analysis": True,
                    "deflection_candidate": False,
                    "deflection_channel": "None",
                    "resolved_in_call_flag": False,
                    "resolution_status": "Partially Resolved",
                    "risk_level": "Moderate",
                    "process_gap": True,
                }
            )
        elif "[scenario:knowledge_gap]" in text_lower or "knowledge gap" in text_lower:
            profile.update(
                {
                    "scenario": "knowledge_gap",
                    "complexity": 3,
                    "confidence": 0.84,
                    "primary_issue": "Unclear Policy Explanation by Representative",
                    "issue_category": "Account Servicing",
                    "issue_subcategory": "Policy Guidance Clarification",
                    "interaction_origin": "First-Time Inquiry",
                    "sentiment": "Neutral -> Confused",
                    "repeat_contact_risk_flag": True,
                    "needs_deeper_analysis": True,
                    "deflection_candidate": False,
                    "deflection_channel": "Web Portal",
                    "resolved_in_call_flag": False,
                    "resolution_status": "Partially Resolved",
                    "risk_level": "Moderate",
                    "knowledge_gap": True,
                }
            )
        elif "[scenario:repeat_contact_risk]" in text_lower or "third time calling" in text_lower:
            profile.update(
                {
                    "scenario": "repeat_contact_risk",
                    "complexity": 3,
                    "confidence": 0.86,
                    "primary_issue": "Repeated Contact on Pending Account Adjustment",
                    "issue_category": "Billing",
                    "issue_subcategory": "Pending Adjustment Follow-Up",
                    "interaction_origin": "Repeat Follow-Up",
                    "sentiment": "Weary -> Cautious",
                    "repeat_contact_risk_flag": True,
                    "needs_deeper_analysis": True,
                    "deflection_candidate": False,
                    "deflection_channel": "Secure Messaging",
                    "resolved_in_call_flag": False,
                    "resolution_status": "Partially Resolved",
                    "risk_level": "Moderate",
                }
            )
        elif "[scenario:unresolved_call]" in text_lower or "still unresolved" in text_lower:
            profile.update(
                {
                    "scenario": "unresolved_call",
                    "complexity": 3,
                    "confidence": 0.83,
                    "primary_issue": "Unresolved Statement Reconciliation",
                    "issue_category": "Billing",
                    "issue_subcategory": "Statement Reconciliation",
                    "interaction_origin": "Billing Statement Trigger",
                    "sentiment": "Frustrated -> Unsatisfied",
                    "repeat_contact_risk_flag": True,
                    "needs_deeper_analysis": True,
                    "deflection_candidate": False,
                    "deflection_channel": "None",
                    "resolved_in_call_flag": False,
                    "resolution_status": "Unresolved",
                    "risk_level": "Moderate",
                }
            )
        elif "[scenario:fee_issue]" in text_lower or "late fee" in text_lower:
            profile.update(
                {
                    "scenario": "fee_issue",
                    "complexity": 2,
                    "confidence": 0.92,
                    "primary_issue": "Late Fee Courtesy Waiver Request",
                    "issue_category": "Billing",
                    "issue_subcategory": "Fee Waiver",
                    "interaction_origin": "Billing Statement Trigger",
                    "sentiment": "Concerned -> Satisfied",
                    "deflection_candidate": True,
                    "deflection_channel": "Mobile App",
                    "needs_deeper_analysis": False,
                    "resolved_in_call_flag": True,
                    "resolution_status": "Resolved",
                    "risk_level": "Low",
                }
            )
        elif "[scenario:billing_issue]" in text_lower or "statement cycle" in text_lower:
            profile.update(
                {
                    "scenario": "billing_issue",
                    "complexity": 2,
                    "confidence": 0.91,
                    "primary_issue": "Statement Closing Date & Minimum Due Inquiry",
                    "issue_category": "Billing",
                    "issue_subcategory": "Statement Explanation",
                    "interaction_origin": "Billing Statement Trigger",
                    "sentiment": "Neutral -> Satisfied",
                    "deflection_candidate": True,
                    "deflection_channel": "Web Portal",
                    "needs_deeper_analysis": False,
                    "resolved_in_call_flag": True,
                    "resolution_status": "Resolved",
                    "risk_level": "Low",
                }
            )
        elif "[scenario:authentication_issue]" in text_lower or "one-time passcode" in text_lower or "login reset" in text_lower:
            profile.update(
                {
                    "scenario": "authentication_issue",
                    "complexity": 2,
                    "confidence": 0.92,
                    "primary_issue": "Digital Login & OTP Verification Assistance",
                    "issue_category": "Authentication",
                    "issue_subcategory": "Passcode / Profile Unlock",
                    "interaction_origin": "Self-Service Failure",
                    "sentiment": "Mildly Frustrated -> Relieved",
                    "deflection_candidate": True,
                    "deflection_channel": "Automated SMS",
                    "needs_deeper_analysis": False,
                    "resolved_in_call_flag": True,
                    "resolution_status": "Resolved",
                    "risk_level": "Low",
                }
            )
        elif "[scenario:transfer_issue]" in text_lower or "department transfer" in text_lower:
            profile.update(
                {
                    "scenario": "transfer_issue",
                    "complexity": 2,
                    "confidence": 0.90,
                    "primary_issue": "Account Routing & Department Transfer Inquiry",
                    "issue_category": "Account Servicing",
                    "issue_subcategory": "Queue Routing",
                    "interaction_origin": "First-Time Inquiry",
                    "sentiment": "Neutral -> Satisfied",
                    "deflection_candidate": True,
                    "deflection_channel": "IVR",
                    "needs_deeper_analysis": False,
                    "resolved_in_call_flag": True,
                    "resolution_status": "Resolved",
                    "risk_level": "Low",
                }
            )
        elif "[scenario:deflection_opportunity]" in text_lower or "paperless" in text_lower or "autopay" in text_lower:
            profile.update(
                {
                    "scenario": "deflection_opportunity",
                    "complexity": 1,
                    "confidence": 0.95,
                    "primary_issue": "AutoPay & Paperless Enrollment",
                    "issue_category": "Self-Service",
                    "issue_subcategory": "AutoPay Enrollment",
                    "interaction_origin": "First-Time Inquiry",
                    "sentiment": "Positive -> Satisfied",
                    "deflection_candidate": True,
                    "deflection_channel": "Mobile App",
                    "needs_deeper_analysis": False,
                    "resolved_in_call_flag": True,
                    "resolution_status": "Resolved",
                    "risk_level": "Low",
                }
            )
        elif "[scenario:balance_information]" in text_lower or "current balance" in text_lower or "available credit" in text_lower:
            profile.update(
                {
                    "scenario": "balance_information",
                    "complexity": 1,
                    "confidence": 0.96,
                    "primary_issue": "Current Balance & Available Credit Check",
                    "issue_category": "Balance",
                    "issue_subcategory": "Balance Inquiry",
                    "interaction_origin": "First-Time Inquiry",
                    "sentiment": "Neutral -> Satisfied",
                    "deflection_candidate": True,
                    "deflection_channel": "Mobile App",
                    "needs_deeper_analysis": False,
                    "resolved_in_call_flag": True,
                    "resolution_status": "Resolved",
                    "risk_level": "Low",
                }
            )

        return profile

    def _raw_first_pass(self, call_id: str, transcript: str, review_goal: str | None = None) -> str:
        profile = self._detect_profile(call_id, transcript)
        allegation = any(
            profile[k]
            for k in ("dispute_flag", "fraud_flag", "compliance_flag", "threat_flag", "self_harm_flag")
        )
        fp = FirstPassResult(
            call_id=call_id,
            summary=(
                f"Synthetic call {call_id} classified under '{profile['primary_issue']}' "
                f"({profile['issue_category']} / {profile['issue_subcategory']}) with complexity {profile['complexity']}."
            ),
            complexity=profile["complexity"],
            analysis_confidence=profile["confidence"],
            primary_issue=profile["primary_issue"],
            issue_category=profile["issue_category"],
            issue_subcategory=profile["issue_subcategory"],
            interaction_origin=profile["interaction_origin"],
            sentiment_progression=profile["sentiment"],
            dispute_flag=profile["dispute_flag"],
            fraud_flag=profile["fraud_flag"],
            threat_flag=profile["threat_flag"],
            self_harm_flag=profile["self_harm_flag"],
            customer_distress_flag=profile["customer_distress_flag"],
            compliance_flag=profile["compliance_flag"],
            escalation_flag=profile["escalation_flag"],
            repeat_contact_risk_flag=profile["repeat_contact_risk_flag"],
            deflection_candidate=profile["deflection_candidate"],
            needs_deeper_analysis=profile["needs_deeper_analysis"],
            resolved_in_call_flag=profile["resolved_in_call_flag"],
            evidence=self._extract_evidence(transcript, allegation=allegation),
        )
        valid_json = fp.model_dump_json()

        if "[SIMULATE_REPAIRABLE_JSON]" in transcript:
            broken = "{malformed_json_missing_quotes: true, call_id: " + call_id
            self._repair_cache[broken] = valid_json
            return broken
        if "[SIMULATE_UNREPAIRABLE_JSON]" in transcript:
            return "{unrepairable_corrupted_payload: <<<INVALID>>>"

        return valid_json

    def _raw_routine_analysis(self, call_id: str, transcript: str, first_pass: FirstPassResult) -> str:
        profile = self._detect_profile(call_id, transcript)
        routine = RoutineAnalysisResult(
            call_id=call_id,
            resolution_status=profile["resolution_status"],
            first_contact_resolution=True,
            call_avoidable=profile["deflection_candidate"],
            deflection_eligible=profile["deflection_candidate"],
            deflection_channel=profile["deflection_channel"],
            review_required=False,
            analysis_confidence=min(0.96, round(first_pass.analysis_confidence + 0.01, 2)),
            quality_scores=[
                QualityDimensionAssessment(
                    dimension_name="Next Step Clarity",
                    rating="Strong",
                    rationale="Representative clearly confirmed account status and next billing cycle timeline.",
                ),
                QualityDimensionAssessment(
                    dimension_name="Control of the Call",
                    rating="Strong",
                    rationale="Structured verification and direct response to routine inquiry.",
                ),
                QualityDimensionAssessment(
                    dimension_name="Option Framing",
                    rating="Strong",
                    rationale=f"Highlighted self-service availability via {profile['deflection_channel']}.",
                ),
                QualityDimensionAssessment(
                    dimension_name="Objection Handling",
                    rating="Adequate",
                    rationale="Addressed follow-up questions accurately.",
                ),
                QualityDimensionAssessment(
                    dimension_name="Empathy and Tone",
                    rating="Strong",
                    rationale="Professional, courteous tone maintained throughout.",
                ),
            ],
            coaching_note=(
                f"Routine '{first_pass.primary_issue}' handled effectively on first contact; "
                f"eligible for {profile['deflection_channel']} self-service."
            ),
        )
        return routine.model_dump_json()

    def _raw_specialist_analysis(
        self,
        call_id: str,
        transcript: str,
        first_pass: FirstPassResult,
        historical_context: dict[str, Any] | None = None,
    ) -> str:
        if "[SIMULATE_SPECIALIST_FAILURE]" in transcript:
            raise AuraError(
                error_code=ErrorCode.SPECIALIST_FAILURE,
                user_message="Specialist analysis model encountered an execution failure. Retaining first-pass triage as provisional.",
                technical_message=f"Simulated specialist failure for call_id={call_id}.",
                retryable=True,
                safe_fallback="Retain first-pass result as provisional and require human review.",
                human_review_required=True,
            )

        profile = self._detect_profile(call_id, transcript)
        hist_count = (historical_context or {}).get("similar_call_count", 0)
        review_req = bool(
            first_pass.threat_flag
            or first_pass.self_harm_flag
            or first_pass.fraud_flag
            or first_pass.compliance_flag
            or profile["risk_level"] in ("High", "Critical")
        )
        if profile["challenger_disagree"]:
            review_req = False

        spec = SpecialistAnalysisResult(
            call_id=call_id,
            resolution_status=profile["resolution_status"],
            first_contact_resolution=first_pass.interaction_origin == "First-Time Inquiry" and first_pass.resolved_in_call_flag,
            call_avoidable=bool(profile["process_gap"] or profile["knowledge_gap"] or first_pass.repeat_contact_risk_flag),
            deflection_eligible=profile["deflection_candidate"],
            deflection_channel=profile["deflection_channel"],
            review_required=review_req,
            analysis_confidence=profile["confidence"],
            risk_level=profile["risk_level"],
            root_cause=(
                "Process Gap"
                if profile["process_gap"]
                else ("Knowledge Gap" if profile["knowledge_gap"] else first_pass.primary_issue)
            ),
            complaint_analysis=(
                "Customer expressed material dissatisfaction requiring documented complaint tracking."
                if (first_pass.escalation_flag or first_pass.issue_category == "Complaint")
                else "No formal service complaint beyond primary transaction inquiry."
            ),
            dispute_analysis=(
                "Customer allegation of billing/merchant discrepancy logged; requires documentary verification."
                if first_pass.dispute_flag
                else "No merchant or billing dispute raised."
            ),
            fraud_analysis=(
                "Customer reported unrecognized transaction indicators; fraud claim workflow initiated."
                if first_pass.fraud_flag
                else "No unauthorized account access indicators detected."
            ),
            compliance_analysis=(
                "Analytical compliance indicator flagged regarding promotional/disclosure clarity or contact frequency "
                "(analytical signal only, not a legal determination)."
                if first_pass.compliance_flag
                else "No analytical compliance indicators triggered."
            ),
            process_gap_identified=profile["process_gap"],
            knowledge_gap_identified=profile["knowledge_gap"],
            quality_scores=[
                QualityDimensionAssessment(
                    dimension_name="Next Step Clarity",
                    rating="Adequate" if first_pass.resolved_in_call_flag else "Needs Improvement",
                    rationale="Evaluated clarity of investigation timelines and reference numbers.",
                ),
                QualityDimensionAssessment(
                    dimension_name="Control of the Call",
                    rating="Adequate",
                    rationale="Representative maintained structure during complex interaction.",
                ),
                QualityDimensionAssessment(
                    dimension_name="Option Framing",
                    rating="Needs Improvement" if profile["knowledge_gap"] else "Adequate",
                    rationale="Assessed accuracy of dispute, hardship, or policy option framing.",
                ),
                QualityDimensionAssessment(
                    dimension_name="Objection Handling",
                    rating="Adequate",
                    rationale="Addressed customer objections using account records.",
                ),
                QualityDimensionAssessment(
                    dimension_name="Empathy and Tone",
                    rating="Strong" if first_pass.customer_distress_flag else "Adequate",
                    rationale="Evaluated empathy alignment with customer emotional state.",
                ),
            ],
            recommended_actions=[
                f"Verify {first_pass.issue_category} documentation and case notes.",
                f"Contextualized against {hist_count} historical similar synthetic calls (informational only).",
            ],
            evidence=first_pass.evidence,
        )
        return spec.model_dump_json()

    def _raw_challenger_analysis(
        self,
        call_id: str,
        transcript: str,
        first_pass: FirstPassResult,
        primary_result: SpecialistAnalysisResult | RoutineAnalysisResult,
    ) -> str:
        if "[SIMULATE_CHALLENGER_FAILURE]" in transcript:
            raise AuraError(
                error_code=ErrorCode.CHALLENGER_FAILURE,
                user_message="Challenger validation model failed during execution. Retaining primary result as provisional and requiring human review.",
                technical_message=f"Simulated challenger failure for call_id={call_id}.",
                retryable=True,
                safe_fallback="Retain primary specialist result as provisional and mandate human review.",
                human_review_required=True,
            )

        profile = self._detect_profile(call_id, transcript)
        primary_risk = getattr(primary_result, "risk_level", "Low")

        if profile["challenger_disagree"]:
            chal = ChallengerAnalysisResult(
                call_id=call_id,
                challenger_agreement=False,
                review_required=True,
                analysis_confidence=0.89,
                final_disposition="Escalated to Human Governance Review",
                challenged_resolution_status="Unresolved",
                challenged_risk_level="High",
                resolution_challenge_note=(
                    "CHALLENGE DISAGREEMENT: Primary analysis marked call as 'Resolved', but customer explicitly "
                    "stated they still disputed the promotional interest charge at call close."
                ),
                escalation_challenge_note="Customer hinted at regulatory escalation if interest was not reversed.",
                sentiment_challenge_note="Customer remained dissatisfied despite polite closing.",
                interaction_origin_challenge_note=f"Confirmed origin: {first_pass.interaction_origin}.",
                agent_performance_challenge_note="Agent did not clearly explain promotional expiration date terms.",
                deflection_challenge_note="Live specialist required; not eligible for self-service deflection.",
                disagreement_fields=["resolution_status", "risk_level", "review_required"],
                disagreement_rationale=(
                    "Primary model over-optimistically classified call as Resolved/Moderate risk; "
                    "Challenger detected unresolved promotional terms dispute and elevated risk to High."
                ),
            )
            return chal.model_dump_json()

        if first_pass.threat_flag or first_pass.self_harm_flag:
            chal = ChallengerAnalysisResult(
                call_id=call_id,
                challenger_agreement=True,
                review_required=True,
                analysis_confidence=0.97,
                final_disposition="Flagged Safety Priority Review",
                challenged_resolution_status="Escalated",
                challenged_risk_level="Critical",
                resolution_challenge_note="Confirmed immediate escalation required for safety indicator.",
                escalation_challenge_note="Highest priority human specialist/supervisor review mandatory.",
                sentiment_challenge_note="Acute safety/distress indicators verified in transcript.",
                interaction_origin_challenge_note=f"Confirmed origin: {first_pass.interaction_origin}.",
                agent_performance_challenge_note="Evaluated adherence to critical safety escalation protocol.",
                deflection_challenge_note="Deflection strictly prohibited for safety-flagged calls.",
                disagreement_fields=[],
                disagreement_rationale="Primary and Challenger models align on Critical safety priority and mandatory human review.",
            )
            return chal.model_dump_json()

        chal = ChallengerAnalysisResult(
            call_id=call_id,
            challenger_agreement=True,
            review_required=bool(primary_result.review_required or first_pass.fraud_flag or first_pass.compliance_flag),
            analysis_confidence=0.91,
            final_disposition="Confirmed Primary Decision",
            challenged_resolution_status=primary_result.resolution_status,
            challenged_risk_level=primary_risk,  # type: ignore[arg-type]
            resolution_challenge_note=f"Confirmed resolution status '{primary_result.resolution_status}' matches transcript evidence.",
            escalation_challenge_note="Escalation indicators accurately captured by primary analysis.",
            sentiment_challenge_note=f"Verified sentiment progression ({first_pass.sentiment_progression}).",
            interaction_origin_challenge_note=f"Confirmed interaction origin ({first_pass.interaction_origin}).",
            agent_performance_challenge_note="Quality dimension ratings are consistent with transcript evidence.",
            deflection_challenge_note=f"Confirmed deflection channel '{primary_result.deflection_channel}' appropriateness.",
            disagreement_fields=[],
            disagreement_rationale="No material disagreement identified between primary and challenger models.",
        )
        return chal.model_dump_json()

    def repair_json_response(self, broken_json: str, schema_name: str, error_details: str) -> str:
        if broken_json in self._repair_cache:
            return self._repair_cache[broken_json]
        if "unrepairable" in broken_json.lower():
            return broken_json
        cleaned = broken_json.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
            cleaned = re.sub(r"```.*$", "", cleaned, flags=re.DOTALL).strip()
        start_idx = cleaned.find("{")
        end_idx = cleaned.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            return cleaned[start_idx : end_idx + 1]
        return cleaned

    def run_candidate_model_analysis(
        self,
        call_id: str,
        transcript: str,
        candidate_model_id: str,
    ) -> dict[str, Any]:
        profile = self._detect_profile(call_id, transcript)
        digest = int(hashlib.sha256(f"{call_id}:{candidate_model_id}".encode("utf-8")).hexdigest()[:8], 16)

        cand_route = "specialist_analysis" if profile["complexity"] >= 4 or profile["needs_deeper_analysis"] else "routine_analysis"
        cand_risk = profile["risk_level"]
        cand_resolution = profile["resolution_status"]
        cand_human_review = bool(
            profile["threat_flag"]
            or profile["self_harm_flag"]
            or profile["fraud_flag"]
            or profile["compliance_flag"]
            or profile["challenger_disagree"]
        )

        if digest % 9 == 0 and profile["complexity"] == 3:
            cand_route = "routine_analysis"
        if digest % 13 == 0 and cand_risk == "High":
            cand_risk = "Moderate"
        if "EXPERIMENTAL" in candidate_model_id.upper() or digest % 17 == 0:
            if profile["dispute_flag"]:
                cand_resolution = "Resolved"

        return {
            "call_id": call_id,
            "candidate_model_id": candidate_model_id,
            "final_route": cand_route,
            "final_risk_level": cand_risk,
            "final_resolution_status": cand_resolution,
            "human_review_required": cand_human_review,
            "complexity": profile["complexity"],
            "confidence": round(max(0.65, min(0.98, profile["confidence"] - 0.02 + ((digest % 5) * 0.01))), 2),
        }
