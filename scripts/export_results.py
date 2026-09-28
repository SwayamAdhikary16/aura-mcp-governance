"""Export AURA processed results from SQLite into an 8-sheet governance Excel workbook.

Required sheets (Section 7):
1. Final Results
2. First Pass
3. Specialist Results
4. Challenger Results
5. MCP Activity
6. Audit Log
7. Portfolio Summary
8. Failed Calls
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aura.database import get_db_connection  # noqa: E402
from aura.excel_utils import write_excel_sheets  # noqa: E402
from aura.metrics_service import MetricsService  # noqa: E402
from aura.repositories import AuraRepository  # noqa: E402


def build_export_workbook_bytes(
    db_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> bytes:
    """Query SQLite system of record and build the 8-sheet Excel workbook."""
    repo = AuraRepository(db_path=db_path)
    metrics_svc = MetricsService(repo)

    with get_db_connection(db_path) as conn:
        final_rows = [dict(r) for r in conn.execute("SELECT * FROM final_results ORDER BY call_id ASC").fetchall()]
        fp_rows = [dict(r) for r in conn.execute("SELECT * FROM first_pass_results ORDER BY call_id ASC").fetchall()]
        spec_rows = [dict(r) for r in conn.execute("SELECT * FROM specialist_results ORDER BY call_id ASC").fetchall()]
        chal_rows = [dict(r) for r in conn.execute("SELECT * FROM challenger_results ORDER BY call_id ASC").fetchall()]
        mcp_rows = [dict(r) for r in conn.execute("SELECT * FROM mcp_activity ORDER BY rowid DESC LIMIT 1000").fetchall()]
        audit_rows = [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY rowid DESC LIMIT 1000").fetchall()]
        failed_rows = [
            dict(r)
            for r in conn.execute(
                "SELECT call_id, source_file, processing_status, current_stage, error_code, error_message, updated_at "
                "FROM calls WHERE processing_status = 'Failed' ORDER BY call_id ASC"
            ).fetchall()
        ]

    summary = metrics_svc.get_portfolio_summary()
    avoided = summary.get("premium_model_calls_avoided", {})
    portfolio_sheet_rows: list[dict[str, Any]] = [
        {"metric": "Total Calls Ingested", "value": summary["total_calls_ingested"]},
        {"metric": "Total Calls Processed", "value": summary["total_calls_processed"]},
        {"metric": "Successful Calls", "value": summary["successful_calls"]},
        {"metric": "Failed Calls", "value": summary["failed_calls"]},
        {"metric": "First-Pass-Only (Routine) Calls", "value": summary["first_pass_only_calls"]},
        {"metric": "Specialist Review Calls", "value": summary["specialist_review_calls"]},
        {"metric": "Challenger Review Calls", "value": summary["challenger_review_calls"]},
        {"metric": "Human Review Required Calls", "value": summary["human_review_calls"]},
        {"metric": "Routine Call Percentage (%)", "value": summary["routine_call_percentage"]},
        {"metric": "Specialist Call Percentage (%)", "value": summary["specialist_percentage"]},
        {"metric": "Challenger Call Percentage (%)", "value": summary["challenger_percentage"]},
        {
            "metric": "Estimated Premium Model Calls Avoided (Workflow-Derived)",
            "value": avoided.get("estimated_calls_avoided", 0),
        },
        {"metric": "Methodology Note", "value": avoided.get("methodology_label", "")},
    ]

    sheets: dict[str, list[dict[str, Any]]] = {
        "Final Results": final_rows or [{"info": "No final results recorded yet."}],
        "First Pass": fp_rows or [{"info": "No first-pass results recorded yet."}],
        "Specialist Results": spec_rows or [{"info": "No specialist results recorded yet."}],
        "Challenger Results": chal_rows or [{"info": "No challenger results recorded yet."}],
        "MCP Activity": mcp_rows or [{"info": "No MCP activity recorded yet."}],
        "Audit Log": audit_rows or [{"info": "No audit events recorded yet."}],
        "Portfolio Summary": portfolio_sheet_rows,
        "Failed Calls": failed_rows or [{"info": "Zero failed calls."}],
    }

    target: str | Path | io.BytesIO = output_path if output_path else io.BytesIO()
    return write_excel_sheets(sheets, target=target)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export AURA SQLite results to multi-sheet Excel workbook.")
    parser.add_argument("--db-path", type=str, default=None, help="Optional SQLite DB path.")
    parser.add_argument(
        "--output",
        type=str,
        default=str(PROJECT_ROOT / "data" / "aura_exported_results.xlsx"),
        help="Target Excel workbook path.",
    )
    args = parser.parse_args()

    build_export_workbook_bytes(db_path=args.db_path, output_path=args.output)
    sys.stderr.write(f"[AURA EXPORT] Exported 8-sheet governance workbook to: {args.output}\n")


if __name__ == "__main__":
    main()
