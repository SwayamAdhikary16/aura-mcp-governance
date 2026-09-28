"""Tests for MCP prompts, stage prompts, and Pydantic output schemas (Section 25)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from aura.database import get_db_connection, initialize_database
from aura.prompt_templates import PROMPT_CATALOG_METADATA, render_mcp_prompt
from aura.prompts import (
    challenger_system_prompt,
    challenger_user_prompt,
    first_pass_system_prompt,
    first_pass_user_prompt,
    single_analysis_system_prompt,
    single_analysis_user_prompt,
    split_analysis_system_prompt,
    split_analysis_user_prompt,
)
from aura.schemas import (
    ChallengerAnalysisResult,
    FirstPassResult,
    RoutineAnalysisResult,
    SpecialistAnalysisResult,
)


class TestPromptsAndSchemas(unittest.TestCase):
    """Verify prompt registration, rendering, activity logging, and Pydantic schemas."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_prompts.db"
        initialize_database(db_path=self.db_path, reset=True)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_mcp_prompts_catalog_and_rendering(self) -> None:
        """All 5 MCP prompts must render cleanly and log PROMPT RETRIEVAL activity."""
        expected_names = {
            "review_customer_call",
            "investigate_high_risk_call",
            "explain_aura_decision",
            "summarize_portfolio_impact",
            "compare_candidate_model",
        }
        actual_names = {item["name"] for item in PROMPT_CATALOG_METADATA}
        self.assertEqual(expected_names, actual_names)

        for name in expected_names:
            rendered = render_mcp_prompt(
                prompt_name=name,
                arguments={"call_id": "SYN-CALL-0001", "transcript": "[00:05] Agent: Hello"},
                db_path=self.db_path,
            )
            self.assertTrue(len(rendered) > 30)

        with get_db_connection(self.db_path) as conn:
            cnt = conn.execute(
                "SELECT COUNT(*) AS cnt FROM mcp_activity WHERE activity_type = 'PROMPT RETRIEVAL'"
            ).fetchone()["cnt"]
            self.assertEqual(cnt, 5)

    def test_stage_prompt_functions(self) -> None:
        """All 8 internal stage prompt builders must return non-empty governed strings."""
        self.assertIn("AURA_FAST", first_pass_system_prompt())
        self.assertIn("SYN-01", first_pass_user_prompt("SYN-01", "Transcript text", "Goal"))
        self.assertIn("Routine Call Analyst", single_analysis_system_prompt())
        self.assertIn("SYN-01", single_analysis_user_prompt("SYN-01", "Transcript", "{}"))
        self.assertIn("AURA_DEEP", split_analysis_system_prompt())
        self.assertIn("SYN-01", split_analysis_user_prompt("SYN-01", "Transcript", "{}", "{}"))
        self.assertIn("AURA_CHALLENGER", challenger_system_prompt())
        self.assertIn("SYN-01", challenger_user_prompt("SYN-01", "Transcript", "{}", "{}"))

    def test_pydantic_schema_validation(self) -> None:
        """Pydantic schemas must validate well-formed payloads and enforce bounds."""
        fp = FirstPassResult(
            call_id="SYN-01",
            summary="Routine payment inquiry resolved.",
            complexity=1,
            analysis_confidence=0.95,
            primary_issue="Payment inquiry",
            issue_category="Billing & Payments",
            issue_subcategory="Due Date",
            interaction_origin="First-Time Inquiry",
            sentiment_progression="Neutral -> Satisfied",
            dispute_flag=False,
            fraud_flag=False,
            threat_flag=False,
            self_harm_flag=False,
            customer_distress_flag=False,
            compliance_flag=False,
            escalation_flag=False,
            repeat_contact_risk_flag=False,
            deflection_candidate=True,
            needs_deeper_analysis=False,
            resolved_in_call_flag=True,
        )
        self.assertEqual(fp.complexity, 1)

        routine = RoutineAnalysisResult(
            call_id="SYN-01",
            analysis_type="routine_analysis",
            resolution_status="Resolved",
            first_contact_resolution=True,
            call_avoidable=True,
            deflection_eligible=True,
            deflection_channel="Mobile App",
            review_required=False,
            analysis_confidence=0.94,
            coaching_note="Clear next steps.",
        )
        self.assertTrue(routine.deflection_eligible)

        spec = SpecialistAnalysisResult(
            call_id="SYN-02",
            analysis_type="specialist_analysis",
            resolution_status="Escalated",
            risk_level="High",
            first_contact_resolution=False,
            call_avoidable=False,
            deflection_eligible=False,
            deflection_channel="None - Live Agent Required",
            review_required=True,
            analysis_confidence=0.90,
            process_gap_identified=True,
            knowledge_gap_identified=False,
            root_cause="Unauthorized charge claim",
            complaint_analysis="Customer upset about card compromise.",
            dispute_analysis="Formal fraud claim opened.",
            fraud_analysis="Card reissued.",
            compliance_analysis="Analytical indicator only; not a legal determination.",
            recommended_actions=["Follow fraud script"],
        )
        self.assertEqual(spec.risk_level, "High")

        chal = ChallengerAnalysisResult(
            call_id="SYN-02",
            challenger_agreement=True,
            review_required=True,
            analysis_confidence=0.92,
            final_disposition="Confirmed Primary Decision",
            challenged_resolution_status="Escalated",
            challenged_risk_level="High",
            resolution_challenge_note="Concur with specialist fraud escalation.",
            escalation_challenge_note="Escalation appropriate.",
            sentiment_challenge_note="Verified sentiment.",
            interaction_origin_challenge_note="Verified origin.",
            agent_performance_challenge_note="Agent followed protocol.",
            deflection_challenge_note="Live agent required.",
            disagreement_fields=[],
            disagreement_rationale="No material disagreement identified.",
        )
        self.assertTrue(chal.challenger_agreement)


if __name__ == "__main__":
    unittest.main()
