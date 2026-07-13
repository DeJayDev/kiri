import pytest

from kiri import config


def test_get_precedence_env_over_toml_over_default(monkeypatch):
    monkeypatch.setattr(config, "_toml", {"model": {"name": "from-toml"}})
    monkeypatch.delenv("KIRI_MODEL", raising=False)
    assert config._get("KIRI_MODEL", "default", "model", "name") == "from-toml"

    monkeypatch.setenv("KIRI_MODEL", "from-env")
    assert config._get("KIRI_MODEL", "default", "model", "name") == "from-env"

    monkeypatch.setattr(config, "_toml", {})
    monkeypatch.delenv("KIRI_MODEL", raising=False)
    assert config._get("KIRI_MODEL", "default", "model", "name") == "default"


def test_stale_finds_settings_nothing_reads(monkeypatch):
    # A key kiri dropped stays in the file and silently stops doing anything. The
    # owner has no way to tell it went dead.
    monkeypatch.setattr(
        config,
        "_toml",
        {
            "shell": {"timeout": 120, "max_timeout": 3600},
            "model": {"name": "claude-opus-4-8"},
            "providers": {"anthropic": {"api_key": "k"}},
        },
    )
    assert config.stale() == [("shell", "max_timeout"), ("shell", "timeout")]


def test_require_asks_the_provider_what_it_needs(monkeypatch):
    monkeypatch.setattr(config, "PROVIDER", "openrouter")
    monkeypatch.setattr(config, "SUMMARY_PROVIDER", None)
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", None)
    monkeypatch.setattr(config, "DISCORD_BOT_TOKEN", "t")
    monkeypatch.setattr(config, "OWNER_ID", 1)
    with pytest.raises(SystemExit) as exc:
        config.require()
    assert "openrouter api key" in str(exc.value)


def test_require_rejects_an_unknown_provider(monkeypatch):
    monkeypatch.setattr(config, "PROVIDER", "gemini")
    monkeypatch.setattr(config, "SUMMARY_PROVIDER", None)
    with pytest.raises(SystemExit) as exc:
        config.require()
    assert "Unknown provider" in str(exc.value)


def test_require_also_validates_the_summary_provider(monkeypatch):
    monkeypatch.setattr(config, "PROVIDER", "anthropic")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(config, "SUMMARY_PROVIDER", "openai")
    monkeypatch.setattr(config, "OPENAI_API_KEY", None)
    monkeypatch.setattr(config, "DISCORD_BOT_TOKEN", "t")
    monkeypatch.setattr(config, "OWNER_ID", 1)
    with pytest.raises(SystemExit) as exc:
        config.require()
    assert "openai api key" in str(exc.value)
