"""Tests for the 17-step governed AURA workflow, error fallbacks, and end-to-end smoke test (Section 25)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aura.database import initialize_database
from aura.errors import AuraError, ErrorCode
from aura.llm_provider.mock_provider import MockLLMProvider
from aura.processing_service import ProcessingService
from aura.repositories import AuraRepository
from aura.schemas import FirstPassResult
from mcp_client import AuraMCPClient


class TestGovernedWorkflow(unittest.TestCase):
    """Verify routine, complex, high-risk, JSON repair, challenger fallback, audit, and E2E flows."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_workflow.db"
        initialize_database(db_path=self.db_path, reset=True)
        self.repo = AuraRepository(db_path=self.db_path)
        self.service = ProcessingService(self.repo)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_happy_path_routine_call_workflow(self) -> None:
        """Routine low-risk call must complete via routine_analysis without specialist or challenger."""
        transcript = (
            "[00:05] Agent: Thank you for calling Customer Care.\n"
            "[00:12] Customer: Hi, I just wanted to check when my next payment due date is.\n"
            "[00:24] Agent: Your payment due date is the 18th of this month, and your minimum due is $35.\n"
            "[00:35] Customer: Perfect, I will pay it in the mobile app today. Thank you!"
        )
        res = self.service.review_call(call_id="SYN-WF-ROUTINE", transcript=transcript)
        self.assertEqual(res.processing_status, "Completed")
        self.assertEqual(res.route_selected, "routine_analysis")
        self.assertFalse(res.specialist_used)
        self.assertFalse(res.challenger_used)
        self.assertFalse(res.human_review_required)

    def test_complex_call_specialist_workflow(self) -> None:
        """Complex billing/promo issue must route to specialist analysis."""
        transcript = (
            "[00:04] Agent: Welcome to Promotional Financing Support.\n"
            "[00:15] Customer: My 12-month promotional deferred interest plan expired and I was charged $410 in retro interest. "
            "I made payments every month and need a breakdown of how my payments were allocated across two promotional balances.\n"
            "[01:10] Agent: Let me review the multi-promo payment allocation ledger across both deferred-interest plans."
        )
        res = self.service.review_call(call_id="SYN-WF-COMPLEX", transcript=transcript)
        self.assertEqual(res.processing_status, "Completed")
        self.assertTrue(res.specialist_used)
        self.assertEqual(res.route_selected, "specialist_analysis")

    def test_high_risk_challenger_and_human_review_workflow(self) -> None:
        """High-risk fraud or safety call must trigger specialist + challenger + mandatory human review."""
        transcript = (
            "[00:05] Agent: Card Services, how can I help?\n"
            "[00:14] Customer: Someone stole my identity and made three unauthorized fraud charges totaling $1,450! "
            "Also I never consented to the credit protection fee and I am reporting this to the CFPB!\n"
            "[00:45] Agent: I am locking your account immediately and opening a formal fraud and compliance escalation."
        )
        res = self.service.review_call(call_id="SYN-WF-HIGHRISK", transcript=transcript)
        self.assertIn(res.processing_status, ("Completed", "Human Review Required"))
        self.assertEqual(res.route_selected, "specialist_analysis")
        self.assertTrue(res.specialist_used)
        self.assertTrue(res.challenger_used)
        self.assertTrue(res.human_review_required)
        self.assertIn(res.final_decision["final_risk_level"], ("High", "Critical"))

    def test_invalid_llm_json_single_repair_and_failure(self) -> None:
        """Provider must recover from 1 broken JSON response via repair, and fail with INVALID_LLM_JSON if unrepairable."""
        provider = MockLLMProvider()
        valid_raw = provider._raw_first_pass("SYN-JSON-01", "[00:05] Agent: Hello\n[00:10] Customer: Payment due date?")
        broken_with_fence = f"```json\n{valid_raw}\n``` trailing garbage"

        retries: list[str] = []
        repaired_obj, was_repaired = provider.validate_with_single_repair(
            raw_json=broken_with_fence,
            schema_cls=FirstPassResult,
            call_id="SYN-JSON-01",
            on_retry_callback=lambda s, e: retries.append(s),
        )
        self.assertTrue(was_repaired)
        self.assertEqual(len(retries), 1)
        self.assertEqual(repaired_obj.call_id, "SYN-JSON-01")

        # Unrepairable JSON must raise AuraError(INVALID_LLM_JSON)
        with self.assertRaises(AuraError) as ctx:
            provider.validate_with_single_repair(
                raw_json="unrepairable non-json text without braces",
                schema_cls=FirstPassResult,
                call_id="SYN-JSON-FAIL",
            )
        self.assertEqual(ctx.exception.structured.error_code, ErrorCode.INVALID_LLM_JSON)
        self.assertTrue(ctx.exception.structured.human_review_required)

    def test_challenger_failure_provisional_fallback(self) -> None:
        """Section 22.H: If challenger fails, retain primary result as provisional and require human review."""
        transcript = (
            "[00:05] Agent: Support desk.\n"
            "[00:12] Customer: I see an unauthorized fraud transaction of $800 on my statement!\n"
            "[00:30] Agent: Opening fraud claim now."
        )
        with patch.object(
            MockLLMProvider,
            "run_challenger_analysis",
            side_effect=AuraError(
                error_code=ErrorCode.CHALLENGER_FAILURE,
                user_message="Simulated challenger timeout.",
                technical_message="Challenger timed out during test.",
                human_review_required=True,
            ),
        ):
            res = self.service.review_call(call_id="SYN-CHAL-FALLBACK", transcript=transcript)
            self.assertIn(res.processing_status, ("Completed", "Human Review Required"))
            self.assertTrue(res.human_review_required)
            self.assertTrue(res.final_decision["provisional_status"])

    def test_audit_completeness_and_end_to_end_smoke(self) -> None:
        """Every processed call must record complete audit and MCP activity trails via AuraMCPClient."""
        client = AuraMCPClient(transport="stdio", db_path=self.db_path)

        resources = client.list_resources()
        self.assertGreaterEqual(len(resources), 8)

        prompts = client.list_prompts()
        self.assertEqual(len(prompts), 5)

        tools = client.list_tools()
        self.assertGreaterEqual(len(tools), 10)

        out = client.call_tool(
            "review_call",
            {
                "call_id": "SYN-SMOKE-01",
                "transcript": (
                    "[00:05] Agent: Hello, thank you for calling.\n"
                    "[00:12] Customer: I am calling to dispute a $195 charge from a merchant that double billed me.\n"
                    "[00:28] Agent: I have initiated a merchant billing dispute for $195."
                ),
            },
        )
        self.assertIn(out["processing_status"], ("Completed", "Human Review Required"))

        audit_out = client.call_tool("get_audit_record", {"call_id": "SYN-SMOKE-01"})
        self.assertGreaterEqual(len(audit_out["ordered_audit_events"]), 6)

        for ev in audit_out["ordered_audit_events"]:
            self.assertTrue(ev["correlation_id"])
            self.assertEqual(ev["call_id"], "SYN-SMOKE-01")
            self.assertIsNotNone(ev["duration_ms"])


if __name__ == "__main__":
    unittest.main()
