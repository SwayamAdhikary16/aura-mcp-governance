"""Audit logging, decision explanation, and primary-vs-challenger comparison service for AURA."""

from __future__ import annotations

from typing import Any

from aura.repositories import AuraRepository


class AuditService:
    """Provides structured audit logging, decision explanations, and primary/challenger comparisons."""

    def __init__(self, repo: AuraRepository) -> None:
        self.repo = repo

    def get_audit_record(self, call_id: str) -> dict[str, Any]:
        """Build complete read-only audit record for `call_id` (MCP tool `get_audit_record`)."""
        call_row = self.repo.get_call(call_id)
        events = self.repo.get_audit_events(call_id)
        final_row = self.repo.get_final_result(call_id)

        models_used: list[str] = []
        prompts_used: list[str] = []
        policies_read: list[str] = []
        tools_invoked: list[str] = []
        stage_durations: dict[str, float] = {}
        successful_stages: list[str] = []
        failed_stages: list[str] = []

        for ev in events:
            if ev.get("model_id"):
                m_str = f"{ev['model_id']} (v{ev.get('model_version') or '1.0'})"
                if m_str not in models_used:
                    models_used.append(m_str)
            if ev.get("prompt_name"):
                p_str = f"{ev['prompt_name']} (v{ev.get('prompt_version') or '2.1.0'})"
                if p_str not in prompts_used:
                    prompts_used.append(p_str)
            if ev.get("resource_uri") and ev["resource_uri"] not in policies_read:
                policies_read.append(ev["resource_uri"])
            if ev.get("tool_name") and ev["tool_name"] not in tools_invoked:
                tools_invoked.append(ev["tool_name"])

            stage = ev.get("stage_name", "Unknown")
            stage_durations[stage] = round(stage_durations.get(stage, 0.0) + float(ev.get("duration_ms", 0.0)), 2)
            if ev.get("status") == "Completed" and stage not in successful_stages:
                successful_stages.append(stage)
            elif ev.get("status") in ("Failed", "Error") and stage not in failed_stages:
                failed_stages.append(stage)

        final_disposition = "Pending"
        if final_row:
            parsed_final = final_row["parsed"]
            final_disposition = (
                "Human Governance Review Required"
                if parsed_final.get("human_review_required")
                else f"Completed ({parsed_final.get('final_resolution_status', 'Resolved')})"
            )
        elif call_row.get("processing_status") == "Failed":
            final_disposition = f"Failed ({call_row.get('error_code') or 'Error'})"

        return {
            "call_id": call_id,
            "processing_status": call_row.get("processing_status"),
            "ordered_audit_events": events,
            "models_used": models_used,
            "prompts_used": prompts_used,
            "policies_read": policies_read,
            "tools_invoked": tools_invoked,
            "stage_durations_ms": stage_durations,
            "successful_stages": successful_stages,
            "failed_stages": failed_stages,
            "final_disposition": final_disposition,
        }

    def explain_decision(self, call_id: str) -> dict[str, Any]:
        """Build a concise, business-readable governance explanation without hidden chain-of-thought."""
        self.repo.get_call(call_id)
        fp_row = self.repo.get_first_pass_result(call_id)
        spec_row = self.repo.get_specialist_result(call_id)
        chal_row = self.repo.get_challenger_result(call_id)
        final_row = self.repo.get_final_result(call_id)
        audit_summary = self.get_audit_record(call_id)

        fp = fp_row["parsed"] if fp_row else {}
        spec = spec_row["parsed"] if spec_row else {}
        chal = chal_row["parsed"] if chal_row else {}
        final = final_row["parsed"] if final_row else {}

        route_explanation = (
            f"Call '{call_id}' was routed to '{final.get('final_route', 'N/A')}' "
            f"based on complexity {fp.get('complexity', 'N/A')} and active flags {final.get('detected_flags', [])}."
        )

        specialist_rationale = "Routine analysis path selected; specialist model was not required by routing policy."
        if final.get("specialist_used"):
            specialist_rationale = (
                f"Specialist model evaluated root cause as '{spec.get('root_cause', 'N/A')}' with "
                f"resolution status '{spec.get('resolution_status', 'N/A')}' and risk level '{spec.get('risk_level', 'N/A')}'."
            )

        challenger_rationale = "Challenger model was not triggered because no critical-risk or low-confidence conditions applied."
        if final.get("challenger_used"):
            if chal:
                challenger_rationale = (
                    f"Challenger disposition: '{chal.get('final_disposition', 'N/A')}' "
                    f"(agreement={chal.get('challenger_agreement')}). {chal.get('disagreement_rationale', '')}"
                )
            else:
                challenger_rationale = (
                    "Challenger validation was triggered by policy but encountered a controlled execution error; "
                    "primary decision retained as provisional with mandatory human review."
                )

        return {
            "call_id": call_id,
            "route_explanation": route_explanation,
            "critical_evidence": fp.get("evidence", []),
            "policy_triggers": final.get("routing_reasons", []),
            "models_and_prompts": {
                "models_used": audit_summary["models_used"],
                "prompts_used": audit_summary["prompts_used"],
                "policies_read": audit_summary["policies_read"],
            },
            "specialist_rationale": specialist_rationale,
            "challenger_rationale": challenger_rationale,
            "unresolved_disagreements": final.get("disagreement_fields", []),
            "human_review_required": bool(final.get("human_review_required", True)),
            "human_review_reasons": final.get("human_review_reasons", []),
            "governance_disclaimer": (
                "Concise business-readable rationale derived from structured evidence and policies. "
                "Compliance indicators are analytical signals and not legal determinations."
            ),
        }

    def compare_decisions(self, call_id: str) -> dict[str, Any]:
        """Compare primary analysis decision with challenger validation decision."""
        self.repo.get_call(call_id)
        spec_row = self.repo.get_specialist_result(call_id)
        chal_row = self.repo.get_challenger_result(call_id)
        final_row = self.repo.get_final_result(call_id)

        primary = spec_row["parsed"] if spec_row else {}
        challenger = chal_row["parsed"] if chal_row else {}
        final = final_row["parsed"] if final_row else {}

        primary_values = {
            "resolution_status": primary.get("resolution_status", "N/A"),
            "risk_level": primary.get("risk_level", "Low"),
            "review_required": bool(primary.get("review_required", False)),
            "deflection_eligible": bool(primary.get("deflection_eligible", False)),
            "analysis_confidence": primary.get("analysis_confidence", 0.0),
        }

        if not challenger:
            return {
                "call_id": call_id,
                "challenger_invoked": False,
                "aligned_fields": list(primary_values.keys()),
                "disagreement_fields": [],
                "primary_values": primary_values,
                "challenger_assessments": {},
                "final_disposition": final.get("final_resolution_status", "Not Challenged"),
                "human_review_status": bool(final.get("human_review_required", False)),
                "note": "Challenger validation was not executed for this call.",
            }

        challenger_values = {
            "resolution_status": challenger.get("challenged_resolution_status"),
            "risk_level": challenger.get("challenged_risk_level"),
            "review_required": bool(challenger.get("review_required", False)),
            "challenger_agreement": bool(challenger.get("challenger_agreement", True)),
            "analysis_confidence": challenger.get("analysis_confidence", 0.0),
            "resolution_challenge_note": challenger.get("resolution_challenge_note"),
            "disagreement_rationale": challenger.get("disagreement_rationale"),
        }

        disagreement_fields: list[str] = list(challenger.get("disagreement_fields", []))
        for field in ("resolution_status", "risk_level", "review_required"):
            if primary_values.get(field) != challenger_values.get(field) and field not in disagreement_fields:
                disagreement_fields.append(field)

        aligned_fields = [
            f for f in ("resolution_status", "risk_level", "review_required") if f not in disagreement_fields
        ]

        return {
            "call_id": call_id,
            "challenger_invoked": True,
            "aligned_fields": aligned_fields,
            "disagreement_fields": disagreement_fields,
            "primary_values": primary_values,
            "challenger_assessments": challenger_values,
            "final_disposition": challenger.get("final_disposition", "Confirmed Primary Decision"),
            "human_review_status": bool(final.get("human_review_required", False)),
        }
