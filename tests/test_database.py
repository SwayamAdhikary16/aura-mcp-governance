"""Tests for AURA SQLite database initialization, schema, and repository layer."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from aura.database import get_db_connection, initialize_database
from aura.errors import AuraError, ErrorCode
from aura.repositories import AuraRepository


class TestDatabaseAndRepositories(unittest.TestCase):
    """Validate SQLite schema, seeded catalogs, and repository operations."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_aura.db"
        initialize_database(db_path=self.db_path, reset=True)
        self.repo = AuraRepository(db_path=self.db_path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_all_thirteen_tables_created(self) -> None:
        expected_tables = {
            "calls",
            "first_pass_results",
            "specialist_results",
            "challenger_results",
            "final_results",
            "model_catalog",
            "prompt_versions",
            "audit_log",
            "mcp_activity",
            "routing_policies",
            "governance_policies",
            "framework_resources",
            "processing_jobs",
        }
        with get_db_connection(self.db_path) as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        existing = {r["name"] for r in rows}
        self.assertTrue(expected_tables.issubset(existing))

    def test_seeded_model_catalog_and_validation(self) -> None:
        models = self.repo.get_model_catalog()
        model_ids = {m["model_id"] for m in models}
        self.assertIn("AURA_FAST", model_ids)
        self.assertIn("AURA_DEEP", model_ids)
        self.assertIn("AURA_CHALLENGER", model_ids)

        fast = self.repo.get_validated_model("AURA_FAST")
        self.assertEqual(fast["cost_tier"], "Low")
        self.assertEqual(fast["approval_status"], "Approved")

        with self.assertRaises(AuraError) as ctx_unknown:
            self.repo.get_validated_model("NON_EXISTENT_MODEL")
        self.assertEqual(ctx_unknown.exception.structured.error_code, ErrorCode.UNKNOWN_MODEL_ID.value)

        with self.assertRaises(AuraError) as ctx_disabled:
            self.repo.get_validated_model("AURA_LEGACY_DISABLED")
        self.assertEqual(ctx_disabled.exception.structured.error_code, ErrorCode.DISABLED_MODEL.value)

    def test_call_upsert_and_duplicate_protection(self) -> None:
        self.repo.upsert_call(
            call_id="CALL-DB-001",
            transcript="[00:05] Customer: Synthetic test transcript.",
            replace_existing=False,
        )
        call_row = self.repo.get_call("CALL-DB-001")
        self.assertEqual(call_row["call_id"], "CALL-DB-001")

        with self.assertRaises(AuraError) as ctx_dup:
            self.repo.upsert_call(
                call_id="CALL-DB-001",
                transcript="Duplicate transcript",
                replace_existing=False,
            )
        self.assertEqual(ctx_dup.exception.structured.error_code, ErrorCode.DUPLICATE_CALL_ID.value)

        with self.assertRaises(AuraError) as ctx_unk:
            self.repo.get_call("UNKNOWN-CALL-999")
        self.assertEqual(ctx_unk.exception.structured.error_code, ErrorCode.UNKNOWN_CALL_ID.value)


if __name__ == "__main__":
    unittest.main()
