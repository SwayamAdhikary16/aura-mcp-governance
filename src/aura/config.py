"""Configuration management for AURA using environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class AuraConfig:
    """Immutable configuration loaded from environment variables."""

    env: str
    db_path: Path
    log_level: str
    log_file: Path
    max_transcript_length: int
    agent_max_turns: int
    demo_mode: bool
    mcp_transport: str
    mcp_host: str
    mcp_port: int
    llm_provider: str
    llm_timeout_seconds: int
    data_dir: Path

    @classmethod
    def from_env(cls, db_path_override: str | Path | None = None) -> "AuraConfig":
        """Load configuration from environment variables with safe defaults."""
        raw_db_path = db_path_override or os.getenv("AURA_DB_PATH", "data/aura.db")
        db_path = Path(raw_db_path)
        if not db_path.is_absolute():
            db_path = PROJECT_ROOT / db_path

        raw_log_file = os.getenv("AURA_LOG_FILE", "logs/aura.log")
        log_file = Path(raw_log_file)
        if not log_file.is_absolute():
            log_file = PROJECT_ROOT / log_file

        return cls(
            env=os.getenv("AURA_ENV", "development"),
            db_path=db_path,
            log_level=os.getenv("AURA_LOG_LEVEL", "INFO").upper(),
            log_file=log_file,
            max_transcript_length=int(os.getenv("AURA_MAX_TRANSCRIPT_LENGTH", "12000")),
            agent_max_turns=min(max(int(os.getenv("AURA_AGENT_MAX_TURNS", "8")), 1), 8),
            demo_mode=os.getenv("AURA_DEMO_MODE", "true").lower() in ("1", "true", "yes"),
            mcp_transport=os.getenv("AURA_MCP_TRANSPORT", "stdio").lower(),
            mcp_host=os.getenv("AURA_MCP_HOST", "127.0.0.1"),
            mcp_port=int(os.getenv("AURA_MCP_PORT", "8080")),
            llm_provider=os.getenv("AURA_LLM_PROVIDER", "mock").lower(),
            llm_timeout_seconds=int(os.getenv("AURA_LLM_TIMEOUT_SECONDS", "30")),
            data_dir=PROJECT_ROOT / "data",
        )


def get_config(db_path_override: str | Path | None = None) -> AuraConfig:
    """Return a fresh configuration instance."""
    return AuraConfig.from_env(db_path_override=db_path_override)
