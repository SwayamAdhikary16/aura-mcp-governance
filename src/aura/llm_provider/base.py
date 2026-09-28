"""Abstract base class and JSON validation/repair lifecycle for AURA LLM providers."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Callable, TypeVar
from pydantic import BaseModel, ValidationError

from aura.errors import AuraError, ErrorCode
from aura.logging_config import get_logger
from aura.schemas import (
    ChallengerAnalysisResult,
    FirstPassResult,
    RoutineAnalysisResult,
    SpecialistAnalysisResult,
)

logger = get_logger("llm_provider")
T = TypeVar("T", bound=BaseModel)


class BaseLLMProvider(ABC):
    """Common interface for all AURA LLM providers (Mock, Kong, Bedrock, Azure OpenAI)."""

    provider_name: str = "base"

    @abstractmethod
    def _raw_first_pass(self, call_id: str, transcript: str, review_goal: str | None = None) -> str:
        """Return raw JSON string for first-pass triage."""

    @abstractmethod
    def _raw_routine_analysis(self, call_id: str, transcript: str, first_pass: FirstPassResult) -> str:
        """Return raw JSON string for routine call analysis."""

    @abstractmethod
    def _raw_specialist_analysis(
        self,
        call_id: str,
        transcript: str,
        first_pass: FirstPassResult,
        historical_context: dict[str, Any] | None = None,
    ) -> str:
        """Return raw JSON string for specialist deep analysis."""

    @abstractmethod
    def _raw_challenger_analysis(
        self,
        call_id: str,
        transcript: str,
        first_pass: FirstPassResult,
        primary_result: SpecialistAnalysisResult | RoutineAnalysisResult,
    ) -> str:
        """Return raw JSON string for challenger validation."""

    @abstractmethod
    def repair_json_response(self, broken_json: str, schema_name: str, error_details: str) -> str:
        """Attempt a single structured JSON repair when an LLM response fails parsing/validation."""

    @abstractmethod
    def run_candidate_model_analysis(
        self,
        call_id: str,
        transcript: str,
        candidate_model_id: str,
    ) -> dict[str, Any]:
        """Run synthetic or shadow candidate model evaluation for upgrade simulation."""

    def validate_with_single_repair(
        self,
        raw_json: str,
        schema_cls: type[T],
        call_id: str,
        on_retry_callback: Callable[[str, str], None] | None = None,
    ) -> tuple[T, bool]:
        """Validate LLM JSON output against `schema_cls`, attempting at most 1 repair on failure."""
        try:
            parsed = json.loads(raw_json)
            return schema_cls.model_validate(parsed), False
        except (json.JSONDecodeError, ValidationError, TypeError) as first_err:
            logger.warning(
                "Initial JSON validation failed for call_id=%s schema=%s: %s. Attempting 1 repair.",
                call_id,
                schema_cls.__name__,
                first_err,
            )
            if on_retry_callback:
                on_retry_callback(schema_cls.__name__, str(first_err))

            try:
                repaired_raw = self.repair_json_response(
                    broken_json=raw_json,
                    schema_name=schema_cls.__name__,
                    error_details=str(first_err),
                )
                repaired_parsed = json.loads(repaired_raw)
                validated = schema_cls.model_validate(repaired_parsed)
                logger.info("Single JSON repair succeeded for call_id=%s schema=%s", call_id, schema_cls.__name__)
                return validated, True
            except Exception as second_err:
                logger.error(
                    "JSON repair failed for call_id=%s schema=%s: %s",
                    call_id,
                    schema_cls.__name__,
                    second_err,
                )
                raise AuraError(
                    error_code=ErrorCode.INVALID_LLM_JSON,
                    user_message=(
                        f"Model response for stage '{schema_cls.__name__}' failed JSON schema validation "
                        "after one repair attempt. Call flagged for human review."
                    ),
                    technical_message=f"Initial error: {first_err} | Repair error: {second_err}",
                    retryable=False,
                    safe_fallback="Halt automated decision and require human governance review.",
                    human_review_required=True,
                ) from second_err

    def run_first_pass(
        self,
        call_id: str,
        transcript: str,
        review_goal: str | None = None,
        on_retry_callback: Callable[[str, str], None] | None = None,
    ) -> tuple[FirstPassResult, bool]:
        raw = self._raw_first_pass(call_id=call_id, transcript=transcript, review_goal=review_goal)
        return self.validate_with_single_repair(raw, FirstPassResult, call_id, on_retry_callback)

    def run_routine_analysis(
        self,
        call_id: str,
        transcript: str,
        first_pass: FirstPassResult,
        on_retry_callback: Callable[[str, str], None] | None = None,
    ) -> tuple[RoutineAnalysisResult, bool]:
        raw = self._raw_routine_analysis(call_id=call_id, transcript=transcript, first_pass=first_pass)
        return self.validate_with_single_repair(raw, RoutineAnalysisResult, call_id, on_retry_callback)

    def run_specialist_analysis(
        self,
        call_id: str,
        transcript: str,
        first_pass: FirstPassResult,
        historical_context: dict[str, Any] | None = None,
        on_retry_callback: Callable[[str, str], None] | None = None,
    ) -> tuple[SpecialistAnalysisResult, bool]:
        raw = self._raw_specialist_analysis(
            call_id=call_id,
            transcript=transcript,
            first_pass=first_pass,
            historical_context=historical_context,
        )
        return self.validate_with_single_repair(raw, SpecialistAnalysisResult, call_id, on_retry_callback)

    def run_challenger_analysis(
        self,
        call_id: str,
        transcript: str,
        first_pass: FirstPassResult,
        primary_result: SpecialistAnalysisResult | RoutineAnalysisResult,
        on_retry_callback: Callable[[str, str], None] | None = None,
    ) -> tuple[ChallengerAnalysisResult, bool]:
        raw = self._raw_challenger_analysis(
            call_id=call_id,
            transcript=transcript,
            first_pass=first_pass,
            primary_result=primary_result,
        )
        return self.validate_with_single_repair(raw, ChallengerAnalysisResult, call_id, on_retry_callback)
