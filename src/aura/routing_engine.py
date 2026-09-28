"""Policy-driven routing engine for AURA.

Reads active routing and challenger policies from the SQLite repository.
Never hardcodes duplicate thresholds across modules.
"""

from __future__ import annotations

import hashlib
from typing import Any

from aura.repositories import AuraRepository
from aura.schemas import (
    FirstPassResult,
    RoutineAnalysisResult,
    RoutingDecision,
    SpecialistAnalysisResult,
)


class RoutingEngine:
    """Evaluates first-pass and primary results against SQLite-persisted policies."""

    def __init__(self, repo: AuraRepository) -> None:
        self.repo = repo

    def evaluate_routing(
        self,
        first_pass: FirstPassResult,
        force_challenger: bool = False,
    ) -> RoutingDecision:
        """Determine whether a call routes to routine_analysis or specialist_analysis."""
        routing_record = self.repo.get_active_routing_policy()
        policy = routing_record["policy"]
        rules = policy.get("rules", {})
        policy_version = routing_record["policy_version"]

        challenger_record = self.repo.get_active_governance_policy()
        c_rules = challenger_record["policy"].get("rules", {})

        low_conf_threshold = float(rules.get("low_confidence_threshold", 0.72))
        borderline_conf_threshold = float(rules.get("borderline_confidence_threshold", 0.80))
        mandatory_spec_flags: list[str] = rules.get("specialist_mandatory_flags", [])
        borderline_spec_flags: list[str] = rules.get("borderline_specialist_flags", [])
        critical_chal_flags: list[str] = rules.get("critical_risk_challenger_flags", [])
        safety_hr_flags: list[str] = rules.get("safety_human_review_flags", ["threat_flag", "self_harm_flag"])

        reasons: list[str] = []
        specialist_required = False

        triggered_mandatory = [f for f in mandatory_spec_flags if getattr(first_pass, f, False)]
        if triggered_mandatory:
            specialist_required = True
            reasons.append(f"Mandatory specialist risk flags active: {', '.join(triggered_mandatory)}")

        spec_min, spec_max = rules.get("specialist_complexity_range", [4, 5])
        borderline_c = int(rules.get("borderline_complexity", 3))
        if spec_min <= first_pass.complexity <= spec_max:
            specialist_required = True
            reasons.append(f"Complexity {first_pass.complexity} is within specialist range [{spec_min}, {spec_max}]")
        elif first_pass.complexity == borderline_c:
            triggered_borderline = [f for f in borderline_spec_flags if getattr(first_pass, f, False)]
            if triggered_borderline:
                specialist_required = True
                reasons.append(
                    f"Borderline complexity {borderline_c} with material flags: {', '.join(triggered_borderline)}"
                )
            elif not first_pass.resolved_in_call_flag:
                specialist_required = True
                reasons.append(f"Borderline complexity {borderline_c} with unresolved call status")
            elif first_pass.analysis_confidence < borderline_conf_threshold:
                specialist_required = True
                reasons.append(
                    f"Borderline complexity {borderline_c} with confidence {first_pass.analysis_confidence:.2f} "
                    f"< {borderline_conf_threshold:.2f}"
                )

        if first_pass.needs_deeper_analysis and not specialist_required:
            specialist_required = True
            reasons.append("First-pass triage signaled needs_deeper_analysis=true")

        if first_pass.analysis_confidence < low_conf_threshold:
            specialist_required = True
            reasons.append(
                f"First-pass confidence ({first_pass.analysis_confidence:.2f}) below threshold ({low_conf_threshold:.2f})"
            )

        if not specialist_required:
            routine_min, routine_max = rules.get("routine_complexity_range", [1, 2])
            reasons.append(
                f"Complexity {first_pass.complexity} within routine policy bounds [{routine_min}, {routine_max}] "
                f"with confidence {first_pass.analysis_confidence:.2f} and no material risk flags"
            )

        challenger_reasons: list[str] = []
        triggered_chal_flags = [f for f in critical_chal_flags if getattr(first_pass, f, False)]
        if triggered_chal_flags:
            challenger_reasons.append(f"Critical governance flags active: {', '.join(triggered_chal_flags)}")

        chal_conf_threshold = float(c_rules.get("challenger_confidence_threshold", 0.75))
        if first_pass.analysis_confidence < chal_conf_threshold:
            challenger_reasons.append(
                f"First-pass confidence ({first_pass.analysis_confidence:.2f}) below challenger threshold ({chal_conf_threshold:.2f})"
            )

        if force_challenger:
            challenger_reasons.append("Explicit force_challenger requested by caller")

        human_review_precondition = any(getattr(first_pass, f, False) for f in safety_hr_flags)

        return RoutingDecision(
            selected_route="specialist_analysis" if specialist_required else "routine_analysis",
            routing_reasons=reasons,
            policy_version=policy_version,
            specialist_required=specialist_required,
            challenger_required=bool(challenger_reasons),
            challenger_reasons=challenger_reasons,
            human_review_precondition=human_review_precondition,
        )

    def evaluate_challenger_after_primary(
        self,
        first_pass: FirstPassResult,
        primary_result: SpecialistAnalysisResult | RoutineAnalysisResult,
        initial_decision: RoutingDecision,
        force_challenger: bool = False,
    ) -> tuple[bool, list[str]]:
        """Evaluate whether Challenger validation is needed after primary analysis completes."""
        challenger_record = self.repo.get_active_governance_policy()
        c_rules: dict[str, Any] = challenger_record["policy"].get("rules", {})

        reasons = list(initial_decision.challenger_reasons)
        chal_conf_threshold = float(c_rules.get("challenger_confidence_threshold", 0.75))
        mandatory_risk_levels: list[str] = c_rules.get("mandatory_challenger_risk_levels", ["Critical", "High"])

        if primary_result.analysis_confidence < chal_conf_threshold:
            msg = (
                f"Primary analysis confidence ({primary_result.analysis_confidence:.2f}) "
                f"below challenger threshold ({chal_conf_threshold:.2f})"
            )
            if msg not in reasons:
                reasons.append(msg)

        primary_risk = getattr(primary_result, "risk_level", "Low")
        if primary_risk in mandatory_risk_levels:
            msg = f"Primary analysis assessed risk_level='{primary_risk}' requiring independent challenger review"
            if msg not in reasons:
                reasons.append(msg)

        sample_mod = int(c_rules.get("audit_sample_modulus", 20))
        if sample_mod > 0 and not reasons and isinstance(primary_result, SpecialistAnalysisResult):
            digest = int(hashlib.sha256(first_pass.call_id.encode("utf-8")).hexdigest()[:6], 16)
            if digest % sample_mod == 0:
                reasons.append(f"Selected for deterministic governance audit sample (1-in-{sample_mod})")

        if force_challenger and "Explicit force_challenger requested by caller" not in reasons:
            reasons.append("Explicit force_challenger requested by caller")

        return bool(reasons), reasons
