"""Finding the game and the player's folder, and the user's config (D-047)."""

from pathlib import Path

import pytest

from chancellor import discovery
from chancellor.app.cli import main
from chancellor.config import load_settings, user_config_path, write_user_config
from chancellor.discovery import (
    GameInstall,
    find_game_installs,
    game_version,
    is_game_dir,
    steam_library_folders,
)


def _game(folder: Path, version: str | None = "v1.37.0.0") -> Path:
    (folder / "common").mkdir(parents=True)
    (folder / "eu4.exe").write_bytes(b"")
    if version:
        (folder / "launcher-settings.json").write_text(f'{{"rawVersion": "{version}"}}', "utf-8")
    return folder


def _user(folder: Path) -> Path:
    (folder / "save games").mkdir(parents=True)
    (folder / "settings.txt").write_text('language="l_spanish"\n', encoding="utf-8")
    return folder


def test_a_game_folder_and_its_version(tmp_path: Path):
    game = _game(tmp_path / "Europa Universalis IV")
    assert is_game_dir(game) and game_version(game) == "v1.37.0.0"
    assert not is_game_dir(tmp_path)
    assert game_version(tmp_path) is None
    assert GameInstall(game, "v1.37.0.0", "steam").version_key == (1, 37, 0, 0)
    assert GameInstall(game, None, "steam").version_key == (0,)


def test_steam_libraries_are_read_from_the_vdf():
    vdf = (
        '"libraryfolders"\n{\n "0" { "path" "C:\\\\Program Files (x86)\\\\Steam" }\n'
        ' "1" { "path" "D:\\\\SteamLibrary" }\n}\n'
    )
    assert steam_library_folders(vdf) == [
        Path("C:\\Program Files (x86)\\Steam"),
        Path("D:\\SteamLibrary"),
    ]


def test_the_newest_install_comes_first_and_each_once(tmp_path: Path, monkeypatch):
    old = _game(tmp_path / "old", "v1.30.2.0")
    new = _game(tmp_path / "new", "v1.37.0.0")
    monkeypatch.setattr(discovery, "_steam_candidates", lambda: [old, tmp_path / "missing"])
    monkeypatch.setattr(discovery, "_registry_candidates", lambda: [new])
    monkeypatch.setattr(discovery, "_usual_candidates", lambda: [new])  # seen twice
    installs = find_game_installs()
    assert [(i.path, i.found_by) for i in installs] == [
        (new, "installed programs"),
        (old, "steam"),
    ]


def test_settings_come_from_env_then_dotenv_then_the_user_config(tmp_path: Path, monkeypatch):
    for key in ("EU4_SAVE_DIR", "EU4_GAME_DIR", "EU4_LANGUAGE"):
        monkeypatch.delenv(key, raising=False)
    write_user_config({"EU4_SAVE_DIR": "/user/saves", "EU4_GAME_DIR": "/user/game"})
    dotenv = tmp_path / ".env"
    dotenv.write_text("EU4_GAME_DIR=/dotenv/game\n", encoding="utf-8")
    monkeypatch.setenv("EU4_LANGUAGE", "english")
    settings = load_settings(dotenv)
    assert settings.save_dir == Path("/user/saves")  # only in the user's config
    assert settings.game_dir == Path("/dotenv/game")  # .env wins over the user's config
    assert settings.language == "english"  # the environment wins over both


def test_writing_the_config_keeps_other_keys():
    write_user_config({"ANTHROPIC_API_KEY": "kept", "EU4_GAME_DIR": "/old"})
    path = write_user_config({"EU4_GAME_DIR": "/new"})
    assert path == user_config_path()
    text = path.read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=kept" in text and "EU4_GAME_DIR=/new" in text
    assert "EU4_GAME_DIR=/old" not in text


def test_setup_checks_and_writes(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)  # no .env here
    game = _game(tmp_path / "game")
    user = _user(tmp_path / "user")
    args = ["setup", "--game-dir", str(game), "--user-dir", str(user)]
    assert main([*args, "--check"]) == 0
    out = capsys.readouterr().out
    assert f"Game: {game} (version v1.37.0.0, given)" in out
    assert "(0 saves; current: none yet)" in out
    assert "Language: spanish" in out and "Nothing written (--check)." in out
    assert not user_config_path().exists()
    assert main(args) == 0
    assert "Every command now works from any folder." in capsys.readouterr().out
    settings = load_settings(tmp_path / "missing.env")
    assert (settings.game_dir, settings.save_dir) == (game, user / "save games")
    assert settings.language == "spanish"


@pytest.mark.parametrize(
    ("flag", "message"),
    [("--game-dir", "does not look like the game"), ("--user-dir", "data folder")],
)
def test_setup_explains_what_is_missing(tmp_path: Path, monkeypatch, capsys, flag, message):
    monkeypatch.chdir(tmp_path)
    good = {"--game-dir": _game(tmp_path / "game"), "--user-dir": _user(tmp_path / "user")}
    good[flag] = tmp_path / "nothing"
    args = ["setup", *(item for k, v in good.items() for item in (k, str(v)))]
    assert main(args) == 1
    assert message in capsys.readouterr().err
