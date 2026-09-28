"""Tests for MCP 2.0 tool registration, historical context, portfolio summary, and model upgrade simulation (Section 25)."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from aura.database import initialize_database
from aura.mcp_server import create_aura_mcp_server
from aura.tools import (
    compare_decisions,
    explain_decision,
    find_similar_calls,
    get_audit_record,
    portfolio_summary,
    review_call,
    simulate_model_upgrade,
)


class TestMCPTools(unittest.TestCase):
    """Verify MCP 2.0 tool schemas, docstrings, and governed tool execution."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_tools.db"
        initialize_database(db_path=self.db_path, reset=True)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_mcp_tool_registration_and_snake_case_schema(self) -> None:
        """All 10 MCP tools must be registered with snake_case input_schema and rich docstrings."""
        server = create_aura_mcp_server()
        tools = asyncio.run(server.list_tools())
        expected_tools = {
            "review_call",
            "review_batch",
            "find_similar_calls",
            "explain_decision",
            "compare_decisions",
            "get_audit_record",
            "portfolio_summary",
            "simulate_model_upgrade",
            "validate_input_file",
            "ingest_validated_calls",
        }
        registered_names = {t.name for t in tools}
        self.assertEqual(expected_tools, registered_names)

        for t in tools:
            self.assertTrue(t.description and len(t.description) > 80, f"Tool {t.name} lacks descriptive docstring")
            schema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", {})
            props = schema.get("properties", {})
            for prop_name in props:
                self.assertEqual(prop_name, prop_name.lower(), f"Non-snake_case property {prop_name} in {t.name}")

    def test_find_similar_calls_never_returns_self(self) -> None:
        """Historical context retrieval must never return a call as its own comparator."""
        t1 = (
            "[00:05] Agent: Welcome to Support.\n"
            "[00:12] Customer: I want to check my minimum payment due date and confirm auto-pay.\n"
            "[00:25] Agent: Your due date is the 15th and auto-pay is active.\n"
            "[00:35] Customer: Thank you!"
        )
        t2 = (
            "[00:05] Agent: Welcome to Support.\n"
            "[00:14] Customer: Can you tell me when my payment due date is for this billing cycle?\n"
            "[00:28] Agent: Your payment is due on the 15th.\n"
            "[00:36] Customer: Great, thanks!"
        )
        r1 = review_call(call_id="SYN-HIST-01", transcript=t1, db_path=self.db_path)
        review_call(call_id="SYN-HIST-02", transcript=t2, db_path=self.db_path)
        cat = r1["final_decision"]["issue_category"]

        sim = find_similar_calls(call_id="SYN-HIST-01", issue_category=cat, db_path=self.db_path)
        self.assertEqual(sim["call_id"], "SYN-HIST-01")
        returned_ids = sim["selected_anonymized_call_ids"]
        self.assertNotIn("HIST-T-01", returned_ids)
        self.assertGreaterEqual(sim["similar_call_count"], 1)

    def test_portfolio_summary_and_audit_tools(self) -> None:
        """Portfolio summary, explain_decision, compare_decisions, and get_audit_record must work end-to-end."""
        transcript = (
            "[00:04] Agent: Thank you for calling.\n"
            "[00:12] Customer: I noticed an unauthorized fraud charge of $540 on my card that I never made.\n"
            "[00:28] Agent: I am locking your card and opening a formal fraud investigation right away.\n"
            "[00:45] Customer: Please send me the provisional credit timeline."
        )
        rev = review_call(call_id="SYN-PORT-01", transcript=transcript, db_path=self.db_path)
        self.assertIn(rev["processing_status"], ("Completed", "Human Review Required"))

        comp = compare_decisions(call_id="SYN-PORT-01", db_path=self.db_path)
        self.assertIn("final_disposition", comp)

        expl = explain_decision(call_id="SYN-PORT-01", db_path=self.db_path)
        self.assertTrue(expl["human_review_required"])

        aud = get_audit_record(call_id="SYN-PORT-01", db_path=self.db_path)
        self.assertGreaterEqual(len(aud["ordered_audit_events"]), 5)

        summary = portfolio_summary(db_path=self.db_path)
        self.assertGreaterEqual(summary["total_calls_processed"], 1)
        self.assertIn("premium_model_calls_avoided", summary)

    def test_model_upgrade_simulation_and_disabled_model_rejection(self) -> None:
        """simulate_model_upgrade must compare candidate vs production and block disabled models."""
        transcript = (
            "[00:05] Agent: Thank you for calling.\n"
            "[00:15] Customer: I am disputing a $220 merchant charge because the item arrived broken.\n"
            "[00:30] Agent: I will file a merchant billing dispute for $220."
        )
        review_call(call_id="SYN-SIM-01", transcript=transcript, db_path=self.db_path)

        sim = simulate_model_upgrade(
            production_model_id="AURA_DEEP",
            candidate_model_id="AURA_CANDIDATE_V2",
            sample_size=5,
            db_path=self.db_path,
        )
        self.assertIn("overall_agreement_score", sim)
        self.assertIn("recommendation", sim)

        # Disabled model must be rejected with AURA_ERR_DISABLED_MODEL
        disabled_sim = simulate_model_upgrade(
            production_model_id="AURA_DEEP",
            candidate_model_id="AURA_LEGACY_DISABLED",
            sample_size=5,
            db_path=self.db_path,
        )
        self.assertEqual(disabled_sim["status"], "error")
        self.assertEqual(disabled_sim["error"]["error_code"], "AURA_ERR_DISABLED_MODEL")


if __name__ == "__main__":
    unittest.main()
