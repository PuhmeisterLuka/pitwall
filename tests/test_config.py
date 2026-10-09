from dataclasses import fields
from pathlib import Path

import pytest

from pitwall.config import Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for field in fields(Settings):
        monkeypatch.delenv(f"PITWALL_{field.name.upper()}", raising=False)


def test_defaults_without_env():
    assert Settings.from_env() == Settings()


def test_env_overrides_keep_their_types(monkeypatch):
    monkeypatch.setenv("PITWALL_TIMEOUT_S", "2.5")
    monkeypatch.setenv("PITWALL_MAX_RETRIES", "5")
    monkeypatch.setenv("PITWALL_CACHE_PATH", "data/cache.sqlite3")

    settings = Settings.from_env()

    assert settings.timeout_s == 2.5
    assert settings.max_retries == 5
    assert settings.cache_path == Path("data/cache.sqlite3")


def test_bad_value_names_the_variable(monkeypatch):
    monkeypatch.setenv("PITWALL_MAX_RETRIES", "lots")
    with pytest.raises(ValueError, match="PITWALL_MAX_RETRIES='lots' is not a valid int"):
        Settings.from_env()
