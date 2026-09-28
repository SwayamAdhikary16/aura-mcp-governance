"""Structured error handling for AURA governance workflows."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class ErrorCode(str, Enum):
    """Canonical error codes for AURA controlled error handling."""

    MISSING_EXCEL_COLUMNS = "AURA_ERR_MISSING_EXCEL_COLUMNS"
    INVALID_FILE_TYPE = "AURA_ERR_INVALID_FILE_TYPE"
    EMPTY_TRANSCRIPT = "AURA_ERR_EMPTY_TRANSCRIPT"
    TRANSCRIPT_TOO_LONG = "AURA_ERR_TRANSCRIPT_TOO_LONG"
    DUPLICATE_CALL_ID = "AURA_ERR_DUPLICATE_CALL_ID"
    UNKNOWN_CALL_ID = "AURA_ERR_UNKNOWN_CALL_ID"
    UNKNOWN_MODEL_ID = "AURA_ERR_UNKNOWN_MODEL_ID"
    DISABLED_MODEL = "AURA_ERR_DISABLED_MODEL"
    NO_ACTIVE_ROUTING_POLICY = "AURA_ERR_NO_ACTIVE_ROUTING_POLICY"
    NO_ACTIVE_GOVERNANCE_POLICY = "AURA_ERR_NO_ACTIVE_GOVERNANCE_POLICY"
    INVALID_LLM_JSON = "AURA_ERR_INVALID_LLM_JSON"
    LLM_TIMEOUT = "AURA_ERR_LLM_TIMEOUT"
    MCP_CONNECTION_FAILURE = "AURA_ERR_MCP_CONNECTION_FAILURE"
    MCP_TOOL_FAILURE = "AURA_ERR_MCP_TOOL_FAILURE"
    DATABASE_LOCK = "AURA_ERR_DATABASE_LOCK"
    SPECIALIST_FAILURE = "AURA_ERR_SPECIALIST_FAILURE"
    CHALLENGER_FAILURE = "AURA_ERR_CHALLENGER_FAILURE"
    UNSUPPORTED_NL_REQUEST = "AURA_ERR_UNSUPPORTED_NL_REQUEST"
    VALIDATION_ERROR = "AURA_ERR_VALIDATION_ERROR"


class StructuredError(BaseModel):
    """Structured error payload safe for UI and MCP responses."""

    error_code: str = Field(..., description="Canonical AURA error code.")
    user_message: str = Field(..., description="Concise user-facing explanation without secrets or stack traces.")
    technical_message: str = Field(..., description="Sanitized technical details for logs and diagnostics.")
    retryable: bool = Field(default=False, description="Whether the operation can be safely retried.")
    safe_fallback: str | None = Field(
        default=None,
        description="Description of the safe fallback applied, if any.",
    )
    human_review_required: bool = Field(
        default=False,
        description="Whether this error requires human review of the call.",
    )
    correlation_id: str = Field(
        default_factory=lambda: f"corr-{uuid.uuid4().hex[:12]}",
        description="Correlation identifier for tracing across MCP and audit logs.",
    )
    details: dict[str, Any] = Field(default_factory=dict, description="Additional structured context.")


class AuraError(Exception):
    """Base exception carrying a StructuredError payload."""

    def __init__(
        self,
        error_code: ErrorCode | str,
        user_message: str,
        technical_message: str | None = None,
        retryable: bool = False,
        safe_fallback: str | None = None,
        human_review_required: bool = False,
        correlation_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        code_str = error_code.value if isinstance(error_code, ErrorCode) else str(error_code)
        super().__init__(user_message)
        self.structured = StructuredError(
            error_code=code_str,
            user_message=user_message,
            technical_message=technical_message or user_message,
            retryable=retryable,
            safe_fallback=safe_fallback,
            human_review_required=human_review_required,
            correlation_id=correlation_id or f"corr-{uuid.uuid4().hex[:12]}",
            details=details or {},
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize structured error to dictionary."""
        return self.structured.model_dump()
