"""Tests for AURA policy-driven Routing Engine and Challenger trigger evaluation."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from aura.database import get_db_connection, initialize_database
from aura.errors import AuraError, ErrorCode
from aura.repositories import AuraRepository
from aura.routing_engine import RoutingEngine
from aura.schemas import FirstPassResult, SpecialistAnalysisResult


class TestRoutingEngine(unittest.TestCase):
    """Verify routine, borderline complexity 3, specialist, and challenger routing rules."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_routing.db"
        initialize_database(db_path=self.db_path, reset=True)
        self.repo = AuraRepository(db_path=self.db_path)
        self.engine = RoutingEngine(self.repo)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make_fp(self, **overrides: object) -> FirstPassResult:
        base = {
            "call_id": "CALL-RT-1",
            "summary": "Routine call summary",
            "complexity": 1,
            "analysis_confidence": 0.94,
            "primary_issue": "Balance Inquiry",
            "issue_category": "Balance",
            "issue_subcategory": "Current Balance",
            "interaction_origin": "First-Time Inquiry",
        }
        base.update(overrides)
        return FirstPassResult(**base)  # type: ignore[arg-type]

    def test_routine_call_routes_to_routine_analysis(self) -> None:
        fp = self._make_fp(complexity=1, analysis_confidence=0.95)
        decision = self.engine.evaluate_routing(fp)
        self.assertEqual(decision.selected_route, "routine_analysis")
        self.assertFalse(decision.specialist_required)
        self.assertFalse(decision.challenger_required)

    def test_borderline_complexity_3_routes_according_to_flags(self) -> None:
        fp_clean = self._make_fp(complexity=3, analysis_confidence=0.88, resolved_in_call_flag=True)
        dec_clean = self.engine.evaluate_routing(fp_clean)
        self.assertEqual(dec_clean.selected_route, "routine_analysis")

        fp_flagged = self._make_fp(
            complexity=3,
            analysis_confidence=0.85,
            repeat_contact_risk_flag=True,
            needs_deeper_analysis=True,
        )
        dec_flagged = self.engine.evaluate_routing(fp_flagged)
        self.assertEqual(dec_flagged.selected_route, "specialist_analysis")
        self.assertTrue(dec_flagged.specialist_required)

    def test_high_risk_flags_trigger_specialist_and_challenger(self) -> None:
        fp_fraud = self._make_fp(complexity=5, fraud_flag=True, dispute_flag=True)
        dec = self.engine.evaluate_routing(fp_fraud)
        self.assertEqual(dec.selected_route, "specialist_analysis")
        self.assertTrue(dec.specialist_required)
        self.assertTrue(dec.challenger_required)

        fp_safety = self._make_fp(complexity=5, self_harm_flag=True)
        dec_safety = self.engine.evaluate_routing(fp_safety)
        self.assertTrue(dec_safety.human_review_precondition)
        self.assertTrue(dec_safety.challenger_required)

    def test_low_specialist_confidence_triggers_challenger(self) -> None:
        fp = self._make_fp(complexity=4, dispute_flag=True, analysis_confidence=0.85)
        initial = self.engine.evaluate_routing(fp)
        self.assertFalse(initial.challenger_required)

        low_conf_spec = SpecialistAnalysisResult(
            call_id=fp.call_id,
            resolution_status="Partially Resolved",
            first_contact_resolution=False,
            call_avoidable=True,
            deflection_eligible=False,
            deflection_channel="None",
            review_required=False,
            analysis_confidence=0.65,
            risk_level="Moderate",
            root_cause="Merchant Dispute",
            complaint_analysis="None",
            dispute_analysis="Disputed charge",
            fraud_analysis="None",
            compliance_analysis="None",
        )
        chal_needed, reasons = self.engine.evaluate_challenger_after_primary(fp, low_conf_spec, initial)
        self.assertTrue(chal_needed)
        self.assertTrue(any("below challenger threshold" in r for r in reasons))

    def test_missing_active_routing_policy_raises_controlled_error(self) -> None:
        with get_db_connection(self.db_path) as conn:
            conn.execute("UPDATE routing_policies SET active = 0")
        fp = self._make_fp()
        with self.assertRaises(AuraError) as ctx:
            self.engine.evaluate_routing(fp)
        self.assertEqual(ctx.exception.structured.error_code, ErrorCode.NO_ACTIVE_ROUTING_POLICY.value)


if __name__ == "__main__":
    unittest.main()
