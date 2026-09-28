"""AURA - AI Unified Review Assistant: Streamlit Governance & Orchestration UI (`app.py`).

Primary Judging Path:
Streamlit UI -> AURA Agent Loop (`agent.py`) -> MCP Client (`mcp_client.py`) -> AURA MCP Server (`mcp_server.py`) -> SQLite.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from agent import AuraAgent  # noqa: E402
from aura.config import get_config  # noqa: E402
from aura.database import initialize_database  # noqa: E402
from aura.processing_service import PIPELINE_STAGES  # noqa: E402
from aura.repositories import AuraRepository  # noqa: E402
from mcp_client import AuraMCPClient  # noqa: E402
from scripts.export_results import build_export_workbook_bytes  # noqa: E402
from scripts.generate_synthetic_data import main as generate_synthetic_files  # noqa: E402


st.set_page_config(
    page_title="AURA | AI Unified Review Assistant",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Enterprise Visual Palette (White, Dark Charcoal, Warm Gold/Yellow, Green, Amber, Red, Gray)
CUSTOM_CSS = """
<style>
    .aura-header {
        background: linear-gradient(135deg, #111827 0%, #1F2937 100%);
        color: #FFFFFF;
        padding: 1.25rem 1.75rem;
        border-radius: 10px;
        border-left: 6px solid #F59E0B;
        margin-bottom: 1rem;
    }
    .aura-header h1 {
        margin: 0;
        font-size: 1.75rem;
        color: #F9FAFB;
        letter-spacing: 0.5px;
    }
    .aura-header p {
        margin: 0.35rem 0 0 0;
        color: #D1D5DB;
        font-size: 0.95rem;
    }
    .demo-banner {
        background-color: #FEF3C7;
        border: 1px solid #F59E0B;
        border-left: 5px solid #D97706;
        color: #92400E;
        padding: 0.65rem 1rem;
        border-radius: 6px;
        font-size: 0.88rem;
        margin-bottom: 1rem;
        font-weight: 500;
    }
    .safety-banner {
        background-color: #F3F4F6;
        border: 1px solid #D1D5DB;
        border-left: 5px solid #374151;
        color: #1F2937;
        padding: 0.6rem 1rem;
        border-radius: 6px;
        font-size: 0.82rem;
        margin-bottom: 1rem;
    }
    .stage-card {
        padding: 0.55rem 0.8rem;
        border-radius: 6px;
        margin-bottom: 0.45rem;
        font-size: 0.86rem;
        font-weight: 600;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .stage-completed { background-color: #ECFDF5; border-left: 4px solid #10B981; color: #065F46; }
    .stage-running { background-color: #FFFBEB; border-left: 4px solid #F59E0B; color: #92400E; }
    .stage-review { background-color: #FEF3C7; border-left: 4px solid #D97706; color: #92400E; }
    .stage-failed { background-color: #FEF2F2; border-left: 4px solid #EF4444; color: #991B1B; }
    .stage-skipped { background-color: #F3F4F6; border-left: 4px solid #9CA3AF; color: #4B5563; }
    .stage-pending { background-color: #F9FAFB; border-left: 4px solid #D1D5DB; color: #6B7280; }
    .mcp-badge {
        display: inline-block;
        padding: 0.15rem 0.55rem;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 700;
        margin-right: 0.5rem;
    }
    .badge-tool { background-color: #FEF3C7; color: #92400E; border: 1px solid #F59E0B; }
    .badge-resource { background-color: #E0E7FF; color: #1E40AF; border: 1px solid #6366F1; }
    .badge-prompt { background-color: #FCE7F3; color: #9D174D; border: 1px solid #EC4899; }
    .badge-db { background-color: #ECFDF5; color: #065F46; border: 1px solid #10B981; }
    .badge-retry { background-color: #FFEDD5; color: #9A3412; border: 1px solid #F97316; }
    .badge-error { background-color: #FEE2E2; color: #991B1B; border: 1px solid #EF4444; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def _ensure_initialized() -> tuple[AuraRepository, AuraMCPClient, AuraAgent]:
    """Ensure SQLite database and synthetic dataset exist, returning repo, MCP client, and Agent."""
    cfg = get_config()
    initialize_database(db_path=cfg.db_path, reset=False)
    if not (cfg.data_dir / "synthetic_calls.xlsx").exists():
        generate_synthetic_files()
    repo = AuraRepository(db_path=cfg.db_path)
    client = AuraMCPClient(db_path=cfg.db_path)
    agent = AuraAgent(mcp_client=client, db_path=cfg.db_path)
    return repo, client, agent


repo, mcp_client, aura_agent = _ensure_initialized()
cfg = get_config()

# Initialize UI selection keys in session_state (business state stays strictly in SQLite)
if "selected_job_id" not in st.session_state:
    jobs = repo.list_processing_jobs()
    st.session_state["selected_job_id"] = jobs[0]["job_id"] if jobs else ""
if "selected_call_id" not in st.session_state:
    st.session_state["selected_call_id"] = "SYN-CALL-0001"
if "last_validation_summary" not in st.session_state:
    st.session_state["last_validation_summary"] = None
if "last_agent_run" not in st.session_state:
    st.session_state["last_agent_run"] = None


def _stage_css_class(status: str) -> tuple[str, str]:
    s = (status or "Pending").strip()
    if s == "Completed":
        return "stage-completed", "🟢 Completed"
    if s == "Running":
        return "stage-running", "🟡 Running"
    if s == "Human Review Required":
        return "stage-review", "🟠 Human Review Required"
    if s in ("Failed", "Error"):
        return "stage-failed", "🔴 Failed"
    if s == "Skipped":
        return "stage-skipped", "⚪ Skipped"
    return "stage-pending", "⏳ Pending"


def _activity_badge_html(activity_type: str) -> str:
    t = (activity_type or "").upper()
    if "TOOL" in t:
        cls = "badge-tool"
    elif "RESOURCE" in t:
        cls = "badge-resource"
    elif "PROMPT" in t:
        cls = "badge-prompt"
    elif "DATABASE" in t:
        cls = "badge-db"
    elif "RETRY" in t:
        cls = "badge-retry"
    elif "ERROR" in t:
        cls = "badge-error"
    else:
        cls = "badge-tool"
    return f'<span class="mcp-badge {cls}">{activity_type}</span>'


# ============================================================================
# Header & Responsible AI / Demo Banners
# ============================================================================
st.markdown(
    """
    <div class="aura-header">
        <h1>🛡️ AURA — AI Unified Review Assistant</h1>
        <p>MCP 2.0-Native AI Review Governance, Policy Routing, Challenger Validation & Audit Platform</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if cfg.llm_provider == "mock" or cfg.demo_mode:
    st.markdown(
        """
        <div class="demo-banner">
            ⚡ <strong>Offline deterministic demonstration:</strong> Running with deterministic Mock LLM Provider
            over live stateless MCP 2.0 Client/Server tool & resource calls and SQLite persistence.
            No external API credentials required.
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown(
    """
    <div class="safety-banner">
        <strong>Responsible AI & Governance Notice:</strong>
        100% synthetic demonstration data only (never upload real PII/PCI/credentials) •
        Model outputs are analytical signals, not automated adverse actions •
        Compliance flags are analytical indicators and <em>not</em> legal determinations •
        Historical call patterns provide context only and do not determine individual outcomes •
        Threat & self-harm scenarios are synthetic test cases requiring immediate human review (AI is not an emergency-response authority).
    </div>
    """,
    unsafe_allow_html=True,
)

# ============================================================================
# Sidebar: System Status, Quick Demo Seed, and Reset Controls
# ============================================================================
with st.sidebar:
    st.subheader("⚙️ Governance Controls")
    st.caption(f"**MCP Transport:** `{cfg.mcp_transport}` (Stateless 2.0)")
    st.caption(f"**LLM Provider:** `{cfg.llm_provider.upper()}`")
    st.caption(f"**SQLite SoR:** `{cfg.db_path.name}`")

    st.divider()
    st.markdown("**🚀 Quick Demo Setup**")
    if st.button("📥 Load & Process 21-Scenario Demo Sample", use_container_width=True):
        with st.spinner("Ingesting synthetic dataset & running governed MCP batch (21 scenarios)..."):
            synth_path = str(cfg.data_dir / "synthetic_calls.xlsx")
            ing_out = mcp_client.invoke_tool(
                "ingest_validated_calls",
                {"file_path": synth_path, "replace_existing": True},
            )
            jid = ing_out.get("job_id", "")
            st.session_state["selected_job_id"] = jid
            mcp_client.invoke_tool(
                "review_batch",
                {
                    "job_id": jid,
                    "maximum_calls": 21,
                    "stop_on_error": False,
                    "use_cached_results": True,
                },
            )
        st.success("Loaded 105 synthetic calls & processed 21 representative scenarios via MCP!")
        st.rerun()

    if st.button("🔄 Reset Demo Database", use_container_width=True):
        initialize_database(db_path=cfg.db_path, reset=True)
        st.session_state["selected_job_id"] = ""
        st.session_state["last_validation_summary"] = None
        st.session_state["last_agent_run"] = None
        st.toast("SQLite database reset and re-seeded cleanly.", icon="✅")
        st.rerun()

    st.divider()
    excel_bytes = build_export_workbook_bytes(db_path=cfg.db_path)
    st.download_button(
        label="📊 Export 8-Sheet Governance Excel",
        data=excel_bytes,
        file_name="aura_governance_results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

# ============================================================================
# Main Navigation Tabs (A through G)
# ============================================================================
tabs = st.tabs(
    [
        "📁 A. Upload & Ingestion",
        "⚡ B. Live Processing",
        "📡 C. MCP Activity Monitor",
        "🔍 D. Call Explorer",
        "📊 E. Governance Dashboard",
        "🧪 F. Model Upgrade Simulator",
        "🤖 G. Agent Playground",
    ]
)

# ----------------------------------------------------------------------------
# TAB A: Upload and Ingestion
# ----------------------------------------------------------------------------
with tabs[0]:
    st.subheader("📁 Batch Excel Upload, Validation & SQLite Ingestion")
    st.info(
        "🏷️ **SYNTHETIC DATA ONLY:** Required columns: `call_id`, `transcript`. "
        "Optional columns: `as_of_date`, `expected_intent`, `expected_complexity`, `expected_risk`, "
        "`expected_route`, `expected_challenger`, `source_system`, `metadata_json`."
    )

    col_tpl, col_synth = st.columns(2)
    with col_tpl:
        template_path = cfg.data_dir / "input_template.xlsx"
        if template_path.exists():
            st.download_button(
                "⬇️ Download Input Excel Template (.xlsx)",
                data=template_path.read_bytes(),
                file_name="aura_input_template.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
    with col_synth:
        synth_xlsx_path = cfg.data_dir / "synthetic_calls.xlsx"
        if synth_xlsx_path.exists():
            st.download_button(
                "⬇️ Download 105 Synthetic Calls Dataset (.xlsx)",
                data=synth_xlsx_path.read_bytes(),
                file_name="synthetic_calls.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    st.divider()
    uploaded_file = st.file_uploader(
        "Upload Customer Call Transcripts (.xlsx or .csv)",
        type=["xlsx", "csv"],
    )
    replace_existing_opt = st.checkbox(
        "Allow replacing existing duplicate `call_id` records in SQLite",
        value=True,
    )

    col_v1, col_v2 = st.columns(2)
    target_validation_path: Path | None = None
    if uploaded_file is not None:
        upload_staging = cfg.data_dir / f"uploaded_{uploaded_file.name}"
        upload_staging.write_bytes(uploaded_file.getvalue())
        target_validation_path = upload_staging

    with col_v1:
        if st.button("🔎 Validate Uploaded / Synthetic File via MCP", use_container_width=True):
            use_path = target_validation_path or (cfg.data_dir / "synthetic_calls.xlsx")
            val_res = mcp_client.invoke_tool(
                "validate_input_file",
                {"file_path": str(use_path), "replace_existing": replace_existing_opt},
            )
            st.session_state["last_validation_summary"] = val_res

    with col_v2:
        if st.button("✅ Ingest Validated Calls into SQLite via MCP", type="primary", use_container_width=True):
            use_path = target_validation_path or (cfg.data_dir / "synthetic_calls.xlsx")
            ing_res = mcp_client.invoke_tool(
                "ingest_validated_calls",
                {"file_path": str(use_path), "replace_existing": replace_existing_opt},
            )
            if ing_res.get("status") == "error":
                st.error(ing_res["error"]["user_message"])
            else:
                st.session_state["selected_job_id"] = ing_res.get("job_id", "")
                st.session_state["last_validation_summary"] = ing_res.get("validation_summary")
                st.success(
                    f"Ingested **{ing_res.get('inserted_count')}** valid calls into SQLite! "
                    f"Generated Job ID: **`{ing_res.get('job_id')}`** "
                    f"(Rejected rows: {ing_res.get('rejected_count')})."
                )

    val_summary = st.session_state.get("last_validation_summary")
    if val_summary:
        if val_summary.get("status") == "error":
            st.error(f"Validation Error ({val_summary['error']['error_code']}): {val_summary['error']['user_message']}")
        else:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total Rows", val_summary.get("total_rows", 0))
            m2.metric("Valid Rows", val_summary.get("valid_rows", 0))
            m3.metric("Invalid Rows", val_summary.get("invalid_rows", 0))
            m4.metric("Duplicates Flagged", len(val_summary.get("duplicate_identifiers", [])))

            if val_summary.get("missing_required_columns"):
                st.error(f"Missing required columns: {', '.join(val_summary['missing_required_columns'])}")

            row_errs = val_summary.get("row_level_errors", [])
            if row_errs:
                st.warning(f"{len(row_errs)} row-level validation error(s) detected. Valid rows can still be loaded.")
                st.dataframe(row_errs, use_container_width=True)
                st.download_button(
                    "⬇️ Download Row Validation Errors (JSON)",
                    data=json.dumps(row_errs, indent=2),
                    file_name="aura_validation_errors.json",
                    mime="application/json",
                )
            else:
                st.success("All rows passed schema, duplicate, and transcript-length validation!")

    st.markdown("#### Currently Ingested Calls Preview (SQLite System of Record)")
    preview_calls = repo.list_calls(limit=15)
    if preview_calls:
        st.dataframe(
            [
                {
                    "call_id": c["call_id"],
                    "processing_status": c["processing_status"],
                    "current_stage": c["current_stage"],
                    "expected_intent": c.get("expected_intent"),
                    "expected_complexity": c.get("expected_complexity"),
                    "expected_route": c.get("expected_route"),
                    "job_id": c.get("job_id"),
                }
                for c in preview_calls
            ],
            use_container_width=True,
        )

# ----------------------------------------------------------------------------
# TAB B: Live Processing
# ----------------------------------------------------------------------------
with tabs[1]:
    st.subheader("⚡ Governed Pipeline Execution & Stage Telemetry")

    all_calls = repo.list_calls(limit=200)
    total_cnt = len(all_calls)
    done_cnt = sum(1 for c in all_calls if c["processing_status"] in ("Completed", "Human Review Required"))
    fail_cnt = sum(1 for c in all_calls if c["processing_status"] == "Failed")
    pend_cnt = sum(1 for c in all_calls if c["processing_status"] == "Pending")

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Ingested Calls", total_cnt)
    k2.metric("Completed / Governed", done_cnt)
    k3.metric("Failed Calls", fail_cnt)
    k4.metric("Pending in Queue", pend_cnt)

    progress_ratio = (done_cnt + fail_cnt) / max(1, total_cnt) if total_cnt else 0.0
    st.progress(progress_ratio, text=f"Portfolio Processing Progress: {done_cnt + fail_cnt} / {total_cnt} calls")

    if not all_calls:
        st.warning("No calls in SQLite yet. Use Tab A or the Sidebar button to ingest synthetic calls.")
    else:
        col_left, col_right = st.columns([1.15, 1.35])

        with col_left:
            st.markdown("#### 🎯 Select Call or Run Sequential Batch via MCP")
            call_options = [
                f"{c['call_id']} | {c['processing_status']} | {c.get('expected_intent') or 'Call'}"
                for c in all_calls
            ]
            selected_label = st.selectbox("Select Call ID to Inspect or Process Live:", call_options)
            active_cid = selected_label.split("|")[0].strip()
            st.session_state["selected_call_id"] = active_cid
            active_call_row = repo.get_call(active_cid)

            force_chal_live = st.checkbox("Force Independent Challenger Validation", value=False)

            b_single, b_batch = st.columns(2)
            with b_single:
                if st.button("▶️ Run Selected Call via MCP (`review_call`)", type="primary", use_container_width=True):
                    with st.status(f"Executing governed MCP `review_call` for `{active_cid}`...", expanded=True) as status_box:
                        st.write("1. Connecting to stateless AURA MCP Server...")
                        res = mcp_client.invoke_tool(
                            "review_call",
                            {
                                "call_id": active_cid,
                                "transcript": active_call_row["transcript"],
                                "review_goal": "Live judging demonstration via MCP Client",
                                "force_challenger": force_chal_live,
                            },
                        )
                        if res.get("status") == "error":
                            status_box.update(label=f"Controlled Error on {active_cid}", state="error")
                            st.error(res["error"]["user_message"])
                        else:
                            status_box.update(
                                label=f"Completed `{active_cid}` -> Route: `{res.get('route_selected')}`",
                                state="complete",
                            )
                    st.rerun()

            with b_batch:
                batch_limit = st.number_input("Batch Size", min_value=1, max_value=105, value=5, label_visibility="collapsed")
                if st.button(f"⏩ Process Next {batch_limit} Pending Calls via MCP", use_container_width=True):
                    pending_rows = [c for c in all_calls if c["processing_status"] == "Pending"][: int(batch_limit)]
                    if not pending_rows:
                        pending_rows = all_calls[: int(batch_limit)]
                    prog = st.progress(0.0, text="Starting sequential MCP batch...")
                    stage_ph = st.empty()
                    for idx, prow in enumerate(pending_rows, start=1):
                        pcid = prow["call_id"]
                        stage_ph.info(f"Invoking MCP `review_call` for **{pcid}** ({idx}/{len(pending_rows)})...")
                        mcp_client.invoke_tool(
                            "review_call",
                            {
                                "call_id": pcid,
                                "transcript": prow["transcript"],
                                "review_goal": "Sequential batch processing via MCP Client",
                                "force_challenger": False,
                            },
                        )
                        prog.progress(idx / len(pending_rows), text=f"Processed {idx}/{len(pending_rows)}: {pcid}")
                    st.rerun()

            st.markdown("#### 📜 Sanitized Transcript")
            st.code(active_call_row["transcript"], language="text")

        with col_right:
            st.markdown(f"#### 🏛️ 10-Stage Governed Pipeline for `{active_cid}`")
            audit_events = repo.get_audit_events(active_cid)
            final_rec = repo.get_final_result(active_cid)
            stage_map: dict[str, dict[str, Any]] = {}
            for ev in audit_events:
                s_name = ev["stage_name"]
                stage_map[s_name] = {
                    "status": ev["status"],
                    "duration_ms": ev["duration_ms"],
                    "route_reason": ev.get("route_reason"),
                }

            for idx, stage_name in enumerate(PIPELINE_STAGES, start=1):
                s_info = stage_map.get(stage_name)
                if s_info:
                    st_status = s_info["status"]
                    if stage_name == "Audit Stored" and final_rec and final_rec["human_review_required"]:
                        st_status = "Human Review Required"
                    dur_label = f"{s_info['duration_ms']:.1f} ms"
                else:
                    st_status = "Pending"
                    dur_label = "—"

                css_cls, badge_txt = _stage_css_class(st_status)
                st.markdown(
                    f"""
                    <div class="stage-card {css_cls}">
                        <span>{idx}. {stage_name}</span>
                        <span>{badge_txt} &nbsp;|&nbsp; <small>{dur_label}</small></span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            if final_rec:
                parsed_f = final_rec["parsed"]
                st.markdown("#### 📌 Consolidated Decision Summary")
                st.write(parsed_f.get("final_summary"))
                c_a, c_b, c_c = st.columns(3)
                c_a.metric("Selected Route", parsed_f.get("final_route"))
                c_b.metric("Final Risk Level", parsed_f.get("final_risk_level"))
                c_c.metric(
                    "Human Review",
                    "REQUIRED" if parsed_f.get("human_review_required") else "Not Required",
                )

# ----------------------------------------------------------------------------
# TAB C: MCP Activity Monitor
# ----------------------------------------------------------------------------
with tabs[2]:
    st.subheader("📡 Live MCP 2.0 Activity Monitor (Tools, Resources, Prompts, Retries, DB Writes)")
    st.caption(
        "Every operation invoked through the AURA MCP Server and Client is logged in SQLite (`mcp_activity`) "
        "with correlation ID, input/output JSON, status, and execution latency."
    )

    r_col1, r_col2, r_col3 = st.columns(3)
    with r_col1:
        selected_res_uri = st.selectbox(
            "Inspect Live MCP Resource (`read_resource`):",
            [
                "aura://model-catalog",
                "aura://routing-policy",
                "aura://challenger-policy",
                "aura://quality-framework",
                "aura://compliance-framework",
                "aura://output-schema",
                "aura://prompt-catalog",
                "aura://portfolio-summary",
            ],
        )
        if st.button("📖 Read MCP Resource Now", use_container_width=True):
            res_out = mcp_client.read_resource(selected_res_uri)
            st.session_state["inspected_mcp_item"] = res_out
    with r_col2:
        selected_prompt_name = st.selectbox(
            "Inspect Live MCP Prompt (`get_prompt`):",
            [
                "review_customer_call",
                "investigate_high_risk_call",
                "explain_aura_decision",
                "summarize_portfolio_impact",
                "compare_candidate_model",
            ],
        )
        if st.button("💬 Retrieve MCP Prompt Now", use_container_width=True):
            p_out = mcp_client.get_prompt(selected_prompt_name, {"call_id": st.session_state["selected_call_id"]})
            st.session_state["inspected_mcp_item"] = p_out
    with r_col3:
        type_filter = st.selectbox(
            "Filter Activity Stream by Type:",
            ["ALL", "TOOL CALL", "RESOURCE READ", "PROMPT RETRIEVAL", "DATABASE WRITE", "RETRY", "ERROR"],
        )

    if st.session_state.get("inspected_mcp_item"):
        with st.expander("🔎 Latest Interactive MCP Resource / Prompt Payload", expanded=True):
            st.json(st.session_state["inspected_mcp_item"])

    activities = repo.list_mcp_activity(limit=120)
    if type_filter != "ALL":
        activities = [a for a in activities if a["activity_type"].upper() == type_filter]

    st.markdown(f"#### Recorded MCP Events ({len(activities)} shown)")
    for act in activities[:45]:
        badge = _activity_badge_html(act["activity_type"])
        header_str = (
            f"{act['activity_type']} | `{act['operation_name']}` | "
            f"Call: `{act.get('call_id') or 'GLOBAL'}` | Status: `{act['status']}` | "
            f"{act['duration_ms']:.1f} ms | {act['timestamp']}"
        )
        with st.expander(header_str):
            st.markdown(
                f"{badge} **Correlation ID:** `{act['correlation_id']}` &nbsp;•&nbsp; "
                f"**Activity ID:** `{act['activity_id']}`",
                unsafe_allow_html=True,
            )
            if act.get("error_message"):
                st.error(f"Error: {act['error_message']}")
            ic1, ic2 = st.columns(2)
            with ic1:
                st.markdown("**Input JSON**")
                st.json(act["input"])
            with ic2:
                st.markdown("**Output JSON**")
                st.json(act["output"])

# ----------------------------------------------------------------------------
# TAB D: Call Explorer
# ----------------------------------------------------------------------------
with tabs[3]:
    st.subheader("🔍 Deep Call Governance & Audit Explorer")
    explorer_calls = repo.list_calls(limit=200)
    if not explorer_calls:
        st.info("No calls ingested yet.")
    else:
        exp_ids = [c["call_id"] for c in explorer_calls]
        default_idx = exp_ids.index(st.session_state["selected_call_id"]) if st.session_state["selected_call_id"] in exp_ids else 0
        chosen_cid = st.selectbox("Select Call ID:", exp_ids, index=default_idx, key="explorer_call_select")

        call_rec = repo.get_call(chosen_cid)
        fp_rec = repo.get_first_pass_result(chosen_cid)
        spec_rec = repo.get_specialist_result(chosen_cid)
        chal_rec = repo.get_challenger_result(chosen_cid)
        final_rec = repo.get_final_result(chosen_cid)

        btn_c1, btn_c2, btn_c3 = st.columns(3)
        with btn_c1:
            if st.button("🧠 Explain Decision via MCP (`explain_decision`)", use_container_width=True):
                st.session_state["explorer_explanation"] = mcp_client.invoke_tool("explain_decision", {"call_id": chosen_cid})
        with btn_c2:
            if st.button("⚖️ Compare Primary vs Challenger (`compare_decisions`)", use_container_width=True):
                st.session_state["explorer_comparison"] = mcp_client.invoke_tool("compare_decisions", {"call_id": chosen_cid})
        with btn_c3:
            if st.button("📜 Fetch Full Audit Record (`get_audit_record`)", use_container_width=True):
                st.session_state["explorer_audit"] = mcp_client.invoke_tool("get_audit_record", {"call_id": chosen_cid})

        st.markdown("#### 1. Sanitized Call Transcript")
        st.code(call_rec["transcript"], language="text")

        col_e1, col_e2 = st.columns(2)
        with col_e1:
            st.markdown("#### 2. First-Pass Triage (`AURA_FAST`)")
            if fp_rec:
                st.json(fp_rec["parsed"])
            else:
                st.caption("Not yet processed.")

            st.markdown("#### 3. Primary Routine / Specialist Analysis")
            if spec_rec:
                st.json(spec_rec["parsed"])
            else:
                st.caption("No routine/specialist analysis stored.")

        with col_e2:
            st.markdown("#### 4. Independent Challenger Validation (`AURA_CHALLENGER`)")
            if chal_rec:
                st.json(chal_rec["parsed"])
            else:
                st.caption("Challenger review was not required or not executed for this call.")

            st.markdown("#### 5. Final Consolidated Governed Result")
            if final_rec:
                st.json(final_rec["parsed"])
            else:
                st.caption("No final consolidated result yet.")

        if fp_rec:
            st.markdown("#### 6. Similar Historical Calls Context (`find_similar_calls`)")
            sim_out = mcp_client.invoke_tool(
                "find_similar_calls",
                {
                    "call_id": chosen_cid,
                    "issue_category": fp_rec["issue_category"],
                    "issue_subcategory": fp_rec["issue_subcategory"],
                },
            )
            st.json(sim_out)

        if st.session_state.get("explorer_explanation"):
            st.markdown("#### 🧠 MCP `explain_decision` Output")
            st.json(st.session_state["explorer_explanation"])

        if st.session_state.get("explorer_comparison"):
            st.markdown("#### ⚖️ MCP `compare_decisions` Output")
            st.json(st.session_state["explorer_comparison"])

        st.markdown("#### 7. Chronological SQLite Audit Timeline")
        audit_events = repo.get_audit_events(chosen_cid)
        if audit_events:
            st.dataframe(
                [
                    {
                        "timestamp": e["timestamp"],
                        "stage_name": e["stage_name"],
                        "event_type": e["event_type"],
                        "actor": e["actor_type"],
                        "model_id": e.get("model_id") or "—",
                        "prompt_name": e.get("prompt_name") or "—",
                        "resource_or_tool": e.get("resource_uri") or e.get("tool_name") or "—",
                        "status": e["status"],
                        "duration_ms": e["duration_ms"],
                        "route_reason": e.get("route_reason") or "",
                    }
                    for e in audit_events
                ],
                use_container_width=True,
            )

# ----------------------------------------------------------------------------
# TAB E: Governance Dashboard
# ----------------------------------------------------------------------------
with tabs[4]:
    st.subheader("📊 Executive Portfolio Governance Dashboard")
    port_metrics = mcp_client.invoke_tool("portfolio_summary", {"job_id": ""})

    d1, d2, d3, d4, d5, d6 = st.columns(6)
    d1.metric("Calls Processed", port_metrics.get("total_calls_processed", 0))
    d2.metric("First-Pass Routine", f"{port_metrics.get('first_pass_only_calls', 0)} ({port_metrics.get('routine_call_percentage', 0)}%)")
    d3.metric("Specialist Invoked", f"{port_metrics.get('specialist_review_calls', 0)} ({port_metrics.get('specialist_percentage', 0)}%)")
    d4.metric("Challenger Invoked", f"{port_metrics.get('challenger_review_calls', 0)} ({port_metrics.get('challenger_percentage', 0)}%)")
    d5.metric("Human Review Req.", port_metrics.get("human_review_calls", 0))
    d6.metric("Failed Calls", port_metrics.get("failed_calls", 0))

    avoided_info = port_metrics.get("premium_model_calls_avoided", {})
    st.success(
        f"💡 **Estimated Premium-Model Calls Avoided (Workflow-Derived Estimate):** "
        f"**`{avoided_info.get('estimated_calls_avoided', 0)}`** premium calls avoided "
        f"(Actual premium calls used: `{avoided_info.get('actual_premium_calls_used', 0)}` vs. "
        f"Ungoverned baseline: `{avoided_info.get('ungoverned_baseline_premium_calls', 0)}`).\n\n"
        f"*{avoided_info.get('methodology_label', '')}*"
    )

    ch1, ch2 = st.columns(2)
    with ch1:
        st.markdown("#### Issue Category Distribution")
        cat_dist = port_metrics.get("issue_category_distribution", {})
        if cat_dist:
            st.bar_chart(cat_dist)
        else:
            st.caption("Process calls to populate issue category chart.")

        st.markdown("#### Route & Risk Level Breakdown")
        st.json(
            {
                "route_distribution": port_metrics.get("route_distribution", {}),
                "risk_level_distribution": port_metrics.get("risk_level_distribution", {}),
            }
        )

    with ch2:
        st.markdown("#### Detected Risk & Governance Flag Distribution")
        flag_dist = port_metrics.get("risk_flag_distribution", {})
        if any(flag_dist.values()):
            st.bar_chart(flag_dist)
        else:
            st.caption("No active risk flags recorded yet.")

        st.markdown("#### Deflection Channel & Stage Latency (ms)")
        st.json(
            {
                "deflection_signal_distribution": port_metrics.get("deflection_signal_distribution", {}),
                "average_stage_durations_ms": port_metrics.get("average_stage_durations_ms", {}),
            }
        )

# ----------------------------------------------------------------------------
# TAB F: Model Upgrade Simulator
# ----------------------------------------------------------------------------
with tabs[5]:
    st.subheader("🧪 Governed Candidate Model Upgrade Simulator (`simulate_model_upgrade`)")
    st.caption(
        "Evaluates a candidate model against stored production decisions over a synthetic sample via MCP. "
        "Candidate models are NEVER automatically approved for production."
    )

    u1, u2, u3, u4 = st.columns(4)
    with u1:
        prod_model_sel = st.selectbox("Production Model:", ["AURA_DEEP", "AURA_FAST"])
    with u2:
        cand_model_sel = st.selectbox(
            "Candidate Model:",
            ["AURA_CANDIDATE_V2", "AURA_CHALLENGER", "AURA_LEGACY_DISABLED"],
        )
    with u3:
        sim_sample_size = st.slider("Synthetic Sample Size:", min_value=1, max_value=50, value=15)
    with u4:
        sim_filter = st.text_input("Optional Category/Risk Filter:", value="")

    if st.button("🚀 Run Upgrade Simulation via MCP", type="primary"):
        sim_res = mcp_client.invoke_tool(
            "simulate_model_upgrade",
            {
                "production_model_id": prod_model_sel,
                "candidate_model_id": cand_model_sel,
                "sample_size": sim_sample_size,
                "sample_filter": sim_filter,
            },
        )
        st.session_state["upgrade_sim_result"] = sim_res

    sim_res = st.session_state.get("upgrade_sim_result")
    if sim_res:
        if sim_res.get("status") == "error":
            st.error(
                f"Controlled Governance Error (`{sim_res['error']['error_code']}`): "
                f"{sim_res['error']['user_message']}"
            )
        else:
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Calls Compared", sim_res.get("calls_compared", 0))
            s2.metric("Overall Agreement Score", f"{sim_res.get('overall_agreement_score', 0)}%")
            s3.metric("Critical Disagreements", sim_res.get("critical_disagreement_count", 0))
            s4.metric("Recommendation", sim_res.get("recommendation", "N/A"))

            st.info(f"**Recommendation Rationale:** {sim_res.get('recommendation_rules_explanation')}")
            st.warning(f"**Sample Limitations & Governance Notice:** {sim_res.get('sample_limitations')} {sim_res.get('governance_notice')}")

            fc1, fc2 = st.columns(2)
            with fc1:
                st.markdown("#### Field-Level Agreement (%)")
                st.json(sim_res.get("field_level_agreement", {}))
            with fc2:
                st.markdown("#### High-Risk Disagreement Details")
                st.json(sim_res.get("high_risk_disagreement_details", []))

# ----------------------------------------------------------------------------
# TAB G: Agent Playground
# ----------------------------------------------------------------------------
with tabs[6]:
    st.subheader("🤖 AURA Governed MCP Agent Playground")
    st.caption(
        "Demonstrates `UI -> Agent Loop -> MCP Client -> MCP Server` with dynamic tool discovery, "
        "8-turn maximum guardrails, out-of-scope boundary protection, and negative/recovery test scenarios."
    )

    preset_scenario = st.selectbox(
        "Select a Demo Scenario Preset (or type a custom request below):",
        [
            "1. Happy Path (Routine Payment Status Call - SYN-CALL-0001)",
            "2. Complex Path (Merchant Dispute Specialist Review - SYN-CALL-0009)",
            "3. High-Risk Path (Suspected Fraud + Challenger Review - SYN-CALL-0012)",
            "4. Challenger Disagreement Path (Promotional Interest Dispute - SYN-CALL-0021)",
            "5. Boundary Test (Out-of-Scope Question: Weather / Stock Price)",
            "6. Bad Input Recovery Test (Empty Transcript Submitted First, Then Recovered)",
            "7. Invalid LLM JSON Repair Test (Malformed JSON Repaired in 1 Retry)",
            "8. Challenger Failure Safe Fallback Test (Provisional Result + Human Review)",
            "9. Simulated MCP Connection Failure Test (Controlled Error & Safe Fallback)",
        ],
    )

    preset_defaults: dict[str, tuple[str, str, str | None]] = {
        "1.": (
            "Review SYN-CALL-0001 and determine whether additional governance review is required.",
            "SYN-CALL-0001",
            None,
        ),
        "2.": (
            "Review merchant dispute call SYN-CALL-0009 and explain the routing and specialist findings.",
            "SYN-CALL-0009",
            None,
        ),
        "3.": (
            "Investigate high-risk fraud call SYN-CALL-0012 and verify challenger agreement.",
            "SYN-CALL-0012",
            None,
        ),
        "4.": (
            "Review SYN-CALL-0021 and compare primary specialist vs challenger decisions.",
            "SYN-CALL-0021",
            None,
        ),
        "5.": (
            "What is the weather forecast in New York tomorrow and what is the best pasta recipe?",
            "SYN-CALL-0001",
            None,
        ),
        "6.": (
            "Review SYN-CALL-0001 with bad input recovery test.",
            "SYN-CALL-0001",
            None,
        ),
        "7.": (
            "Review call CALL-JSON-REPAIR-01 and verify JSON repair recovery.",
            "CALL-JSON-REPAIR-01",
            "[SCENARIO:payment_status] [SIMULATE_REPAIRABLE_JSON]\n[00:05] Customer: Checking my synthetic payment status.\n[00:15] Agent: Your payment of 100 units posted today.",
        ),
        "8.": (
            "Review high-risk fraud call CALL-CHAL-FAIL-01 where challenger fails mid-review.",
            "CALL-CHAL-FAIL-01",
            "[SCENARIO:suspected_fraud] [SIMULATE_CHALLENGER_FAILURE]\n[00:05] Customer: I see an unauthorized charge of 900 units—this is suspected fraud!\n[00:20] Agent: Locking your synthetic credential and opening fraud claim.",
        ),
        "9.": (
            "Review SYN-CALL-0001 when MCP server is unreachable.",
            "SYN-CALL-0001",
            None,
        ),
    }

    prefix = preset_scenario[:2]
    def_query, def_cid, def_transcript = preset_defaults.get(prefix, preset_defaults["1."])

    mode_col, cid_col = st.columns([1.4, 1.0])
    with mode_col:
        agent_mode_choice = st.radio(
            "Operating Mode:",
            [
                "agent (Autonomous Tool Selection via Discovered Schemas)",
                "deterministic_demo (Offline deterministic demonstration)",
            ],
            horizontal=True,
        )
    with cid_col:
        pg_call_id = st.text_input("Target Call ID:", value=def_cid)

    user_nl_query = st.text_area("Natural-Language Request:", value=def_query, height=80)

    if st.button("🚀 Execute Request via AURA Agent Loop", type="primary"):
        selected_mode = "agent" if agent_mode_choice.startswith("agent") else "deterministic_demo"
        sim_unavail = prefix == "9."
        sim_bad_input = prefix == "6."

        test_client = AuraMCPClient(db_path=cfg.db_path, simulate_unavailable=sim_unavail)
        test_agent = AuraAgent(mcp_client=test_client, db_path=cfg.db_path)

        st.session_state["last_agent_run"] = test_agent.run_request(
            user_request=user_nl_query,
            call_id=pg_call_id,
            transcript=def_transcript,
            mode=selected_mode,
            simulate_bad_input_first=sim_bad_input,
        )

    agent_out = st.session_state.get("last_agent_run")
    if agent_out:
        st.markdown(f"#### 💬 Agent Response (`{agent_out.get('operating_mode')}`)")
        if agent_out.get("status") == "declined_out_of_scope":
            st.warning(agent_out.get("final_response"))
        else:
            st.markdown(agent_out.get("final_response", ""))

        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Turns Used", f"{agent_out.get('turn_count', 0)} / {agent_out.get('max_turns', 8)}")
        a2.metric("Tools Discovered", len(agent_out.get("tools_discovered", [])))
        a3.metric("Resources Read", len(agent_out.get("resources_used", [])))
        a4.metric("Tool Calls Executed", len(agent_out.get("tool_calls", [])))

        with st.expander("🛠️ Discovered MCP Tool Schemas (`input_schema`)"):
            st.json(agent_out.get("tool_schemas_provided", []))

        with st.expander("📚 MCP Resources & Prompts Retrieved During Turn"):
            st.json(
                {
                    "resources_used": agent_out.get("resources_used", []),
                    "prompts_retrieved": agent_out.get("prompts_retrieved", []),
                }
            )

        with st.expander("⚡ Model-Selected MCP Tool Calls (Inputs & Outputs)", expanded=True):
            st.json(agent_out.get("tool_calls", []))
