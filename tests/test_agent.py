"""Tests for AuraAgent modes, boundary declining, bad-input recovery, and max-turn enforcement (Section 25)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent import AuraAgent
from aura.database import initialize_database
from mcp_client import AuraMCPClient


class TestAuraAgent(unittest.TestCase):
    """Verify Autonomous Agent Mode, Deterministic Demo Mode, out-of-scope boundaries, and bad-input recovery."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_agent.db"
        initialize_database(db_path=self.db_path, reset=True)
        self.client = AuraMCPClient(transport="stdio", db_path=self.db_path)
        self.agent = AuraAgent(mcp_client=self.client, db_path=self.db_path, max_turns=8)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_agent_boundary_declines_out_of_scope_question(self) -> None:
        """Agent must decline out-of-scope requests without inventing tool outputs."""
        res = self.agent.run_request(
            user_request="What is the weather forecast and stock price of Bitcoin today?",
            mode="agent",
        )
        self.assertEqual(res["status"], "declined_out_of_scope")
        self.assertEqual(len(res["tool_calls"]), 0)
        self.assertIn("outside AURA's governed", res["final_response"])

    def test_agent_mode_autonomous_call_review(self) -> None:
        """Agent mode must discover tools, select review_call/explain_decision/get_audit_record, and return a grounded summary."""
        res = self.agent.run_request(
            user_request="Review this call and explain the governance decision.",
            call_id="SYN-AGENT-01",
            transcript=(
                "[00:05] Agent: Customer Support.\n"
                "[00:12] Customer: I see an unauthorized fraud charge of $620 on my card!\n"
                "[00:25] Agent: Locking your card and opening a fraud claim now."
            ),
            mode="agent",
        )
        self.assertEqual(res["status"], "completed")
        self.assertIn("Autonomous MCP Agent Mode", res["operating_mode"])
        self.assertLessEqual(res["turn_count"], 8)
        called_names = [c["tool_name"] for c in res["tool_calls"]]
        self.assertIn("review_call", called_names)
        self.assertIn("explain_decision", called_names)

    def test_agent_bad_input_recovery(self) -> None:
        """Agent must handle a structured empty-transcript error from MCP and recover cleanly on the next turn."""
        res = self.agent.run_request(
            user_request="Review this call and test bad input recovery.",
            call_id="SYN-AGENT-RECOVER",
            transcript=(
                "[00:05] Agent: Welcome.\n"
                "[00:12] Customer: When is my payment due date?\n"
                "[00:22] Agent: Your due date is the 15th."
            ),
            mode="agent",
            simulate_bad_input_first=True,
        )
        self.assertEqual(res["status"], "completed")
        self.assertGreaterEqual(len(res["tool_calls"]), 2)
        first_call = res["tool_calls"][0]
        self.assertEqual(first_call["status"], "Failed")
        second_call = res["tool_calls"][1]
        self.assertEqual(second_call["tool_name"], "review_call")
        self.assertEqual(second_call["status"], "Completed")

    def test_deterministic_demo_mode_labeled_transparently(self) -> None:
        """Deterministic demo mode must execute the governed sequence and clearly label itself as offline deterministic demonstration."""
        res = self.agent.run_request(
            user_request="Run governed demo workflow for this call.",
            call_id="SYN-DEMO-01",
            transcript=(
                "[00:05] Agent: Billing Desk.\n"
                "[00:14] Customer: I am disputing a $310 merchant charge for undelivered merchandise.\n"
                "[00:30] Agent: I have opened a merchant billing dispute."
            ),
            mode="deterministic_demo",
        )
        self.assertEqual(res["status"], "completed")
        self.assertIn("Offline deterministic demonstration", res["operating_mode"])
        self.assertGreaterEqual(len(res["resources_used"]), 2)
        self.assertGreaterEqual(len(res["prompts_retrieved"]), 1)
        self.assertGreaterEqual(len(res["tool_calls"]), 3)


if __name__ == "__main__":
    unittest.main()
