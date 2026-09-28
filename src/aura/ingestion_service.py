"""Excel and CSV validation, transcript sanitization, and call ingestion service for AURA."""

from __future__ import annotations

import csv
import html
import re
from pathlib import Path
from typing import Any

from aura.config import get_config
from aura.errors import AuraError, ErrorCode
from aura.excel_utils import read_excel_records
from aura.repositories import AuraRepository
from aura.schemas import FileValidationSummary, RowValidationError


REQUIRED_COLUMNS = ("call_id", "transcript")
OPTIONAL_COLUMNS = (
    "as_of_date",
    "expected_intent",
    "expected_complexity",
    "expected_risk",
    "expected_route",
    "expected_challenger",
    "source_system",
    "metadata_json",
)


def sanitize_transcript(raw_text: str) -> str:
    """Sanitize transcript text for safe storage and UI display.

    - Removes control characters (except newlines/tabs)
    - Escapes HTML/script injection tags
    - Masks accidental 16-digit card-like or 9-digit SSN-like patterns
    """
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", raw_text)
    cleaned = re.sub(r"<\s*script[^>]*>.*?<\s*/\s*script\s*>", "[REDACTED_SCRIPT]", cleaned, flags=re.I | re.S)
    cleaned = html.escape(cleaned, quote=False)
    # Redact any accidental SSN-like or 16-digit card-like sequences
    cleaned = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED-SYNTHETIC-ID]", cleaned)
    cleaned = re.sub(r"\b(?:\d{4}[-\s]?){3}\d{4}\b", "[REDACTED-SYNTHETIC-CARD]", cleaned)
    return cleaned.strip()


class IngestionService:
    """Validates uploaded Excel/CSV files and ingests valid synthetic calls into SQLite."""

    def __init__(self, repo: AuraRepository, max_transcript_length: int | None = None) -> None:
        self.repo = repo
        self.max_length = max_transcript_length or get_config().max_transcript_length

    def _load_file_records(self, file_path: str | Path) -> tuple[list[str], list[dict[str, Any]]]:
        path = Path(file_path)
        if not path.exists():
            raise AuraError(
                error_code=ErrorCode.INVALID_FILE_TYPE,
                user_message=f"Input file '{path.name}' does not exist.",
                technical_message=f"File not found at {path}",
            )
        suffix = path.suffix.lower()
        if suffix == ".xlsx":
            return read_excel_records(path)
        if suffix == ".csv":
            with path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                headers = [h.strip() for h in (reader.fieldnames or [])]
                records = [dict(r) for r in reader]
                return headers, records
        raise AuraError(
            error_code=ErrorCode.INVALID_FILE_TYPE,
            user_message=f"Unsupported file extension '{suffix}'. Please upload an .xlsx or .csv file.",
            technical_message=f"Invalid file extension: {suffix}",
        )

    def validate_file(
        self,
        file_path: str | Path,
        replace_existing: bool = False,
    ) -> tuple[FileValidationSummary, list[dict[str, Any]]]:
        """Validate an uploaded Excel or CSV file and return (FileValidationSummary, valid_records)."""
        headers, records = self._load_file_records(file_path)
        normalized_headers = [h.strip().lower() for h in headers]

        missing_cols = [c for c in REQUIRED_COLUMNS if c not in normalized_headers]
        if missing_cols:
            summary = FileValidationSummary(
                file_path=str(file_path),
                valid_file=False,
                total_rows=len(records),
                valid_rows=0,
                invalid_rows=len(records),
                duplicate_identifiers=[],
                missing_required_columns=missing_cols,
                row_level_errors=[
                    RowValidationError(
                        row_index=1,
                        call_id=None,
                        error_code=ErrorCode.MISSING_EXCEL_COLUMNS.value,
                        message=f"Missing required column(s): {', '.join(missing_cols)}",
                    )
                ],
            )
            return summary, []

        seen_call_ids: set[str] = set()
        duplicate_ids: list[str] = []
        row_errors: list[RowValidationError] = []
        valid_rows: list[dict[str, Any]] = []

        for idx, raw_row in enumerate(records, start=2):
            row = {str(k).strip().lower(): v for k, v in raw_row.items() if k is not None}
            raw_cid = row.get("call_id")
            call_id = str(raw_cid).strip() if raw_cid is not None else ""
            raw_transcript = row.get("transcript")
            transcript = str(raw_transcript).strip() if raw_transcript is not None else ""

            if not call_id or call_id.lower() == "none":
                row_errors.append(
                    RowValidationError(
                        row_index=idx,
                        call_id=None,
                        error_code=ErrorCode.VALIDATION_ERROR.value,
                        message="Missing or empty call_id.",
                    )
                )
                continue

            if call_id in seen_call_ids:
                duplicate_ids.append(call_id)
                row_errors.append(
                    RowValidationError(
                        row_index=idx,
                        call_id=call_id,
                        error_code=ErrorCode.DUPLICATE_CALL_ID.value,
                        message=f"Duplicate call_id '{call_id}' within uploaded file.",
                    )
                )
                continue

            if not replace_existing and self.repo.call_exists(call_id):
                duplicate_ids.append(call_id)
                row_errors.append(
                    RowValidationError(
                        row_index=idx,
                        call_id=call_id,
                        error_code=ErrorCode.DUPLICATE_CALL_ID.value,
                        message=f"call_id '{call_id}' already exists in SQLite (enable replace option to overwrite).",
                    )
                )
                continue

            if not transcript or transcript.lower() == "none":
                row_errors.append(
                    RowValidationError(
                        row_index=idx,
                        call_id=call_id,
                        error_code=ErrorCode.EMPTY_TRANSCRIPT.value,
                        message=f"Transcript for call_id '{call_id}' is empty.",
                    )
                )
                continue

            if len(transcript) > self.max_length:
                row_errors.append(
                    RowValidationError(
                        row_index=idx,
                        call_id=call_id,
                        error_code=ErrorCode.TRANSCRIPT_TOO_LONG.value,
                        message=(
                            f"Transcript length ({len(transcript)} chars) exceeds configured limit ({self.max_length} chars)."
                        ),
                    )
                )
                continue

            seen_call_ids.add(call_id)
            sanitized_text = sanitize_transcript(transcript)

            exp_comp = row.get("expected_complexity")
            parsed_comp = None
            if exp_comp not in (None, ""):
                try:
                    parsed_comp = int(float(str(exp_comp)))
                except ValueError:
                    parsed_comp = None

            exp_chal = row.get("expected_challenger")
            parsed_chal: bool | None = None
            if exp_chal not in (None, ""):
                parsed_chal = str(exp_chal).strip().lower() in ("true", "1", "yes")

            valid_rows.append(
                {
                    "call_id": call_id,
                    "transcript": sanitized_text,
                    "as_of_date": str(row.get("as_of_date") or "") or None,
                    "expected_intent": str(row.get("expected_intent") or "") or None,
                    "expected_complexity": parsed_comp,
                    "expected_risk": str(row.get("expected_risk") or "") or None,
                    "expected_route": str(row.get("expected_route") or "") or None,
                    "expected_challenger": parsed_chal,
                    "source_system": str(row.get("source_system") or "AURA_EXCEL_UPLOAD"),
                    "metadata_json": str(row.get("metadata_json") or "{}"),
                }
            )

        summary = FileValidationSummary(
            file_path=str(file_path),
            valid_file=len(missing_cols) == 0 and len(valid_rows) > 0,
            total_rows=len(records),
            valid_rows=len(valid_rows),
            invalid_rows=len(row_errors),
            duplicate_identifiers=duplicate_ids,
            missing_required_columns=[],
            row_level_errors=row_errors,
        )
        return summary, valid_rows

    def ingest_validated_calls(
        self,
        file_path: str | Path,
        replace_existing: bool = True,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        """Validate file, insert all valid rows into SQLite, and create a processing_jobs record."""
        summary, valid_rows = self.validate_file(file_path=file_path, replace_existing=replace_existing)
        if summary.missing_required_columns:
            raise AuraError(
                error_code=ErrorCode.MISSING_EXCEL_COLUMNS,
                user_message=f"Cannot ingest file: missing required columns {', '.join(summary.missing_required_columns)}.",
                technical_message=f"Missing columns: {summary.missing_required_columns}",
            )

        created_job_id = self.repo.create_processing_job(
            source_file=Path(file_path).name,
            total_calls=summary.total_rows,
            valid_calls=len(valid_rows),
            failed_validation_calls=summary.invalid_rows,
            job_id=job_id,
        )

        inserted = 0
        for item in valid_rows:
            self.repo.upsert_call(
                call_id=item["call_id"],
                transcript=item["transcript"],
                source_file=Path(file_path).name,
                source_system=item["source_system"],
                as_of_date=item["as_of_date"],
                expected_intent=item["expected_intent"],
                expected_complexity=item["expected_complexity"],
                expected_risk=item["expected_risk"],
                expected_route=item["expected_route"],
                expected_challenger=item["expected_challenger"],
                metadata_json=item["metadata_json"],
                job_id=created_job_id,
                replace_existing=replace_existing,
            )
            inserted += 1

        return {
            "job_id": created_job_id,
            "source_file": Path(file_path).name,
            "total_rows": summary.total_rows,
            "inserted_count": inserted,
            "rejected_count": summary.invalid_rows,
            "current_status": "Ready" if inserted > 0 else "Empty",
            "validation_summary": summary.model_dump(),
        }
