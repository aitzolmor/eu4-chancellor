from pathlib import Path

from chancellor.config import DEFAULT_MODEL, load_settings


def test_reads_values_from_dotenv(tmp_path: Path, monkeypatch):
    for key in ("EU4_SAVE_DIR", "ANTHROPIC_API_KEY", "CHANCELLOR_MODEL"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text('# comment\nEU4_SAVE_DIR="/saves"\nANTHROPIC_API_KEY=abc\n', encoding="utf-8")

    settings = load_settings(env)

    assert settings.save_dir == Path("/saves")
    assert settings.api_key == "abc"
    assert settings.model == DEFAULT_MODEL


def test_environment_overrides_dotenv(tmp_path: Path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")

    assert load_settings(env).api_key == "from-env"


def test_missing_values_are_none(tmp_path: Path, monkeypatch):
    for key in ("EU4_SAVE_DIR", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    settings = load_settings(tmp_path / "missing.env")

    assert settings.save_dir is None
    assert settings.api_key is None
