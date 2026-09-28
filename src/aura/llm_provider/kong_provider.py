"""Synchrony Kong AI Gateway LLM Provider template for AURA."""

from __future__ import annotations

import json
import os
from typing import Any
import httpx

from aura.llm_provider.base import BaseLLMProvider
from aura.llm_provider.mock_provider import MockLLMProvider
from aura.prompts import (
    challenger_system_prompt,
    challenger_user_prompt,
    first_pass_system_prompt,
    first_pass_user_prompt,
    single_analysis_system_prompt,
    single_analysis_user_prompt,
    split_analysis_system_prompt,
    split_analysis_user_prompt,
)
from aura.schemas import FirstPassResult, RoutineAnalysisResult, SpecialistAnalysisResult


class KongAIProvider(BaseLLMProvider):
    """Enterprise Kong AI Gateway provider implementation with safe offline fallback."""

    provider_name = "kong"

    def __init__(self) -> None:
        self.gateway_url = os.getenv("KONG_AI_GATEWAY_URL", "")
        self.api_key = os.getenv("KONG_API_KEY", "")
        self.route_fast = os.getenv("KONG_ROUTE_FAST", "aura-fast-route-placeholder")
        self.route_deep = os.getenv("KONG_ROUTE_DEEP", "aura-deep-route-placeholder")
        self.route_challenger = os.getenv("KONG_ROUTE_CHALLENGER", "aura-challenger-route-placeholder")
        self.timeout = float(os.getenv("AURA_LLM_TIMEOUT_SECONDS", "30"))
        self._fallback = MockLLMProvider()

    def _is_placeholder(self) -> bool:
        return (
            not self.gateway_url
            or "placeholder" in self.gateway_url.lower()
            or not self.api_key
            or "placeholder" in self.api_key.lower()
        )

    def _invoke_kong(self, route: str, system_prompt: str, user_prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Kong-AI-Route": route,
            "Content-Type": "application/json",
        }
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self.gateway_url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    def _raw_first_pass(self, call_id: str, transcript: str, review_goal: str | None = None) -> str:
        if self._is_placeholder():
            return self._fallback._raw_first_pass(call_id, transcript, review_goal)
        return self._invoke_kong(
            self.route_fast,
            first_pass_system_prompt(),
            first_pass_user_prompt(call_id, transcript, review_goal),
        )

    def _raw_routine_analysis(self, call_id: str, transcript: str, first_pass: FirstPassResult) -> str:
        if self._is_placeholder():
            return self._fallback._raw_routine_analysis(call_id, transcript, first_pass)
        return self._invoke_kong(
            self.route_fast,
            single_analysis_system_prompt(),
            single_analysis_user_prompt(call_id, transcript, first_pass.model_dump_json()),
        )

    def _raw_specialist_analysis(
        self,
        call_id: str,
        transcript: str,
        first_pass: FirstPassResult,
        historical_context: dict[str, Any] | None = None,
    ) -> str:
        if self._is_placeholder():
            return self._fallback._raw_specialist_analysis(call_id, transcript, first_pass, historical_context)
        return self._invoke_kong(
            self.route_deep,
            split_analysis_system_prompt(),
            split_analysis_user_prompt(
                call_id,
                transcript,
                first_pass.model_dump_json(),
                json.dumps(historical_context) if historical_context else None,
            ),
        )

    def _raw_challenger_analysis(
        self,
        call_id: str,
        transcript: str,
        first_pass: FirstPassResult,
        primary_result: SpecialistAnalysisResult | RoutineAnalysisResult,
    ) -> str:
        if self._is_placeholder():
            return self._fallback._raw_challenger_analysis(call_id, transcript, first_pass, primary_result)
        return self._invoke_kong(
            self.route_challenger,
            challenger_system_prompt(),
            challenger_user_prompt(
                call_id,
                transcript,
                first_pass.model_dump_json(),
                primary_result.model_dump_json(),
            ),
        )

    def repair_json_response(self, broken_json: str, schema_name: str, error_details: str) -> str:
        if self._is_placeholder():
            return self._fallback.repair_json_response(broken_json, schema_name, error_details)
        return self._invoke_kong(
            self.route_fast,
            "Repair the provided JSON so it strictly conforms to the schema. Output valid JSON only.",
            f"Schema: {schema_name}\nError: {error_details}\nBroken JSON:\n{broken_json}",
        )

    def run_candidate_model_analysis(
        self,
        call_id: str,
        transcript: str,
        candidate_model_id: str,
    ) -> dict[str, Any]:
        return self._fallback.run_candidate_model_analysis(call_id, transcript, candidate_model_id)
