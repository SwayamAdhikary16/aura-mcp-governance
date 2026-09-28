# AURA — AI Unified Review Assistant

**MCP 2.0-Native AI Review Governance and Orchestration Platform for Customer-Call Transcripts**

> **Core Value Proposition**:  
> - **The LLM** provides structured transcript analysis.  
> - **MCP 2.0** provides discoverability, context, governance, reusable tools, policies, and access to enterprise data.  
> - **SQLite** provides durable storage, historical context, portfolio metrics, and end-to-end auditability.  
> - **Streamlit** provides a visually polished 7-tab judging and governance interface.

---

## 1. High-Level Architecture

```text
Streamlit UI (app.py)
    |
    v
AURA Agent Loop (agent.py — Autonomous Agent Mode & Deterministic Demo Mode)
    |
    v
MCP 2.0 Client (mcp_client.py — Stateless Per-Request Client)
    |
    v
AURA MCP Server (src/aura/mcp_server.py — MCPServer, Stateless, snake_case input_schema)
    |
    +--> 10 MCP Tools       (src/aura/tools.py)
    +--> 8 MCP Resources    (src/aura/resources.py)
    +--> 5 MCP Prompts      (src/aura/prompt_templates.py)
    |
    v
AURA Orchestrator (src/aura/processing_service.py)
    |
    +--> Model Catalog Verification       (aura://model-catalog)
    +--> First-Pass Triage                (AURA_FAST)
    +--> Routing-Policy Evaluation        (aura://routing-policy)
    +--> Routine or Specialist Analysis   (AURA_FAST / AURA_DEEP)
    +--> Historical-Context Retrieval     (find_similar_calls)
    +--> Challenger-Policy Evaluation     (aura://challenger-policy)
    +--> Independent Challenger Review    (AURA_CHALLENGER)
    +--> Final Decision Consolidation     (src/aura/consolidator.py)
    +--> Chronological Audit Logging      (src/aura/audit_service.py)
    |
    v
SQLite System of Record (data/aura.db — 13 Tables + Indexed Governance Store)
```

---

## 2. MCP 2.0 Compliance Highlights

AURA is built for the **post-July-2026 MCP Python SDK (`mcp>=2.0.0,<2.1.0`)**:
1. **Stateless Server**: No in-memory session state across requests; no `Mcp-Session-Id` handshakes.
2. **`MCPServer` Class**: Uses `from mcp.server.mcpserver import MCPServer` (never deprecated `FastMCP` patterns).
3. **Runtime Transport Configuration**: Passes `transport`, `host`, and `port` to `mcp.run()` rather than the constructor.
4. **`snake_case` Schemas**: Inspects and exposes `input_schema` with `snake_case` field names across all 10 tools.
5. **Stdout Purity**: Application and audit logs are routed strictly to `stderr` and `logs/aura.log` so `stdio` JSON-RPC framing is never corrupted.
6. **Self-Describing Tools**: Every tool includes comprehensive docstrings specifying when to use, when not to use, required/optional inputs, outputs, read/write behavior, and error boundaries.

---

## 3. Quick Start & Setup Instructions

### Prerequisites
- **Python 3.11+**
- **VS Code** (recommended for local execution and optional Copilot MCP discovery)
- Works **100% offline out of the box** using the deterministic `MockLLMProvider` (`AURA_LLM_PROVIDER=mock`).

### Option A: macOS / Linux (Bash / Zsh)

```bash
# 1. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install pinned dependencies
pip install -r requirements.txt
pip install -e .

# 3. Copy environment configuration
cp .env.example .env

# 4. Initialize and seed the SQLite database (13 tables + catalog + policies)
PYTHONPATH=src:. python scripts/initialize_database.py --reset

# 5. Generate 105 synthetic call transcripts across 21 scenarios
PYTHONPATH=src:. python scripts/generate_synthetic_data.py

# 6. Launch the Streamlit Judging UI
PYTHONPATH=src:. streamlit run app.py
```

### Option B: Windows (PowerShell)

```powershell
# 1. Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install pinned dependencies
pip install -r requirements.txt
pip install -e .

# 3. Copy environment configuration
Copy-Item .env.example .env

# 4. Initialize and seed the SQLite database
$env:PYTHONPATH="src;."
python scripts/initialize_database.py --reset

# 5. Generate 105 synthetic call transcripts across 21 scenarios
python scripts/generate_synthetic_data.py

# 6. Launch the Streamlit Judging UI
streamlit run app.py
```

---

## 4. Running the MCP Server Directly & Exporting Results

### Run MCP Server (`stdio` or `streamable-http`)

```bash
# Default stdio transport (for MCP clients & VS Code Copilot)
PYTHONPATH=src:. python -m aura.mcp_server --transport stdio

# Streamable HTTP transport (on 127.0.0.1:8080)
PYTHONPATH=src:. python -m aura.mcp_server --transport streamable-http --host 127.0.0.1 --port 8080
```

### Export Multi-Sheet Governance Excel Workbook (8 Sheets)

```bash
PYTHONPATH=src:. python scripts/export_results.py --output data/aura_exported_results.xlsx
```

Exports 8 sheets from SQLite (`data/aura.db`):
1. `Final Results`
2. `First Pass`
3. `Specialist Results`
4. `Challenger Results`
5. `MCP Activity`
6. `Audit Log`
7. `Portfolio Summary`
8. `Failed Calls`

---

## 5. VS Code MCP Configuration & Fallback Note

To use AURA directly inside **VS Code GitHub Copilot Chat (Agent Mode)**:
1. Copy [`.vscode/mcp.json.example`](.vscode/mcp.json.example) to `.vscode/mcp.json`.
2. Ensure the Python path points to your `.venv` interpreter.
3. Open Copilot Chat in Agent Mode and query AURA resources (`aura://model-catalog`) or tools (`review_call`, `portfolio_summary`, `simulate_model_upgrade`).

> **Fallback Note**: Even if VS Code Copilot Chat or external network access is unavailable on a judging machine, the **Streamlit Judging UI (`app.py`)** includes its own built-in `AuraMCPClient` (`mcp_client.py`) and **Tab 7: Agent Playground** (`agent.py`), demonstrating live MCP 2.0 tool discovery, resource reading, prompt retrieval, and tool execution completely offline.

---

## 6. Running the Test Suite

AURA includes 32 automated unit, schema, routing, resource, prompt, tool, workflow, and agent tests across 8 test modules in [`tests/`](tests/):

```bash
# Run with pytest
PYTHONPATH=src:. pytest -v

# Or run with standard library unittest
PYTHONPATH=src:. python -m unittest discover -s tests -v
```

---

## 7. Responsible AI, Privacy & Governance Notices

- **Synthetic Data Only**: All 105 included transcripts in `data/synthetic_calls.xlsx` are 100% synthetic. Never upload real customer PII, PCI, account numbers, or credentials.
- **Analytical Signals Only**: Model outputs and `compliance_flag` indicators are analytical signals for human QA and governance prioritization — they are **not** legal determinations or automated adverse actions.
- **Safety Priority**: Any call exhibiting `threat_flag` or `self_harm_flag` immediately elevates to `Critical` risk and requires mandatory human review.
- **No Unverified Financial Claims**: Portfolio efficiency metrics report **estimated avoided premium-model invocations** as a workflow-derived call count, without making unverified dollar savings claims.
- **Candidate Upgrade Governance**: `simulate_model_upgrade` provides shadow-testing evidence (`insufficient_evidence`, `continue_shadow_testing`, `candidate_for_canary`, `not_ready`) and never grants automatic production approval.

---

## 8. Additional Documentation

- **Enterprise LLM Connection Guide**: [`docs/LLM_CONNECTION_GUIDE.md`](docs/LLM_CONNECTION_GUIDE.md) (Synchrony Kong AI Gateway, Amazon Bedrock, Azure OpenAI, JSON repair, and mock fallback)
- **5-Minute Hackathon Judging Demo Script**: [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)
