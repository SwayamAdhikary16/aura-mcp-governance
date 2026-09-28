"""Portfolio governance metrics and candidate model upgrade simulation service for AURA."""

from __future__ import annotations

import json
from typing import Any

from aura.database import get_db_connection
from aura.llm_provider import get_llm_provider
from aura.repositories import AuraRepository


class MetricsService:
    """Calculates portfolio-level governance metrics and model-upgrade simulations from SQLite."""

    def __init__(self, repo: AuraRepository) -> None:
        self.repo = repo

    def get_portfolio_summary(self, job_id: str | None = None) -> dict[str, Any]:
        """Compute aggregate processing and governance metrics from SQLite."""
        with get_db_connection(self.repo.db_path) as conn:
            call_filter = "WHERE job_id = ?" if job_id else ""
            params: tuple[Any, ...] = (job_id,) if job_id else ()

            calls_rows = conn.execute(f"SELECT * FROM calls {call_filter}", params).fetchall()
            total_ingested = len(calls_rows)
            call_ids = [r["call_id"] for r in calls_rows]

            successful_calls = sum(1 for r in calls_rows if r["processing_status"] in ("Completed", "Human Review Required"))
            failed_calls = sum(1 for r in calls_rows if r["processing_status"] == "Failed")
            total_processed = successful_calls + failed_calls

            if call_ids:
                placeholders = ",".join("?" for _ in call_ids)
                final_rows = conn.execute(
                    f"SELECT * FROM final_results WHERE call_id IN ({placeholders})",
                    tuple(call_ids),
                ).fetchall()
                fp_rows = conn.execute(
                    f"SELECT * FROM first_pass_results WHERE call_id IN ({placeholders})",
                    tuple(call_ids),
                ).fetchall()
                spec_rows = conn.execute(
                    f"SELECT * FROM specialist_results WHERE call_id IN ({placeholders})",
                    tuple(call_ids),
                ).fetchall()
                audit_rows = conn.execute(
                    f"SELECT stage_name, AVG(duration_ms) as avg_ms FROM audit_log "
                    f"WHERE call_id IN ({placeholders}) GROUP BY stage_name",
                    tuple(call_ids),
                ).fetchall()
            else:
                final_rows, fp_rows, spec_rows, audit_rows = [], [], [], []

        first_pass_only_calls = sum(1 for r in final_rows if not r["specialist_used"] and not r["challenger_used"])
        specialist_calls = sum(1 for r in final_rows if r["specialist_used"])
        challenger_calls = sum(1 for r in final_rows if r["challenger_used"])
        human_review_calls = sum(1 for r in final_rows if r["human_review_required"])

        denom = max(1, len(final_rows))
        routine_pct = round((first_pass_only_calls / denom) * 100.0, 1) if final_rows else 0.0
        specialist_pct = round((specialist_calls / denom) * 100.0, 1) if final_rows else 0.0
        challenger_pct = round((challenger_calls / denom) * 100.0, 1) if final_rows else 0.0

        # Workflow-derived estimate: In an ungoverned pipeline that runs specialist + challenger on every call
        # (2 premium calls per transcript), governed routing avoids premium calls whenever specialist or challenger is skipped.
        ungoverned_premium_calls = len(final_rows) * 2
        actual_premium_calls = specialist_calls + challenger_calls
        premium_calls_avoided = max(0, ungoverned_premium_calls - actual_premium_calls)

        # Distributions
        risk_flag_dist: dict[str, int] = {
            "dispute_flag": 0,
            "fraud_flag": 0,
            "threat_flag": 0,
            "self_harm_flag": 0,
            "customer_distress_flag": 0,
            "compliance_flag": 0,
            "escalation_flag": 0,
            "repeat_contact_risk_flag": 0,
            "deflection_candidate": 0,
        }
        issue_cat_dist: dict[str, int] = {}
        for fp in fp_rows:
            cat = fp["issue_category"]
            issue_cat_dist[cat] = issue_cat_dist.get(cat, 0) + 1
            for flag_name in risk_flag_dist:
                if fp[flag_name]:
                    risk_flag_dist[flag_name] += 1

        deflection_dist: dict[str, int] = {}
        for sr in spec_rows:
            ch = sr["deflection_channel"] or "None"
            deflection_dist[ch] = deflection_dist.get(ch, 0) + 1

        route_dist: dict[str, int] = {}
        risk_level_dist: dict[str, int] = {}
        for fr in final_rows:
            rt = fr["final_route"]
            rl = fr["final_risk_level"]
            route_dist[rt] = route_dist.get(rt, 0) + 1
            risk_level_dist[rl] = risk_level_dist.get(rl, 0) + 1

        avg_stage_durations = {r["stage_name"]: round(float(r["avg_ms"] or 0.0), 2) for r in audit_rows}

        return {
            "job_id": job_id or "ALL_JOBS",
            "total_calls_ingested": total_ingested,
            "total_calls_processed": total_processed,
            "successful_calls": successful_calls,
            "failed_calls": failed_calls,
            "first_pass_only_calls": first_pass_only_calls,
            "specialist_review_calls": specialist_calls,
            "challenger_review_calls": challenger_calls,
            "human_review_calls": human_review_calls,
            "routine_call_percentage": routine_pct,
            "specialist_percentage": specialist_pct,
            "challenger_percentage": challenger_pct,
            "average_stage_durations_ms": avg_stage_durations,
            "premium_model_calls_avoided": {
                "estimated_calls_avoided": premium_calls_avoided,
                "actual_premium_calls_used": actual_premium_calls,
                "ungoverned_baseline_premium_calls": ungoverned_premium_calls,
                "methodology_label": (
                    "Workflow-derived estimate comparing governed routing (AURA_DEEP + AURA_CHALLENGER invoked "
                    "only when policy-triggered) against an ungoverned baseline invoking both premium models on all calls. "
                    "No financial savings are claimed without explicit unit-cost assumptions."
                ),
            },
            "risk_flag_distribution": risk_flag_dist,
            "risk_level_distribution": risk_level_dist,
            "issue_category_distribution": issue_cat_dist,
            "deflection_signal_distribution": deflection_dist,
            "route_distribution": route_dist,
        }

    def simulate_model_upgrade(
        self,
        production_model_id: str,
        candidate_model_id: str,
        sample_size: int = 20,
        sample_filter: str | None = None,
    ) -> dict[str, Any]:
        """Compare stored production results against synthetic candidate-model results."""
        prod_model = self.repo.get_validated_model(production_model_id)
        cand_model = self.repo.get_validated_model(candidate_model_id)
        provider = get_llm_provider()

        safe_sample_size = max(1, min(int(sample_size), 100))

        with get_db_connection(self.repo.db_path) as conn:
            query = """
                SELECT c.call_id, c.transcript, fr.final_result_json, fp.issue_category
                FROM calls c
                JOIN final_results fr ON c.call_id = fr.call_id
                LEFT JOIN first_pass_results fp ON c.call_id = fp.call_id
                WHERE 1=1
            """
            params: list[Any] = []
            if sample_filter and sample_filter.strip() and sample_filter.lower() != "all":
                query += " AND (LOWER(fp.issue_category) = LOWER(?) OR LOWER(fr.final_risk_level) = LOWER(?))"
                params.extend([sample_filter.strip(), sample_filter.strip()])
            query += " ORDER BY c.call_id ASC LIMIT ?"
            params.append(safe_sample_size)
            rows = conn.execute(query, tuple(params)).fetchall()

        calls_compared = len(rows)
        if calls_compared == 0:
            return {
                "production_model": prod_model["model_id"],
                "candidate_model": cand_model["model_id"],
                "calls_compared": 0,
                "overall_agreement_score": 0.0,
                "field_level_agreement": {},
                "critical_disagreement_count": 0,
                "high_risk_disagreement_details": [],
                "recommendation": "insufficient_evidence",
                "recommendation_rules_explanation": (
                    "Fewer than 5 processed calls were available for comparison. Process a batch of calls before evaluating upgrades."
                ),
                "sample_limitations": "Zero processed calls matched the filter criteria in SQLite.",
                "governance_notice": "Candidate models are NEVER automatically approved for production by simulation.",
            }

        compared_fields = ["final_route", "final_risk_level", "final_resolution_status", "human_review_required"]
        field_matches = {f: 0 for f in compared_fields}
        critical_disagreements = 0
        high_risk_details: list[dict[str, Any]] = []

        for row in rows:
            cid = row["call_id"]
            transcript = row["transcript"]
            prod_res = json.loads(row["final_result_json"])
            cand_res = provider.run_candidate_model_analysis(cid, transcript, candidate_model_id)

            row_disagreements: list[str] = []
            for f in compared_fields:
                if prod_res.get(f) == cand_res.get(f):
                    field_matches[f] += 1
                else:
                    row_disagreements.append(f)

            # Check if disagreement is on a High/Critical risk call or changes human_review_required
            prod_risk = prod_res.get("final_risk_level", "Low")
            cand_risk = cand_res.get("final_risk_level", "Low")
            if row_disagreements and (
                prod_risk in ("High", "Critical")
                or cand_risk in ("High", "Critical")
                or prod_res.get("human_review_required") != cand_res.get("human_review_required")
            ):
                critical_disagreements += 1
                high_risk_details.append(
                    {
                        "call_id": cid,
                        "issue_category": row["issue_category"],
                        "disagreed_fields": row_disagreements,
                        "production_values": {k: prod_res.get(k) for k in row_disagreements},
                        "candidate_values": {k: cand_res.get(k) for k in row_disagreements},
                    }
                )

        field_agreement_pct = {
            f: round((field_matches[f] / calls_compared) * 100.0, 1) for f in compared_fields
        }
        overall_agreement = round(sum(field_agreement_pct.values()) / len(compared_fields), 1)

        # Apply governed recommendation rules
        if calls_compared < 5:
            recommendation = "insufficient_evidence"
            reason = (
                f"Sample size ({calls_compared} calls) is below the minimum 5-call governance threshold "
                "required for shadow evaluation conclusions."
            )
        elif critical_disagreements > max(2, int(calls_compared * 0.15)) or overall_agreement < 80.0:
            recommendation = "not_ready"
            reason = (
                f"Candidate exhibited {critical_disagreements} high-risk disagreements and {overall_agreement}% "
                "overall agreement (< 80% threshold). Model is not ready for canary traffic."
            )
        elif critical_disagreements == 0 and overall_agreement >= 92.0 and calls_compared >= 10:
            recommendation = "candidate_for_canary"
            reason = (
                f"Candidate achieved {overall_agreement}% field agreement with 0 critical risk disagreements across "
                f"{calls_compared} calls. Eligible for human-governed canary review (not production approval)."
            )
        else:
            recommendation = "continue_shadow_testing"
            reason = (
                f"Candidate achieved {overall_agreement}% field agreement with {critical_disagreements} critical "
                f"disagreement(s) across {calls_compared} calls. Continue offline shadow testing to gather broader evidence."
            )

        return {
            "production_model": f"{prod_model['model_id']} (v{prod_model['model_version']})",
            "candidate_model": f"{cand_model['model_id']} (v{cand_model['model_version']})",
            "calls_compared": calls_compared,
            "overall_agreement_score": overall_agreement,
            "field_level_agreement": field_agreement_pct,
            "critical_disagreement_count": critical_disagreements,
            "high_risk_disagreement_details": high_risk_details,
            "recommendation": recommendation,
            "recommendation_rules_explanation": reason,
            "governance_rules_reference": {
                "insufficient_evidence": "calls_compared < 5",
                "not_ready": "overall_agreement < 80% or critical_disagreements > 15% of sample",
                "continue_shadow_testing": "overall_agreement >= 80% with minor/moderate disagreements",
                "candidate_for_canary": "calls_compared >= 10, overall_agreement >= 92%, and 0 critical disagreements",
            },
            "sample_limitations": (
                f"Evaluated on a synthetic sample of {calls_compared} calls. Shadow testing results are diagnostic "
                "and do NOT constitute production model approval."
            ),
            "governance_notice": "IMPORTANT: Candidate models are never approved for production automatically by AURA.",
        }
