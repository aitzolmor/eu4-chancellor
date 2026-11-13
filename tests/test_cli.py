import shutil
from pathlib import Path

import pytest

from chancellor import __version__
from chancellor.app import cli
from chancellor.app.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "mini_save.txt"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path: Path):
    """Keep the developer's real .env and environment out of CLI tests."""
    for key in ("EU4_SAVE_DIR", "EU4_GAME_DIR", "EU4_LANGUAGE", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


def make_save_dir(tmp_path: Path) -> Path:
    save_dir = tmp_path / "user" / "save games"
    save_dir.mkdir(parents=True)
    shutil.copy(FIXTURE, save_dir / "mini.eu4")
    return save_dir


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_chat_without_save_folder_fails_cleanly(capsys):
    assert main(["chat"]) == 1
    assert "EU4_SAVE_DIR" in capsys.readouterr().err


def test_summary_without_configuration_fails(capsys):
    assert main(["summary"]) == 1
    assert "EU4_SAVE_DIR" in capsys.readouterr().err


def test_summary_uses_save_dir(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setenv("EU4_SAVE_DIR", str(make_save_dir(tmp_path)))
    assert main(["summary"]) == 0
    assert "# Campaign briefing: HAB (HAB), 1471.10.2" in capsys.readouterr().out


def test_summary_explicit_save_and_output(tmp_path: Path, capsys):
    save = make_save_dir(tmp_path) / "mini.eu4"
    out = tmp_path / "briefing.md"
    assert main(["summary", "--save", str(save), "--output", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == capsys.readouterr().out


def test_summary_copy(monkeypatch, tmp_path: Path, capsys):
    copied = []
    monkeypatch.setattr(cli, "copy_to_clipboard", copied.append)
    save = make_save_dir(tmp_path) / "mini.eu4"
    assert main(["summary", "--save", str(save), "--copy"]) == 0
    assert copied and copied[0].startswith("# Campaign briefing")
    assert "copied to the clipboard" in capsys.readouterr().err


def test_summary_rejects_non_save(tmp_path: Path, capsys):
    bad = tmp_path / "bad.eu4"
    bad.write_text("nope", encoding="utf-8")
    assert main(["summary", "--save", str(bad)]) == 1
    assert "error:" in capsys.readouterr().err


def test_summary_uses_localisation(monkeypatch, tmp_path: Path, capsys):
    game = tmp_path / "game" / "localisation"
    game.mkdir(parents=True)
    (game / "countries_l_spanish.yml").write_text(
        'l_spanish:\n HAB:0 "Austria"\n', encoding="utf-8-sig"
    )
    save_dir = make_save_dir(tmp_path)
    (save_dir.parent / "settings.txt").write_text('language="l_spanish"\n', encoding="utf-8")
    monkeypatch.setenv("EU4_SAVE_DIR", str(save_dir))
    monkeypatch.setenv("EU4_GAME_DIR", str(tmp_path / "game"))

    assert main(["summary"]) == 0
    assert "# Campaign briefing: Austria (HAB)" in capsys.readouterr().out


# --- country ---------------------------------------------------------------------------


def make_game_dir(tmp_path: Path) -> Path:
    loc = tmp_path / "game" / "localisation"
    loc.mkdir(parents=True)
    (loc / "countries_l_spanish.yml").write_text(
        'l_spanish:\n HAB:0 "Austria"\n TUR:0 "Otomanos"\n BOH:0 "Bohemia"\n'
        ' BHU:0 "Bohemian Union"\n',
        encoding="utf-8-sig",
    )
    return tmp_path / "game"


@pytest.fixture
def configured(monkeypatch, tmp_path: Path) -> Path:
    save_dir = make_save_dir(tmp_path)
    (save_dir.parent / "settings.txt").write_text('language="l_spanish"\n', encoding="utf-8")
    monkeypatch.setenv("EU4_SAVE_DIR", str(save_dir))
    monkeypatch.setenv("EU4_GAME_DIR", str(make_game_dir(tmp_path)))
    return save_dir


def test_country_by_name(configured, capsys):
    assert main(["country", "otomanos"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Country briefing: Otomanos (TUR)")
    assert "## Relation to the player" in out


def test_country_by_tag(configured, capsys):
    assert main(["country", "TUR"]) == 0
    assert "# Country briefing: Otomanos (TUR)" in capsys.readouterr().out


def test_country_name_with_spaces(configured, capsys):
    assert main(["country", "Bohemian", "Union"]) == 0
    assert "# Country briefing: Bohemian Union (BHU)" in capsys.readouterr().out


def test_country_player_gets_campaign_briefing(configured, capsys):
    assert main(["country", "austria"]) == 0
    assert "# Campaign briefing: Austria (HAB)" in capsys.readouterr().out


def test_country_ambiguous(configured, capsys):
    assert main(["country", "bohem"]) == 1
    err = capsys.readouterr().err
    assert "matches several countries" in err
    assert "Bohemia (BOH)" in err


def test_country_unknown(configured, capsys):
    assert main(["country", "Narnia"]) == 1
    assert "No country named 'Narnia'" in capsys.readouterr().err


def test_country_copy(configured, monkeypatch, capsys):
    copied = []
    monkeypatch.setattr(cli, "copy_to_clipboard", copied.append)
    assert main(["country", "TUR", "--copy"]) == 0
    assert copied[0].startswith("# Country briefing: Otomanos (TUR)")
    assert "Briefing of Otomanos (TUR) copied" in capsys.readouterr().err


# --- war-check -------------------------------------------------------------------------


def test_war_check(configured, capsys):
    assert main(["war-check", "otomanos"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# War check: Austria (HAB) vs Otomanos (TUR)")
    assert "## Defenders" in out


def test_war_check_with_attacker(configured, capsys):
    assert main(["war-check", "Bohemia", "--attacker", "TUR"]) == 0
    assert "# War check: Otomanos (TUR) vs Bohemia (BOH)" in capsys.readouterr().out


def test_war_check_against_self(configured, capsys):
    assert main(["war-check", "austria"]) == 1
    assert "cannot declare war on itself" in capsys.readouterr().err


# --- world -----------------------------------------------------------------------------


def test_world(configured, capsys):
    assert main(["world", "--top", "3"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# World overview, 1471.10.2")
    assert "## Largest countries" in out


# --- missions --------------------------------------------------------------------------


def test_missions_need_game_dir(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setenv("EU4_SAVE_DIR", str(make_save_dir(tmp_path)))
    assert main(["missions"]) == 1
    assert "EU4_GAME_DIR" in capsys.readouterr().err


def test_missions_without_tree(configured, capsys):
    assert main(["missions", "--brief"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Missions: Austria (HAB)")
    assert "records no mission tree" in out


# --- decisions -------------------------------------------------------------------------


def test_decisions_need_game_dir(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setenv("EU4_SAVE_DIR", str(make_save_dir(tmp_path)))
    assert main(["decisions"]) == 1
    assert "EU4_GAME_DIR" in capsys.readouterr().err


def test_decisions(configured, tmp_path: Path, capsys):
    folder = tmp_path / "game" / "decisions"
    folder.mkdir()
    (folder / "d.txt").write_text(
        "country_decisions = { form_x = { major = yes potential = { tag = HAB } "
        "allow = { adm_tech = 1 } effect = { change_tag = XXX } } }",
        encoding="utf-8",
    )
    assert main(["decisions", "--formables"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Decisions: Austria (HAB)")
    assert "forms XXX (XXX)" in out


def test_clear_cache_command(isolated_cache: Path, capsys):
    isolated_cache.mkdir()
    (isolated_cache / "x-123.pickle").write_bytes(b"x")
    assert main(["clear-cache"]) == 0
    assert "Removed 1 cached file(s)" in capsys.readouterr().err
    assert not list(isolated_cache.glob("*.pickle"))


# --- targets ---------------------------------------------------------------------------


def test_targets_need_game_dir(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setenv("EU4_SAVE_DIR", str(make_save_dir(tmp_path)))
    assert main(["targets"]) == 1
    assert "EU4_GAME_DIR" in capsys.readouterr().err


def test_targets(configured, capsys):
    assert main(["targets"]) == 0
    assert capsys.readouterr().out.startswith("# Expansion targets: Austria (HAB)")
