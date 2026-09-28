"""Parameterized SQLite repository layer for AURA."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from aura.database import get_db_connection, utc_now
from aura.errors import AuraError, ErrorCode
from aura.schemas import (
    ChallengerAnalysisResult,
    FinalConsolidatedResult,
    FirstPassResult,
    RoutineAnalysisResult,
    SpecialistAnalysisResult,
)


class AuraRepository:
    """Stateless repository providing parameterized SQLite access across all 13 AURA tables."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = db_path

    def get_model_catalog(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        """Return model catalog entries from SQLite."""
        query = "SELECT * FROM model_catalog"
        params: tuple[Any, ...] = ()
        if enabled_only:
            query += " WHERE enabled = ?"
            params = (1,)
        query += " ORDER BY model_id ASC"
        with get_db_connection(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["capabilities"] = json.loads(item.get("capabilities_json") or "[]")
            item["enabled"] = bool(item.get("enabled"))
            results.append(item)
        return results

    def get_validated_model(self, model_id: str) -> dict[str, Any]:
        """Retrieve a specific model and verify it exists and is enabled."""
        with get_db_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM model_catalog WHERE model_id = ?",
                (model_id,),
            ).fetchone()
        if row is None:
            raise AuraError(
                error_code=ErrorCode.UNKNOWN_MODEL_ID,
                user_message=f"Model '{model_id}' was not found in the AURA model catalog.",
                technical_message=f"Unknown model_id={model_id} in model_catalog.",
                retryable=False,
            )
        model = dict(row)
        model["capabilities"] = json.loads(model.get("capabilities_json") or "[]")
        model["enabled"] = bool(model.get("enabled"))
        if not model["enabled"]:
            raise AuraError(
                error_code=ErrorCode.DISABLED_MODEL,
                user_message=f"Model '{model_id}' is currently disabled in the governance catalog.",
                technical_message=f"Model {model_id} has enabled=0 and approval_status={model.get('approval_status')}.",
                retryable=False,
            )
        return model

    def get_active_routing_policy(self) -> dict[str, Any]:
        """Return the active routing policy from SQLite or raise NO_ACTIVE_ROUTING_POLICY."""
        with get_db_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM routing_policies WHERE active = 1 ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            raise AuraError(
                error_code=ErrorCode.NO_ACTIVE_ROUTING_POLICY,
                user_message="No active routing policy is configured in AURA.",
                technical_message="routing_policies table has no row with active=1.",
                human_review_required=True,
            )
        record = dict(row)
        record["policy"] = json.loads(record["policy_json"])
        return record

    def get_active_governance_policy(self) -> dict[str, Any]:
        """Return the active challenger/governance policy from SQLite or raise NO_ACTIVE_GOVERNANCE_POLICY."""
        with get_db_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM governance_policies WHERE active = 1 ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            raise AuraError(
                error_code=ErrorCode.NO_ACTIVE_GOVERNANCE_POLICY,
                user_message="No active challenger governance policy is configured in AURA.",
                technical_message="governance_policies table has no row with active=1.",
                human_review_required=True,
            )
        record = dict(row)
        record["policy"] = json.loads(record["policy_json"])
        return record

    def get_framework_resource(self, resource_uri: str) -> dict[str, Any]:
        """Fetch an active framework resource (quality or compliance) by URI."""
        with get_db_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM framework_resources WHERE resource_uri = ? AND active = 1",
                (resource_uri,),
            ).fetchone()
        if row is None:
            return {}
        data = dict(row)
        data["content"] = json.loads(data["content_json"])
        return data

    def get_prompt_catalog(self) -> list[dict[str, Any]]:
        """Return active prompt versions from SQLite."""
        with get_db_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM prompt_versions WHERE active = 1 ORDER BY prompt_id ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def create_processing_job(
        self,
        source_file: str,
        total_calls: int,
        valid_calls: int,
        failed_validation_calls: int,
        job_id: str | None = None,
    ) -> str:
        """Insert a new processing_jobs row and return job_id."""
        jid = job_id or f"JOB-{uuid.uuid4().hex[:8].upper()}"
        now = utc_now()
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO processing_jobs (
                    job_id, source_file, total_calls, valid_calls,
                    failed_validation_calls, processed_calls, successful_calls,
                    failed_calls, processing_status, started_at
                ) VALUES (?, ?, ?, ?, ?, 0, 0, 0, 'Ready', ?)
                """,
                (jid, source_file, total_calls, valid_calls, failed_validation_calls, now),
            )
        return jid

    def update_processing_job(
        self,
        job_id: str,
        processed_calls: int,
        successful_calls: int,
        failed_calls: int,
        processing_status: str,
        completed: bool = False,
    ) -> None:
        """Update job counters and status."""
        completed_at = utc_now() if completed else None
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                UPDATE processing_jobs
                SET processed_calls = ?,
                    successful_calls = ?,
                    failed_calls = ?,
                    processing_status = ?,
                    completed_at = COALESCE(?, completed_at)
                WHERE job_id = ?
                """,
                (processed_calls, successful_calls, failed_calls, processing_status, completed_at, job_id),
            )

    def get_processing_job(self, job_id: str) -> dict[str, Any] | None:
        """Retrieve a processing job by ID."""
        with get_db_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM processing_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list_processing_jobs(self) -> list[dict[str, Any]]:
        """List all processing jobs ordered by started_at descending."""
        with get_db_connection(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM processing_jobs ORDER BY started_at DESC").fetchall()
        return [dict(r) for r in rows]

    def call_exists(self, call_id: str) -> bool:
        """Return True if call_id already exists in calls table."""
        with get_db_connection(self.db_path) as conn:
            row = conn.execute("SELECT 1 FROM calls WHERE call_id = ?", (call_id,)).fetchone()
        return row is not None

    def upsert_call(
        self,
        call_id: str,
        transcript: str,
        source_file: str = "direct_mcp_input",
        source_system: str = "AURA_SYNTHETIC",
        as_of_date: str | None = None,
        expected_intent: str | None = None,
        expected_complexity: int | None = None,
        expected_risk: str | None = None,
        expected_route: str | None = None,
        expected_challenger: bool | None = None,
        metadata_json: str | None = None,
        job_id: str | None = None,
        replace_existing: bool = True,
    ) -> None:
        """Insert or replace a call record in SQLite."""
        now = utc_now()
        with get_db_connection(self.db_path) as conn:
            existing = conn.execute("SELECT call_id FROM calls WHERE call_id = ?", (call_id,)).fetchone()
            if existing and not replace_existing:
                raise AuraError(
                    error_code=ErrorCode.DUPLICATE_CALL_ID,
                    user_message=f"Duplicate call_id '{call_id}' detected and replace_existing is disabled.",
                    technical_message=f"call_id={call_id} already exists in calls table.",
                )
            conn.execute(
                """
                INSERT INTO calls (
                    call_id, transcript, source_file, source_system,
                    as_of_date, expected_intent, expected_complexity, expected_risk,
                    expected_route, expected_challenger, metadata_json, job_id,
                    processing_status, current_stage, error_code, error_message,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending', 'Transcript Loaded', NULL, NULL, ?, ?)
                ON CONFLICT(call_id) DO UPDATE SET
                    transcript = excluded.transcript,
                    source_file = excluded.source_file,
                    source_system = excluded.source_system,
                    as_of_date = COALESCE(excluded.as_of_date, calls.as_of_date),
                    expected_intent = COALESCE(excluded.expected_intent, calls.expected_intent),
                    expected_complexity = COALESCE(excluded.expected_complexity, calls.expected_complexity),
                    expected_risk = COALESCE(excluded.expected_risk, calls.expected_risk),
                    expected_route = COALESCE(excluded.expected_route, calls.expected_route),
                    expected_challenger = COALESCE(excluded.expected_challenger, calls.expected_challenger),
                    metadata_json = COALESCE(excluded.metadata_json, calls.metadata_json),
                    job_id = COALESCE(excluded.job_id, calls.job_id),
                    processing_status = 'Pending',
                    current_stage = 'Transcript Loaded',
                    error_code = NULL,
                    error_message = NULL,
                    updated_at = excluded.updated_at
                """,
                (
                    call_id,
                    transcript,
                    source_file,
                    source_system,
                    as_of_date,
                    expected_intent,
                    expected_complexity,
                    expected_risk,
                    expected_route,
                    1 if expected_challenger else (0 if expected_challenger is False else None),
                    metadata_json,
                    job_id,
                    now,
                    now,
                ),
            )

    def update_call_stage(
        self,
        call_id: str,
        processing_status: str,
        current_stage: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update processing status and active stage for a call."""
        now = utc_now()
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                UPDATE calls
                SET processing_status = ?,
                    current_stage = ?,
                    error_code = ?,
                    error_message = ?,
                    updated_at = ?
                WHERE call_id = ?
                """,
                (processing_status, current_stage, error_code, error_message, now, call_id),
            )

    def get_call(self, call_id: str) -> dict[str, Any]:
        """Retrieve a call row by call_id or raise UNKNOWN_CALL_ID."""
        with get_db_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM calls WHERE call_id = ?", (call_id,)).fetchone()
        if row is None:
            raise AuraError(
                error_code=ErrorCode.UNKNOWN_CALL_ID,
                user_message=f"Call ID '{call_id}' was not found in the AURA database.",
                technical_message=f"No record in calls table for call_id={call_id}.",
            )
        return dict(row)

    def list_calls(self, job_id: str | None = None, status: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        """List calls optionally filtered by job_id and status."""
        query = "SELECT * FROM calls WHERE 1=1"
        params: list[Any] = []
        if job_id:
            query += " AND job_id = ?"
            params.append(job_id)
        if status:
            query += " AND processing_status = ?"
            params.append(status)
        query += " ORDER BY call_id ASC LIMIT ?"
        params.append(limit)
        with get_db_connection(self.db_path) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def save_first_pass_result(self, result: FirstPassResult) -> None:
        """Persist first_pass_results row."""
        now = utc_now()
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO first_pass_results (
                    call_id, result_json, complexity, analysis_confidence,
                    primary_issue, issue_category, issue_subcategory, interaction_origin,
                    dispute_flag, fraud_flag, threat_flag, self_harm_flag,
                    customer_distress_flag, compliance_flag, escalation_flag,
                    repeat_contact_risk_flag, deflection_candidate,
                    needs_deeper_analysis, resolved_in_call_flag, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.call_id,
                    result.model_dump_json(),
                    result.complexity,
                    result.analysis_confidence,
                    result.primary_issue,
                    result.issue_category,
                    result.issue_subcategory,
                    result.interaction_origin,
                    int(result.dispute_flag),
                    int(result.fraud_flag),
                    int(result.threat_flag),
                    int(result.self_harm_flag),
                    int(result.customer_distress_flag),
                    int(result.compliance_flag),
                    int(result.escalation_flag),
                    int(result.repeat_contact_risk_flag),
                    int(result.deflection_candidate),
                    int(result.needs_deeper_analysis),
                    int(result.resolved_in_call_flag),
                    now,
                ),
            )

    def get_first_pass_result(self, call_id: str) -> dict[str, Any] | None:
        """Retrieve first_pass_results row for call_id."""
        with get_db_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM first_pass_results WHERE call_id = ?", (call_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["parsed"] = json.loads(d["result_json"])
        return d

    def save_specialist_or_routine_result(
        self,
        result: SpecialistAnalysisResult | RoutineAnalysisResult,
    ) -> str:
        """Persist routine or specialist analysis result into specialist_results table."""
        now = utc_now()
        s_id = f"SPEC-{result.call_id}-{uuid.uuid4().hex[:6]}"
        with get_db_connection(self.db_path) as conn:
            conn.execute("DELETE FROM specialist_results WHERE call_id = ?", (result.call_id,))
            conn.execute(
                """
                INSERT INTO specialist_results (
                    specialist_result_id, call_id, analysis_type, result_json,
                    resolution_status, first_contact_resolution, call_avoidable,
                    deflection_eligible, deflection_channel, review_required,
                    analysis_confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    s_id,
                    result.call_id,
                    result.analysis_type,
                    result.model_dump_json(),
                    result.resolution_status,
                    int(result.first_contact_resolution),
                    int(result.call_avoidable),
                    int(result.deflection_eligible),
                    result.deflection_channel,
                    int(result.review_required),
                    result.analysis_confidence,
                    now,
                ),
            )
        return s_id

    def get_specialist_result(self, call_id: str) -> dict[str, Any] | None:
        """Retrieve specialist_results row for call_id."""
        with get_db_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM specialist_results WHERE call_id = ? ORDER BY created_at DESC LIMIT 1",
                (call_id,),
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["parsed"] = json.loads(d["result_json"])
        return d

    def save_challenger_result(self, result: ChallengerAnalysisResult) -> str:
        """Persist challenger_results row."""
        now = utc_now()
        c_id = f"CHAL-{result.call_id}-{uuid.uuid4().hex[:6]}"
        with get_db_connection(self.db_path) as conn:
            conn.execute("DELETE FROM challenger_results WHERE call_id = ?", (result.call_id,))
            conn.execute(
                """
                INSERT INTO challenger_results (
                    challenger_result_id, call_id, result_json,
                    challenger_agreement, review_required, analysis_confidence,
                    final_disposition, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    c_id,
                    result.call_id,
                    result.model_dump_json(),
                    int(result.challenger_agreement),
                    int(result.review_required),
                    result.analysis_confidence,
                    result.final_disposition,
                    now,
                ),
            )
        return c_id

    def get_challenger_result(self, call_id: str) -> dict[str, Any] | None:
        """Retrieve challenger_results row for call_id."""
        with get_db_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM challenger_results WHERE call_id = ? ORDER BY created_at DESC LIMIT 1",
                (call_id,),
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["parsed"] = json.loads(d["result_json"])
        return d

    def save_final_result(self, result: FinalConsolidatedResult) -> None:
        """Persist final_results row."""
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO final_results (
                    call_id, final_result_json, final_summary, final_route,
                    final_risk_level, final_resolution_status, specialist_used,
                    challenger_used, human_review_required, final_confidence, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.call_id,
                    result.model_dump_json(),
                    result.final_summary,
                    result.final_route,
                    result.final_risk_level,
                    result.final_resolution_status,
                    int(result.specialist_used),
                    int(result.challenger_used),
                    int(result.human_review_required),
                    result.final_confidence,
                    result.completed_at,
                ),
            )

    def get_final_result(self, call_id: str) -> dict[str, Any] | None:
        """Retrieve final_results row for call_id."""
        with get_db_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM final_results WHERE call_id = ?", (call_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["parsed"] = json.loads(d["final_result_json"])
        return d

    def find_similar_calls(
        self,
        call_id: str,
        issue_category: str,
        issue_subcategory: str | None = None,
        maximum_results: int = 5,
        minimum_confidence: float = 0.65,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant processed synthetic calls excluding `call_id`."""
        query = """
            SELECT
                fp.call_id,
                fp.issue_category,
                fp.issue_subcategory,
                fp.primary_issue,
                fp.complexity,
                fr.final_route,
                fr.final_resolution_status,
                fr.final_risk_level,
                fr.final_confidence,
                sr.deflection_channel,
                sr.deflection_eligible
            FROM first_pass_results fp
            JOIN final_results fr ON fp.call_id = fr.call_id
            LEFT JOIN specialist_results sr ON fp.call_id = sr.call_id
            WHERE fp.call_id != ?
              AND LOWER(fp.issue_category) = LOWER(?)
              AND fr.final_confidence >= ?
        """
        params: list[Any] = [call_id, issue_category, minimum_confidence]
        if issue_subcategory:
            query += " AND LOWER(fp.issue_subcategory) = LOWER(?)"
            params.append(issue_subcategory)
        query += " ORDER BY fr.completed_at DESC LIMIT ?"
        params.append(max(1, min(maximum_results, 25)))

        with get_db_connection(self.db_path) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            if not rows and issue_subcategory:
                fallback_query = """
                    SELECT
                        fp.call_id,
                        fp.issue_category,
                        fp.issue_subcategory,
                        fp.primary_issue,
                        fp.complexity,
                        fr.final_route,
                        fr.final_resolution_status,
                        fr.final_risk_level,
                        fr.final_confidence,
                        sr.deflection_channel,
                        sr.deflection_eligible
                    FROM first_pass_results fp
                    JOIN final_results fr ON fp.call_id = fr.call_id
                    LEFT JOIN specialist_results sr ON fp.call_id = sr.call_id
                    WHERE fp.call_id != ?
                      AND LOWER(fp.issue_category) = LOWER(?)
                      AND fr.final_confidence >= ?
                    ORDER BY fr.completed_at DESC LIMIT ?
                """
                rows = conn.execute(
                    fallback_query,
                    (call_id, issue_category, minimum_confidence, max(1, min(maximum_results, 25))),
                ).fetchall()
        return [dict(r) for r in rows]

    def record_audit_event(
        self,
        correlation_id: str,
        call_id: str,
        event_type: str,
        stage_name: str,
        actor_type: str,
        status: str,
        duration_ms: float = 0.0,
        tool_name: str | None = None,
        resource_uri: str | None = None,
        prompt_name: str | None = None,
        prompt_version: str | None = None,
        model_id: str | None = None,
        model_version: str | None = None,
        input_summary: dict[str, Any] | None = None,
        output_summary: dict[str, Any] | None = None,
        route_reason: str | None = None,
        error_code: str | None = None,
    ) -> str:
        """Insert a record into audit_log."""
        audit_id = f"AUD-{uuid.uuid4().hex[:12].upper()}"
        now = utc_now()
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO audit_log (
                    audit_id, correlation_id, call_id, event_type, stage_name,
                    actor_type, tool_name, resource_uri, prompt_name, prompt_version,
                    model_id, model_version, input_summary_json, output_summary_json,
                    route_reason, duration_ms, status, error_code, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    correlation_id,
                    call_id,
                    event_type,
                    stage_name,
                    actor_type,
                    tool_name,
                    resource_uri,
                    prompt_name,
                    prompt_version,
                    model_id,
                    model_version,
                    json.dumps(input_summary or {}),
                    json.dumps(output_summary or {}),
                    route_reason,
                    round(duration_ms, 2),
                    status,
                    error_code,
                    now,
                ),
            )
        return audit_id

    def get_audit_events(self, call_id: str) -> list[dict[str, Any]]:
        """Retrieve ordered audit_log entries for a call_id."""
        with get_db_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE call_id = ? ORDER BY timestamp ASC, rowid ASC",
                (call_id,),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            item["input_summary"] = json.loads(item.get("input_summary_json") or "{}")
            item["output_summary"] = json.loads(item.get("output_summary_json") or "{}")
            events.append(item)
        return events

    def record_mcp_activity(
        self,
        correlation_id: str,
        activity_type: str,
        operation_name: str,
        status: str,
        duration_ms: float = 0.0,
        call_id: str | None = None,
        input_payload: dict[str, Any] | None = None,
        output_payload: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> str:
        """Insert a record into mcp_activity."""
        activity_id = f"MCP-{uuid.uuid4().hex[:12].upper()}"
        now = utc_now()
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO mcp_activity (
                    activity_id, correlation_id, call_id, activity_type,
                    operation_name, input_json, output_json, duration_ms,
                    status, error_message, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    activity_id,
                    correlation_id,
                    call_id,
                    activity_type,
                    operation_name,
                    json.dumps(input_payload or {}),
                    json.dumps(output_payload or {}),
                    round(duration_ms, 2),
                    status,
                    error_message,
                    now,
                ),
            )
        return activity_id

    def list_mcp_activity(self, call_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        """Return recent MCP activity records."""
        query = "SELECT * FROM mcp_activity"
        params: list[Any] = []
        if call_id:
            query += " WHERE call_id = ?"
            params.append(call_id)
        query += " ORDER BY rowid DESC LIMIT ?"
        params.append(limit)
        with get_db_connection(self.db_path) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        items: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["input"] = json.loads(d.get("input_json") or "{}")
            d["output"] = json.loads(d.get("output_json") or "{}")
            items.append(d)
        return items
