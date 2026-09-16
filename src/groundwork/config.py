"""
Central place every part of GroundWork (API, agent, poller) reads config from.

Why this exists instead of scattered `os.getenv()` calls:
  - One source of truth for what config the app needs. Read this file and you
    know every environment variable GroundWork depends on — no hunting through
    the codebase for os.getenv() calls hiding in random modules.
  - pydantic validates types and required-ness at import time, not at first
    use. A missing DATABASE_URL fails immediately with a clear error instead
    of crashing deep inside a request handler an hour into a demo.
  - Locally this reads from a `.env` file (see .env.example). In AWS, Lambda
    and AgentCore inject the same variable names from SSM Parameter Store —
    application code never has to know or care which one it's running under.
    That's "12-factor config": config lives in the environment, not in code.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path, not ".env" - a relative path resolves against whatever
# directory the process happens to be launched from (repo root when you
# run scripts by hand, but not necessarily under uvicorn --reload, an IDE
# run config, or a test runner). This file lives at src/groundwork/, so
# the repo root is two levels up. In production there's no .env at all -
# pydantic-settings just falls through to real environment variables, so
# this path simply won't exist there and that's fine.
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8")

    # Postgres connection string.
    # Local: docker-compose Postgres. Prod: Supabase, via SSM.
    database_url: str

    # local | production
    environment: str = "local"

    # debug | info | warning | error
    log_level: str = "info"

    # Region the Bedrock Runtime client targets. Matches where model access
    aws_region: str = "us-east-1"

    # Bedrock inference-profile ID for the resume-extraction utility
    bedrock_extraction_model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


@lru_cache
def get_settings() -> Settings:
    """
    Cached so every caller shares one validated Settings instance instead of
    re-reading and re-validating `.env` every time config is needed.
    """
    return Settings()
