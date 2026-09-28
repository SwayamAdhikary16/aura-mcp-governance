"""Tests for Excel/CSV validation, call ingestion, transcript sanitization, and synthetic data."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from aura.database import initialize_database
from aura.errors import AuraError, ErrorCode
from aura.excel_utils import write_excel_sheets
from aura.ingestion_service import IngestionService, sanitize_transcript
from aura.repositories import AuraRepository
from scripts.generate_synthetic_data import generate_dataset


class TestIngestionAndSyntheticData(unittest.TestCase):
    """Verify Excel validation rules, partial row loading, and synthetic data generation."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.db_path = self.tmp_dir / "test_ingest.db"
        initialize_database(db_path=self.db_path, reset=True)
        self.repo = AuraRepository(db_path=self.db_path)
        self.service = IngestionService(self.repo, max_transcript_length=500)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_deterministic_synthetic_dataset_has_over_100_calls(self) -> None:
        rows, expected = generate_dataset(total_calls=105)
        self.assertEqual(len(rows), 105)
        self.assertEqual(len(expected), 105)
        scenarios = {e["scenario_name"] for e in expected}
        self.assertEqual(len(scenarios), 21)

    def test_missing_required_columns_rejected(self) -> None:
        bad_xlsx = self.tmp_dir / "missing_cols.xlsx"
        write_excel_sheets({"Sheet1": [{"wrong_col": "123", "notes": "abc"}]}, bad_xlsx)
        summary, valid_rows = self.service.validate_file(bad_xlsx)
        self.assertFalse(summary.valid_file)
        self.assertEqual(len(valid_rows), 0)
        self.assertIn("call_id", summary.missing_required_columns)
        self.assertIn("transcript", summary.missing_required_columns)

        with self.assertRaises(AuraError) as ctx:
            self.service.ingest_validated_calls(bad_xlsx)
        self.assertEqual(ctx.exception.structured.error_code, ErrorCode.MISSING_EXCEL_COLUMNS.value)

    def test_partial_valid_rows_loaded_when_some_rows_fail(self) -> None:
        mixed_xlsx = self.tmp_dir / "mixed_calls.xlsx"
        rows = [
            {"call_id": "VALID-01", "transcript": "[00:05] Customer: Valid synthetic call 1."},
            {"call_id": "VALID-01", "transcript": "[00:05] Customer: Duplicate call ID in file."},
            {"call_id": "EMPTY-02", "transcript": ""},
            {"call_id": "TOO-LONG-03", "transcript": "X" * 600},
            {"call_id": "VALID-04", "transcript": "[00:05] Customer: Valid synthetic call 4."},
        ]
        write_excel_sheets({"Calls": rows}, mixed_xlsx)
        ing_res = self.service.ingest_validated_calls(mixed_xlsx, replace_existing=False)
        self.assertEqual(ing_res["inserted_count"], 2)
        self.assertEqual(ing_res["rejected_count"], 3)
        self.assertTrue(self.repo.call_exists("VALID-01"))
        self.assertTrue(self.repo.call_exists("VALID-04"))
        self.assertFalse(self.repo.call_exists("EMPTY-02"))

    def test_transcript_sanitization(self) -> None:
        dirty = "<script>alert('xss')</script> Customer SSN 123-45-6789 inquiring on balance."
        cleaned = sanitize_transcript(dirty)
        self.assertNotIn("<script>", cleaned)
        self.assertNotIn("123-45-6789", cleaned)
        self.assertIn("[REDACTED-SYNTHETIC-ID]", cleaned)


if __name__ == "__main__":
    unittest.main()
