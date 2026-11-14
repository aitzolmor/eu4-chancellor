from pathlib import Path

from chancellor.config import DEFAULT_MODEL, load_settings


def test_reads_values_from_dotenv(tmp_path: Path, monkeypatch):
    for key in ("EU4_SAVE_DIR", "EU4_GAME_DIR", "ANTHROPIC_API_KEY", "CHANCELLOR_MODEL"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        '# comment\nEU4_SAVE_DIR="/saves"\nEU4_GAME_DIR=/games/eu4\nANTHROPIC_API_KEY=abc\n',
        encoding="utf-8",
    )

    settings = load_settings(env)

    assert settings.save_dir == Path("/saves")
    assert settings.game_dir == Path("/games/eu4")
    assert settings.api_key == "abc"
    assert settings.model == DEFAULT_MODEL


def test_environment_overrides_dotenv(tmp_path: Path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")

    assert load_settings(env).api_key == "from-env"


def test_missing_values_are_none(tmp_path: Path, monkeypatch):
    for key in ("EU4_SAVE_DIR", "EU4_GAME_DIR", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    settings = load_settings(tmp_path / "missing.env")

    assert settings.save_dir is None
    assert settings.game_dir is None
    assert settings.api_key is None


def test_budget_settings(tmp_path, monkeypatch):
    for key in ("CHANCELLOR_API_BUDGET_USD", "CHANCELLOR_QUESTION_CAP_USD"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text("CHANCELLOR_API_BUDGET_USD=4.5\nCHANCELLOR_QUESTION_CAP_USD=nope\n", "utf-8")
    settings = load_settings(env)
    assert settings.api_budget_usd == 4.5
    assert settings.question_cap_usd == 0.50  # unreadable values fall back to the default
