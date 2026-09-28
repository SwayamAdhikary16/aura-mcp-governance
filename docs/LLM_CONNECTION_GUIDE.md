# AURA Enterprise LLM Connection Guide

AURA (**AI Unified Review Assistant**) decouples MCP 2.0 governance, routing policies, and SQLite auditability from the underlying LLM execution provider. By default, AURA runs completely offline using a deterministic, high-fidelity **`MockLLMProvider`** (`AURA_LLM_PROVIDER=mock`), allowing judges and developers to run all 105 synthetic calls, live MCP workflows, and candidate model upgrade simulations with zero external API keys.

When deploying in an enterprise environment, AURA supports plug-and-play connection to:
1. **Synchrony Kong AI Gateway** (`AURA_LLM_PROVIDER=kong`)
2. **Amazon Bedrock** (`AURA_LLM_PROVIDER=bedrock`)
3. **Azure OpenAI** (`AURA_LLM_PROVIDER=azure_openai`)

---

## 1. Provider Interface (`src/aura/llm_provider/`)

All LLM providers implement `BaseLLMProvider` in [`src/aura/llm_provider/base.py`](../src/aura/llm_provider/base.py) and are instantiated by [`src/aura/llm_provider/provider_factory.py`](../src/aura/llm_provider/provider_factory.py):

```python
class BaseLLMProvider(ABC):
    provider_name: str

    def run_first_pass(self, call_id: str, transcript: str, review_goal: str | None = None) -> tuple[FirstPassResult, bool]: ...
    def run_routine_analysis(self, call_id: str, transcript: str, first_pass: FirstPassResult) -> tuple[RoutineAnalysisResult, bool]: ...
    def run_specialist_analysis(self, call_id: str, transcript: str, first_pass: FirstPassResult, historical_context: dict | None = None) -> tuple[SpecialistAnalysisResult, bool]: ...
    def run_challenger_analysis(self, call_id: str, transcript: str, first_pass: FirstPassResult, primary_result: Any) -> tuple[ChallengerAnalysisResult, bool]: ...
    def repair_json_response(self, broken_json: str, schema_name: str, error_details: str) -> str: ...
    def run_candidate_model_analysis(self, call_id: str, transcript: str, candidate_model_id: str) -> dict[str, Any]: ...
```

The active provider is selected via the `AURA_LLM_PROVIDER` environment variable:
- `mock` (Default — offline deterministic provider)
- `kong` (Synchrony Kong AI Gateway)
- `bedrock` (Amazon Bedrock Converse / InvokeModel)
- `azure_openai` (Azure OpenAI Chat Completions)

---

## 2. Required Environment Variables

Copy `.env.example` to `.env` and set only placeholder or environment-scoped credentials. **Never commit `.env` or real API keys to version control.**

| Variable | Provider | Description |
| :--- | :--- | :--- |
| `AURA_LLM_PROVIDER` | All | `mock`, `kong`, `bedrock`, or `azure_openai` |
| `AURA_FALLBACK_TO_MOCK` | All | `true` (default) to fall back safely to `mock` if enterprise credentials are missing during local testing |
| `KONG_GATEWAY_URL` | `kong` | Base URL for the Synchrony Kong AI Gateway route |
| `KONG_API_KEY` | `kong` | Gateway consumer token / API key |
| `KONG_ROUTE_FAST` | `kong` | Route name for `AURA_FAST` first-pass triage |
| `KONG_ROUTE_DEEP` | `kong` | Route name for `AURA_DEEP` specialist analysis |
| `KONG_ROUTE_CHALLENGER` | `kong` | Route name for `AURA_CHALLENGER` validation |
| `AWS_REGION` | `bedrock` | AWS region (e.g., `us-east-1`) |
| `BEDROCK_MODEL_FAST` | `bedrock` | Bedrock model ID for `AURA_FAST` |
| `BEDROCK_MODEL_DEEP` | `bedrock` | Bedrock model ID for `AURA_DEEP` |
| `BEDROCK_MODEL_CHALLENGER` | `bedrock` | Bedrock model ID for `AURA_CHALLENGER` |
| `AZURE_OPENAI_ENDPOINT` | `azure_openai` | Azure OpenAI resource endpoint URL |
| `AZURE_OPENAI_API_KEY` | `azure_openai` | Azure OpenAI API key |
| `AZURE_OPENAI_API_VERSION` | `azure_openai` | API version (e.g., `2024-10-21`) |
| `AZURE_DEPLOYMENT_FAST` | `azure_openai` | Deployment name for `AURA_FAST` |
| `AZURE_DEPLOYMENT_DEEP` | `azure_openai` | Deployment name for `AURA_DEEP` |
| `AZURE_DEPLOYMENT_CHALLENGER` | `azure_openai` | Deployment name for `AURA_CHALLENGER` |

---

## 3. Synchrony Kong AI Gateway Configuration Template

Implemented in [`src/aura/llm_provider/kong_provider.py`](../src/aura/llm_provider/kong_provider.py).

```ini
# .env configuration for Synchrony Kong AI Gateway
AURA_LLM_PROVIDER=kong
KONG_GATEWAY_URL=https://kong-ai-gateway.internal.example.com/v1/chat/completions
KONG_API_KEY=your_kong_consumer_key_here
KONG_ROUTE_FAST=aura-fast-triage
KONG_ROUTE_DEEP=aura-deep-specialist
KONG_ROUTE_CHALLENGER=aura-challenger-validator
AURA_LLM_TIMEOUT_SECONDS=30
```

Request structure sent by `KongAIProvider`:
- Headers: `apikey: <REDACTED_IN_LOGS>`, `Content-Type: application/json`, `X-Aura-Route: <route>`
- Payload: Standard OpenAI-compatible `messages` array with `response_format={"type": "json_object"}` and `temperature=0.0`.

---

## 4. Amazon Bedrock Configuration Template

Implemented in [`src/aura/llm_provider/bedrock_provider.py`](../src/aura/llm_provider/bedrock_provider.py). Uses standard AWS IAM credential chains (`AWS_PROFILE`, IAM role, or environment credentials).

```ini
# .env configuration for Amazon Bedrock
AURA_LLM_PROVIDER=bedrock
AWS_REGION=us-east-1
BEDROCK_MODEL_FAST=anthropic.claude-3-5-haiku-20241022-v1:0
BEDROCK_MODEL_DEEP=anthropic.claude-3-5-sonnet-20241022-v2:0
BEDROCK_MODEL_CHALLENGER=anthropic.claude-3-5-sonnet-20241022-v2:0
```

---

## 5. Azure OpenAI Configuration Template

Implemented in [`src/aura/llm_provider/azure_openai_provider.py`](../src/aura/llm_provider/azure_openai_provider.py).

```ini
# .env configuration for Azure OpenAI
AURA_LLM_PROVIDER=azure_openai
AZURE_OPENAI_ENDPOINT=https://your-resource-name.openai.azure.com
AZURE_OPENAI_API_KEY=your_azure_openai_key_here
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_DEPLOYMENT_FAST=gpt-4o-mini-aura-fast
AZURE_DEPLOYMENT_DEEP=gpt-4o-aura-deep
AZURE_DEPLOYMENT_CHALLENGER=gpt-4o-aura-challenger
```

---

## 6. JSON Response Validation & Single-Retry Repair

Every LLM stage output in AURA is validated against strict Pydantic v2 models in [`src/aura/schemas.py`](../src/aura/schemas.py):
- `FirstPassResult`
- `RoutineAnalysisResult`
- `SpecialistAnalysisResult`
- `ChallengerAnalysisResult`

In `BaseLLMProvider.validate_with_single_repair()`:
1. The raw string returned by the model is parsed with `json.loads()` and validated via `schema_cls.model_validate()`.
2. If parsing or schema validation fails on the first attempt, AURA logs a `RETRY_TRIGGERED` audit event and invokes `repair_json_response()` **at most once** with the exact Pydantic validation error details.
3. If the single repair succeeds, processing continues seamlessly and records the retry in `audit_log`.
4. If the repair also fails, AURA raises `AuraError(ErrorCode.INVALID_LLM_JSON)` with `human_review_required=True`. In the Challenger stage, a failure retains the primary specialist decision as `provisional_status=True` and routes the call to mandatory human review.

---

## 7. MCP 2.0 Tool-Schema Passing

In [`agent.py`](../agent.py), `AuraAgent` queries `AuraMCPClient.list_tools()` at the start of each stateless request. Each tool exposes its snake_case `input_schema` JSON Schema (conforming to MCP Python SDK 2.0). The agent provides these schemas to the tool-selection planner so the LLM selects valid tool names and required parameters (`call_id`, `transcript`, `production_model_id`, `candidate_model_id`, etc.) and recovers gracefully if a tool returns a structured validation error.

---

## 8. Safe Logging & Fallback to `mock`

- **Zero Secret Leakage**: [`src/aura/logging_config.py`](../src/aura/logging_config.py) and all provider classes redact `api_key`, `apikey`, `Authorization`, and bearer tokens before writing to `stderr` or `logs/aura.log`.
- **Stdout Protection**: When running over MCP `stdio` transport, no log messages are ever written to `stdout`.
- **Graceful Fallback**: If an enterprise provider is selected without credentials and `AURA_FALLBACK_TO_MOCK=true`, `provider_factory.py` logs a warning to `stderr` and falls back to `MockLLMProvider` so demos and tests never crash.
