"""Amazon Bedrock LLM Provider template for AURA."""

from __future__ import annotations

import os
from typing import Any

from aura.llm_provider.base import BaseLLMProvider
from aura.llm_provider.mock_provider import MockLLMProvider
from aura.schemas import FirstPassResult, RoutineAnalysisResult, SpecialistAnalysisResult


class BedrockLLMProvider(BaseLLMProvider):
    """Enterprise Amazon Bedrock Converse API provider template."""

    provider_name = "bedrock"

    def __init__(self) -> None:
        self.region = os.getenv("AWS_REGION", "us-east-1")
        self.access_key = os.getenv("AWS_ACCESS_KEY_ID", "")
        self.fast_model_id = os.getenv("BEDROCK_FAST_MODEL_ID", "placeholder.model-fast-v1:0")
        self.deep_model_id = os.getenv("BEDROCK_DEEP_MODEL_ID", "placeholder.model-deep-v1:0")
        self.challenger_model_id = os.getenv("BEDROCK_CHALLENGER_MODEL_ID", "placeholder.model-challenger-v1:0")
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
