"""Tests for AURA MCP Resource registration and read-only governance payloads."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from aura.database import initialize_database
from aura.resources import RESOURCE_METADATA, read_aura_resource
from mcp_client import AuraMCPClient


class TestMCPResources(unittest.TestCase):
    """Verify all 8 required MCP resources are registered and return valid governance data."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_resources.db"
        initialize_database(db_path=self.db_path, reset=True)
        self.client = AuraMCPClient(db_path=self.db_path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_all_eight_resources_registered_and_discoverable(self) -> None:
        discovered = self.client.list_resources()
        uris = {r["uri"] for r in discovered}
        expected_uris = {
            "aura://model-catalog",
            "aura://routing-policy",
            "aura://challenger-policy",
            "aura://quality-framework",
            "aura://compliance-framework",
            "aura://output-schema",
            "aura://prompt-catalog",
            "aura://portfolio-summary",
        }
        self.assertEqual(len(RESOURCE_METADATA), 8)
        self.assertTrue(expected_uris.issubset(uris))

    def test_quality_framework_has_no_duplicate_dimensions(self) -> None:
        qf = read_aura_resource("aura://quality-framework", db_path=self.db_path)
        dims = [d["name"] for d in qf.get("dimensions", [])]
        self.assertEqual(len(dims), 5)
        self.assertEqual(len(dims), len(set(dims)))
        self.assertIn("Next Step Clarity", dims)
        self.assertIn("Empathy and Tone", dims)

    def test_compliance_framework_contains_legal_disclaimer(self) -> None:
        cf = read_aura_resource("aura://compliance-framework", db_path=self.db_path)
        disclaimer = cf.get("legal_disclaimer", "").lower()
        self.assertIn("analytical indicators", disclaimer)
        self.assertIn("not", disclaimer)
        self.assertIn("legal determinations", disclaimer)


if __name__ == "__main__":
    unittest.main()
