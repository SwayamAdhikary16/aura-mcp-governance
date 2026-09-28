"""SQLite database initialization, connection context manager, and seeding for AURA."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from aura.config import get_config
from aura.errors import AuraError, ErrorCode
from aura.logging_config import get_logger

logger = get_logger("database")


def utc_now() -> str:
    """Return current UTC ISO timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


SCHEMA_SQL = """
-- A. calls
CREATE TABLE IF NOT EXISTS calls (
    call_id TEXT PRIMARY KEY,
    transcript TEXT NOT NULL,
    source_file TEXT,
    source_system TEXT,
    as_of_date TEXT,
    expected_intent TEXT,
    expected_complexity INTEGER,
    expected_risk TEXT,
    expected_route TEXT,
    expected_challenger INTEGER,
    metadata_json TEXT,
    job_id TEXT,
    processing_status TEXT NOT NULL DEFAULT 'Pending',
    current_stage TEXT NOT NULL DEFAULT 'Transcript Loaded',
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- B. first_pass_results
CREATE TABLE IF NOT EXISTS first_pass_results (
    call_id TEXT PRIMARY KEY,
    result_json TEXT NOT NULL,
    complexity INTEGER NOT NULL,
    analysis_confidence REAL NOT NULL,
    primary_issue TEXT NOT NULL,
    issue_category TEXT NOT NULL,
    issue_subcategory TEXT NOT NULL,
    interaction_origin TEXT NOT NULL,
    dispute_flag INTEGER NOT NULL DEFAULT 0,
    fraud_flag INTEGER NOT NULL DEFAULT 0,
    threat_flag INTEGER NOT NULL DEFAULT 0,
    self_harm_flag INTEGER NOT NULL DEFAULT 0,
    customer_distress_flag INTEGER NOT NULL DEFAULT 0,
    compliance_flag INTEGER NOT NULL DEFAULT 0,
    escalation_flag INTEGER NOT NULL DEFAULT 0,
    repeat_contact_risk_flag INTEGER NOT NULL DEFAULT 0,
    deflection_candidate INTEGER NOT NULL DEFAULT 0,
    needs_deeper_analysis INTEGER NOT NULL DEFAULT 0,
    resolved_in_call_flag INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY (call_id) REFERENCES calls(call_id) ON DELETE CASCADE
);

-- C. specialist_results
CREATE TABLE IF NOT EXISTS specialist_results (
    specialist_result_id TEXT PRIMARY KEY,
    call_id TEXT NOT NULL,
    analysis_type TEXT NOT NULL,
    result_json TEXT NOT NULL,
    resolution_status TEXT NOT NULL,
    first_contact_resolution INTEGER NOT NULL DEFAULT 1,
    call_avoidable INTEGER NOT NULL DEFAULT 0,
    deflection_eligible INTEGER NOT NULL DEFAULT 0,
    deflection_channel TEXT NOT NULL,
    review_required INTEGER NOT NULL DEFAULT 0,
    analysis_confidence REAL NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (call_id) REFERENCES calls(call_id) ON DELETE CASCADE
);

-- D. challenger_results
CREATE TABLE IF NOT EXISTS challenger_results (
    challenger_result_id TEXT PRIMARY KEY,
    call_id TEXT NOT NULL,
    result_json TEXT NOT NULL,
    challenger_agreement INTEGER NOT NULL DEFAULT 1,
    review_required INTEGER NOT NULL DEFAULT 0,
    analysis_confidence REAL NOT NULL,
    final_disposition TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (call_id) REFERENCES calls(call_id) ON DELETE CASCADE
);

-- E. final_results
CREATE TABLE IF NOT EXISTS final_results (
    call_id TEXT PRIMARY KEY,
    final_result_json TEXT NOT NULL,
    final_summary TEXT NOT NULL,
    final_route TEXT NOT NULL,
    final_risk_level TEXT NOT NULL,
    final_resolution_status TEXT NOT NULL,
    specialist_used INTEGER NOT NULL DEFAULT 0,
    challenger_used INTEGER NOT NULL DEFAULT 0,
    human_review_required INTEGER NOT NULL DEFAULT 0,
    final_confidence REAL NOT NULL,
    completed_at TEXT NOT NULL,
    FOREIGN KEY (call_id) REFERENCES calls(call_id) ON DELETE CASCADE
);

-- F. model_catalog
CREATE TABLE IF NOT EXISTS model_catalog (
    model_id TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    model_role TEXT NOT NULL,
    capabilities_json TEXT NOT NULL,
    cost_tier TEXT NOT NULL,
    latency_tier TEXT NOT NULL,
    maximum_complexity INTEGER NOT NULL,
    approval_status TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    catalog_version TEXT NOT NULL
);

-- G. prompt_versions
CREATE TABLE IF NOT EXISTS prompt_versions (
    prompt_id TEXT PRIMARY KEY,
    prompt_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    prompt_role TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

-- H. audit_log
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    tool_name TEXT,
    resource_uri TEXT,
    prompt_name TEXT,
    prompt_version TEXT,
    model_id TEXT,
    model_version TEXT,
    input_summary_json TEXT,
    output_summary_json TEXT,
    route_reason TEXT,
    duration_ms REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL,
    error_code TEXT,
    timestamp TEXT NOT NULL
);

-- I. mcp_activity
CREATE TABLE IF NOT EXISTS mcp_activity (
    activity_id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL,
    call_id TEXT,
    activity_type TEXT NOT NULL,
    operation_name TEXT NOT NULL,
    input_json TEXT,
    output_json TEXT,
    duration_ms REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL,
    error_message TEXT,
    timestamp TEXT NOT NULL
);

-- J. routing_policies
CREATE TABLE IF NOT EXISTS routing_policies (
    policy_id TEXT PRIMARY KEY,
    policy_version TEXT NOT NULL,
    policy_name TEXT NOT NULL,
    policy_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

-- K. governance_policies
CREATE TABLE IF NOT EXISTS governance_policies (
    policy_id TEXT PRIMARY KEY,
    policy_version TEXT NOT NULL,
    policy_name TEXT NOT NULL,
    policy_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

-- L. framework_resources
CREATE TABLE IF NOT EXISTS framework_resources (
    resource_uri TEXT PRIMARY KEY,
    resource_name TEXT NOT NULL,
    version TEXT NOT NULL,
    content_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

-- M. processing_jobs
CREATE TABLE IF NOT EXISTS processing_jobs (
    job_id TEXT PRIMARY KEY,
    source_file TEXT NOT NULL,
    total_calls INTEGER NOT NULL DEFAULT 0,
    valid_calls INTEGER NOT NULL DEFAULT 0,
    failed_validation_calls INTEGER NOT NULL DEFAULT 0,
    processed_calls INTEGER NOT NULL DEFAULT 0,
    successful_calls INTEGER NOT NULL DEFAULT 0,
    failed_calls INTEGER NOT NULL DEFAULT 0,
    processing_status TEXT NOT NULL DEFAULT 'Created',
    started_at TEXT NOT NULL,
    completed_at TEXT
);

-- Required Indexes
CREATE INDEX IF NOT EXISTS idx_calls_call_id ON calls(call_id);
CREATE INDEX IF NOT EXISTS idx_calls_job_id ON calls(job_id);
CREATE INDEX IF NOT EXISTS idx_calls_processing_status ON calls(processing_status);
CREATE INDEX IF NOT EXISTS idx_calls_created_at ON calls(created_at);
CREATE INDEX IF NOT EXISTS idx_first_pass_issue_category ON first_pass_results(issue_category);
CREATE INDEX IF NOT EXISTS idx_first_pass_created_at ON first_pass_results(created_at);
CREATE INDEX IF NOT EXISTS idx_specialist_call_id ON specialist_results(call_id);
CREATE INDEX IF NOT EXISTS idx_challenger_call_id ON challenger_results(call_id);
CREATE INDEX IF NOT EXISTS idx_final_completed_at ON final_results(completed_at);
CREATE INDEX IF NOT EXISTS idx_audit_call_id ON audit_log(call_id);
CREATE INDEX IF NOT EXISTS idx_audit_correlation_id ON audit_log(correlation_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_mcp_activity_call_id ON mcp_activity(call_id);
CREATE INDEX IF NOT EXISTS idx_mcp_activity_correlation_id ON mcp_activity(correlation_id);
CREATE INDEX IF NOT EXISTS idx_mcp_activity_timestamp ON mcp_activity(timestamp);
CREATE INDEX IF NOT EXISTS idx_jobs_job_id ON processing_jobs(job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON processing_jobs(processing_status);
"""


@contextmanager
def get_db_connection(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Context manager yielding a parameterized SQLite connection with WAL mode."""
    cfg = get_config(db_path_override=db_path)
    target_path = cfg.db_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(target_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=30000;")
        yield conn
        conn.commit()
    except sqlite3.OperationalError as exc:
        if conn is not None:
            conn.rollback()
        if "locked" in str(exc).lower():
            raise AuraError(
                error_code=ErrorCode.DATABASE_LOCK,
                user_message="The AURA governance database is temporarily busy. Please retry your request.",
                technical_message=f"SQLite OperationalError: {exc}",
                retryable=True,
                safe_fallback="Wait briefly and retry operation.",
            ) from exc
        raise
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()


def _seed_reference_data(conn: sqlite3.Connection, data_dir: Path) -> None:
    """Seed model catalog, routing/governance policies, frameworks, and prompt versions."""
    now = utc_now()

    catalog_file = data_dir / "model_catalog.json"
    if catalog_file.exists():
        catalog_data = json.loads(catalog_file.read_text(encoding="utf-8"))
        catalog_version = catalog_data.get("catalog_version", "2026.09.1")
        for m in catalog_data.get("models", []):
            conn.execute(
                """
                INSERT OR REPLACE INTO model_catalog (
                    model_id, model_name, model_version, model_role,
                    capabilities_json, cost_tier, latency_tier, maximum_complexity,
                    approval_status, enabled, effective_from, effective_to, catalog_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    m["model_id"],
                    m["model_name"],
                    m["model_version"],
                    m["model_role"],
                    json.dumps(m["capabilities"]),
                    m["cost_tier"],
                    m["latency_tier"],
                    int(m["maximum_complexity"]),
                    m["approval_status"],
                    1 if m.get("enabled", True) else 0,
                    m["effective_from"],
                    m.get("effective_to"),
                    catalog_version,
                ),
            )

    routing_file = data_dir / "routing_policy.json"
    if routing_file.exists():
        r_data = json.loads(routing_file.read_text(encoding="utf-8"))
        conn.execute(
            """
            INSERT OR REPLACE INTO routing_policies (
                policy_id, policy_version, policy_name, policy_json, active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                r_data["policy_id"],
                r_data["policy_version"],
                r_data["policy_name"],
                json.dumps(r_data),
                1 if r_data.get("active", True) else 0,
                now,
            ),
        )

    challenger_file = data_dir / "challenger_policy.json"
    if challenger_file.exists():
        c_data = json.loads(challenger_file.read_text(encoding="utf-8"))
        conn.execute(
            """
            INSERT OR REPLACE INTO governance_policies (
                policy_id, policy_version, policy_name, policy_json, active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                c_data["policy_id"],
                c_data["policy_version"],
                c_data["policy_name"],
                json.dumps(c_data),
                1 if c_data.get("active", True) else 0,
                now,
            ),
        )

    for fname in ("quality_framework.json", "compliance_framework.json"):
        fpath = data_dir / fname
        if fpath.exists():
            f_data = json.loads(fpath.read_text(encoding="utf-8"))
            conn.execute(
                """
                INSERT OR REPLACE INTO framework_resources (
                    resource_uri, resource_name, version, content_json, active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f_data["resource_uri"],
                    f_data["resource_name"],
                    f_data["version"],
                    json.dumps(f_data),
                    1,
                    now,
                ),
            )

    seeded_prompts = [
        ("PROMPT-FP-2.1", "first_pass_prompt", "2.1.0", "First-pass triage", "aura-first-pass-v2.1.0"),
        ("PROMPT-SINGLE-2.1", "single_analysis_prompt", "2.1.0", "Routine analysis", "aura-single-analysis-v2.1.0"),
        ("PROMPT-SPLIT-2.1", "split_analysis_prompt", "2.1.0", "Specialist deep analysis", "aura-split-analysis-v2.1.0"),
        ("PROMPT-CHAL-2.1", "challenger_prompt", "2.1.0", "Challenger validation", "aura-challenger-v2.1.0"),
    ]
    for pid, pname, pver, prole, seed_str in seeded_prompts:
        phash = hashlib.sha256(seed_str.encode("utf-8")).hexdigest()[:16]
        conn.execute(
            """
            INSERT OR REPLACE INTO prompt_versions (
                prompt_id, prompt_name, prompt_version, prompt_role, prompt_hash, active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (pid, pname, pver, prole, phash, 1, now),
        )


def initialize_database(db_path: str | Path | None = None, reset: bool = False) -> Path:
    """Initialize SQLite schema, indexes, and reference governance seed data."""
    cfg = get_config(db_path_override=db_path)
    target_path = cfg.db_path
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if reset and target_path.exists():
        target_path.unlink()

    with get_db_connection(target_path) as conn:
        conn.executescript(SCHEMA_SQL)
        _seed_reference_data(conn, cfg.data_dir)

    logger.info("Initialized AURA SQLite database at %s", target_path)
    return target_path
