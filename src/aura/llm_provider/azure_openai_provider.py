"""Azure OpenAI LLM Provider template for AURA."""

from __future__ import annotations

import os
from typing import Any

from aura.llm_provider.base import BaseLLMProvider
from aura.llm_provider.mock_provider import MockLLMProvider
from aura.schemas import FirstPassResult, RoutineAnalysisResult, SpecialistAnalysisResult


class AzureOpenAIProvider(BaseLLMProvider):
    """Enterprise Azure OpenAI provider template."""

    provider_name = "azure_openai"

    def __init__(self) -> None:
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
        self.fast_deployment = os.getenv("AZURE_OPENAI_FAST_DEPLOYMENT", "placeholder-fast-deployment")
        self.deep_deployment = os.getenv("AZURE_OPENAI_DEEP_DEPLOYMENT", "placeholder-deep-deployment")
        self.challenger_deployment = os.getenv("AZURE_OPENAI_CHALLENGER_DEPLOYMENT", "placeholder-challenger-deployment")
        self._fallback = MockLLMProvider()

    def _raw_first_pass(self, call_id: str, transcript: str, review_goal: str | None = None) -> str:
        return self._fallback._raw_first_pass(call_id, transcript, review_goal)

    def _raw_routine_analysis(self, call_id: str, transcript: str, first_pass: FirstPassResult) -> str:
        return self._fallback._raw_routine_analysis(call_id, transcript, first_pass)

    def _raw_specialist_analysis(
        self,
        call_id: str,
        transcript: str,
        first_pass: FirstPassResult,
        historical_context: dict[str, Any] | None = None,
    ) -> str:
        return self._fallback._raw_specialist_analysis(call_id, transcript, first_pass, historical_context)

    def _raw_challenger_analysis(
        self,
        call_id: str,
        transcript: str,
        first_pass: FirstPassResult,
        primary_result: SpecialistAnalysisResult | RoutineAnalysisResult,
    ) -> str:
        return self._fallback._raw_challenger_analysis(call_id, transcript, first_pass, primary_result)

    def repair_json_response(self, broken_json: str, schema_name: str, error_details: str) -> str:
        return self._fallback.repair_json_response(broken_json, schema_name, error_details)

    def run_candidate_model_analysis(
        self,
        call_id: str,
        transcript: str,
        candidate_model_id: str,
    ) -> dict[str, Any]:
        return self._fallback.run_candidate_model_analysis(call_id, transcript, candidate_model_id)
