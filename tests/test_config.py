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


def test_dig_missing_key_is_none():
    assert config._dig({"a": {"b": 1}}, ("a", "c")) is None
    assert config._dig({"a": "scalar"}, ("a", "b")) is None


def test_provider_key_selects_by_provider(monkeypatch):
    monkeypatch.setattr(config, "PROVIDER", "openrouter")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "or-key")
    assert config.provider_key() == "or-key"


def test_require_fails_loud_lists_all_missing(monkeypatch):
    monkeypatch.setattr(config, "PROVIDER", "anthropic")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(config, "DISCORD_BOT_TOKEN", None)
    monkeypatch.setattr(config, "OWNER_ID", None)
    with pytest.raises(SystemExit) as exc:
        config.require()
    message = str(exc.value)
    assert "anthropic api key" in message
    assert "discord token" in message
    assert "owner_id" in message


def test_require_unknown_provider(monkeypatch):
    monkeypatch.setattr(config, "PROVIDER", "bogus")
    with pytest.raises(SystemExit) as exc:
        config.require()
    assert "Unknown provider" in str(exc.value)


def test_require_passes_when_satisfied(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROVIDER", "anthropic")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(config, "DISCORD_BOT_TOKEN", "t")
    monkeypatch.setattr(config, "OWNER_ID", 42)
    monkeypatch.setattr(config, "KIRI_HOME", str(tmp_path / "home"))
    config.require()  # must not raise
