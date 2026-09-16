"""
Smoke test for Layer 0: confirms the package installs correctly and Settings
loads/validates from environment variables. This should pass before anything
else gets built on top of it.
"""

from groundwork.config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")

    # _env_file=None: ignore any real .env on disk, so this test only depends
    # on the env vars we set above and stays deterministic in CI.
    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql://user:pass@localhost:5432/db"
    assert settings.environment == "local"
    assert settings.log_level == "info"
