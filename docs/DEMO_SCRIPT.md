# AURA 5-Minute Hackathon Judging Demo Script

**Project**: AURA — AI Unified Review Assistant  
**Positioning**: MCP 2.0-Native AI Review Governance & Orchestration Platform for Customer-Call Transcripts  
**Core Thesis**: *"The LLM provides analysis. MCP provides discoverability, context, governance, reusable tools, policies, and access to enterprise data. SQLite provides durable storage, history, metrics, and auditability. Streamlit provides a visually polished judging interface."*

---

## Pre-Demo Verification (30 seconds before judging)

Ensure the SQLite database (`data/aura.db`) is seeded and the Streamlit app is running:

```bash
# Optional: Reset and pre-seed the database and 105 synthetic calls
PYTHONPATH=src:. python scripts/initialize_database.py --reset
PYTHONPATH=src:. python scripts/generate_synthetic_data.py

# Launch the Streamlit Judging UI
streamlit run app.py
```

---

## Minute 0:00 – 0:40 | Steps 1–2: Opening Hook & MCP 2.0 Architecture

### Step 1: State the Problem clearly
> *"In enterprise contact centers, running every call transcript through a single heavyweight LLM prompt is expensive, opaque, and ungoverned. When a model marks an unresolved dispute as 'Resolved' or misses a compliance signal, there is no policy enforcement, no independent challenger validation, and no audit trail."*

### Step 2: Show the AURA Architecture Banner
Point to the top **AURA Architecture Banner** in the Streamlit app:
`Streamlit UI -> AURA Agent Loop -> MCP 2.0 Client -> AURA MCP Server (Tools + Resources + Prompts) -> AURA Orchestrator -> SQLite System of Record`
- Highlight that AURA uses the **MCP Python SDK 2.0** (`MCPServer`, stateless per-request execution, no `Mcp-Session-Id`, snake_case `input_schema`, logs strictly to `stderr`/`logs/aura.log`).
- Emphasize that the Streamlit UI **never bypasses MCP** — every action flows through `AuraMCPClient` (`mcp_client.py`).

---

## Minute 0:40 – 1:30 | Steps 3–5: Tab 1 (Upload & Ingestion) & MCP Governance Resources

### Step 3: Load the 105-Call Synthetic Dataset (Tab 1)
1. Open **Tab 1: Upload & Ingestion**.
2. Point out the **Download Input Excel Template** button and the explicit **Synthetic Data Only** governance banner.
3. Click **"Validate & Ingest Pre-Generated Synthetic Dataset (105 Calls)"** (or upload `data/synthetic_calls.xlsx`).
4. Show the MCP validation summary returned by `validate_input_file` and `ingest_validated_calls`:
   - 105 total synthetic calls across 21 realistic scenarios (routine payment inquiries, merchant disputes, suspected fraud, compliance concerns, customer distress, self-harm/threat safety scenarios, and challenger disagreement cases).

### Step 4 & 5: Inspect Live MCP Resources (`aura://model-catalog` & `aura://routing-policy`)
1. Switch briefly to **Tab 3: MCP Activity Monitor** (or the Resource Inspector expander).
2. Click to read `aura://model-catalog` and `aura://routing-policy` via the MCP Client:
   - Show the 5 seeded models: `AURA_FAST` (triage), `AURA_DEEP` (specialist), `AURA_CHALLENGER` (independent validator), `AURA_CANDIDATE_V2` (shadow candidate), and `AURA_LEGACY_DISABLED` (retired/blocked).
   - Show how routing rules are declarative MCP resources stored in SQLite, not hardcoded prompt text.

---

## Minute 1:30 – 3:00 | Steps 6–9: Tab 2 (Live Processing) — Routine vs. Complex vs. High-Risk Calls

### Step 6: Run a Routine Low-Risk Call (`SYN-CALL-0001` — Payment Status)
1. Open **Tab 2: Live Processing**.
2. Select a routine call (e.g., `SYN-CALL-0001`, Payment Status / Due Date Inquiry) and click **Run Governed MCP Review (`review_call`)**.
3. Walk judges through the **10-Stage Visual Stepper**:
   - `AURA_FAST` scores Complexity = 1, Confidence = 0.93, zero risk flags.
   - Routing policy selects **`routine_analysis`** and skips `AURA_DEEP` and `AURA_CHALLENGER`, avoiding unnecessary premium model invocations while identifying digital deflection eligibility (`Mobile App`).

### Step 7: Run a Complex Merchant Dispute Call (`SYN-CALL-0036`)
1. Select a Merchant Dispute call (`SYN-CALL-0036`) and click **Run Governed MCP Review**.
2. Show how `dispute_flag=True` and Complexity = 4 trigger **`specialist_analysis`** (`AURA_DEEP`) and automatic **Historical Context Retrieval** (`find_similar_calls`), pulling anonymized comparator outcomes from SQLite without letting historical patterns override individual call facts.

### Step 8 & 9: Run a High-Risk Fraud / Challenger Disagreement Call (`SYN-CALL-0056` or `SYN-CALL-0096`)
1. Select a Challenger Disagreement call (`SYN-CALL-0096`) or Suspected Fraud call (`SYN-CALL-0056`) and run `review_call`.
2. Show the **Side-by-Side Primary vs. Challenger Comparison**:
   - On `SYN-CALL-0096`, the primary specialist model marks the promotional interest dispute as `"Resolved"` with `"Moderate"` risk.
   - **`AURA_CHALLENGER`** independently challenges the decision, detects that the customer remained dissatisfied at call close, elevates risk to `"High"`, overrides resolution to `"Unresolved"`, and sets **`Human Review Required = True`**.

---

## Minute 3:00 – 4:00 | Steps 10–12: Tab 3 (MCP Monitor), Tab 4 (Call Explorer), & Tab 5 (Governance Dashboard)

### Step 10: Show Real-Time MCP 2.0 Telemetry (Tab 3)
1. Open **Tab 3: MCP Activity Monitor**.
2. Show the live telemetry cards and filterable activity table (`RESOURCE READ`, `PROMPT RETRIEVAL`, `TOOL CALL`, `DATABASE WRITE`, `ERROR`) with `correlation_id`, `duration_ms`, and expandable JSON input/output payloads.

### Step 11: Inspect Call Evidence & Chronological Audit Trail (Tab 4)
1. Open **Tab 4: Call Explorer & Audit Trail**.
2. Select `SYN-CALL-0096` (or `SYN-CALL-0056`).
3. Show the timestamped transcript evidence distinguishing **Confirmed Facts** vs. **Customer Allegations**, the structured output of `explain_decision`, and the chronological SQLite audit log (`get_audit_record`) with model versions and prompt hashes.

### Step 12: Executive Portfolio Governance & Excel Export (Tab 5)
1. Open **Tab 5: Governance Dashboard**.
2. Point out the routing funnel, risk-flag breakdown, deflection channel distribution, and the **Workflow-Derived Estimate of Avoided Premium Model Calls** (explicitly labeled without unverified dollar claims).
3. Click **Export Multi-Sheet Governance Workbook (`.xlsx`)** to generate the 8-sheet Excel report (`Final Results`, `First Pass`, `Specialist Results`, `Challenger Results`, `MCP Activity`, `Audit Log`, `Portfolio Summary`, `Failed Calls`).

---

## Minute 4:00 – 5:00 | Steps 13–14: Tab 6 (Model Upgrade Simulator) & Tab 7 (Agent Playground)

### Step 13: Shadow-Test a Candidate Model Upgrade (Tab 6)
1. Open **Tab 6: Model Upgrade Simulator**.
2. Compare Production Model `AURA_DEEP` against Candidate Model `AURA_CANDIDATE_V2` over 20 calls via `simulate_model_upgrade`.
3. Show field-level agreement percentages, critical disagreements on high-risk calls, and the governed recommendation (`continue_shadow_testing` / `candidate_for_canary`), noting that **simulation never grants automatic production approval**.
4. Also show that selecting `AURA_LEGACY_DISABLED` is immediately blocked by MCP catalog governance (`AURA_ERR_DISABLED_MODEL`).

### Step 14: Demonstrate Autonomous Agent Mode, Boundary Safety & Error Recovery (Tab 7)
1. Open **Tab 7: Agent Playground**.
2. Point out the explicit mode selector: **Autonomous MCP Agent Mode** vs. **Offline Deterministic Demo Mode**.
3. Click the preset **"Review this call and explain the governance decision"** — show the discovered `input_schema` JSON, selected MCP tools, and grounded synthesis.
4. Click **"Test Bad-Input Recovery"** (or toggle Controlled Fault Injection) — show the agent receiving a structured `AURA_ERR_EMPTY_TRANSCRIPT` error from the MCP server and automatically recovering on Turn 2.
5. Click **"Test Out-of-Scope Boundary (Weather/Stocks)"** — show the agent politely declining the out-of-scope request without hallucinating tool calls.
