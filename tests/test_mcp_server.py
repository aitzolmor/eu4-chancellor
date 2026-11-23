import asyncio
import json
import os
import shutil
from pathlib import Path

import pytest

from chancellor.app.cli import main
from chancellor.app.mcp_server import (
    SERVER_NAME,
    CampaignProvider,
    build_server,
    desktop_config,
)
from chancellor.config import Settings
from chancellor.context.campaign import Campaign
from chancellor.context.tools import TOOL_DEFINITIONS, Toolbox
from chancellor.game.missions import MissionLibrary
from chancellor.player.journal import journal_path
from chancellor.save.loader import load_save

FIXTURE = Path(__file__).parent / "fixtures" / "mini_save.txt"


@pytest.fixture
def save_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "user" / "save games"
    folder.mkdir(parents=True)
    shutil.copy(FIXTURE, folder / "mini.eu4")
    return folder


@pytest.fixture
def provider(save_dir: Path):
    loads = []

    def load(path: Path) -> Campaign:
        loads.append(path)
        return Campaign.from_raw(load_save(path))

    settings = Settings(save_dir=save_dir, game_dir=None, api_key=None)
    return CampaignProvider(settings, load), loads


def bump(path: Path) -> None:
    os.utime(path, (path.stat().st_mtime + 60,) * 2)


# --- provider --------------------------------------------------------------------------


def test_provider_loads_once_until_the_save_changes(provider, save_dir: Path):
    campaigns, loads = provider
    first = campaigns.toolbox()
    assert campaigns.toolbox() is first
    assert len(loads) == 1
    assert campaigns.save_path == save_dir / "mini.eu4"

    bump(save_dir / "mini.eu4")
    second = campaigns.toolbox()
    assert second is not first
    assert len(loads) == 2


def test_provider_follows_a_newer_save_file(provider, save_dir: Path):
    campaigns, _ = provider
    campaigns.toolbox()
    newer = save_dir / "newer.eu4"
    shutil.copy(FIXTURE, newer)
    bump(newer)
    campaigns.toolbox()
    assert campaigns.save_path == newer


def test_provider_records_each_new_save_in_the_journal(provider, save_dir: Path):
    campaigns, _ = provider
    toolbox = campaigns.toolbox()
    # The context and journal live in the game's user folder, next to "save games".
    assert toolbox.context_file.parent == save_dir.parent / "eu4-chancellor"
    assert journal_path(toolbox.context_file).is_file()


def test_provider_errors(tmp_path: Path):
    no_dir = CampaignProvider(Settings(save_dir=None, game_dir=None, api_key=None), None)
    with pytest.raises(RuntimeError, match="EU4_SAVE_DIR"):
        no_dir.toolbox()
    empty = tmp_path / "empty"
    empty.mkdir()
    no_saves = CampaignProvider(Settings(save_dir=empty, game_dir=None, api_key=None), None)
    with pytest.raises(RuntimeError, match="No .eu4 files"):
        no_saves.toolbox()


def test_reload_reuses_loaded_game_data(save_dir: Path):
    campaign = Campaign.from_raw(load_save(save_dir / "mini.eu4"))
    toolbox = Toolbox(campaign, Path("game"))
    library = MissionLibrary()
    toolbox.__dict__["_missions"] = library
    other = toolbox.with_campaign(campaign)
    assert other._missions is library
    assert "_decisions" not in other.__dict__


# --- server ----------------------------------------------------------------------------


def run(coroutine):
    return asyncio.run(coroutine)


def text_of(result) -> str:
    assert not result.is_error
    return "".join(getattr(block, "text", "") for block in result.content)


def test_server_lists_every_tool(provider):
    server = build_server(provider[0])
    tools = {tool.name: tool for tool in run(server.list_tools())}
    expected = {t["name"] for t in TOOL_DEFINITIONS} | {"get_save_status"}
    assert set(tools) == expected
    assert server.name == SERVER_NAME
    assert "Europa Universalis IV" in server.instructions
    writers = {name for name, tool in tools.items() if not tool.annotations.read_only_hint}
    # They write (D-039, D-041, D-061).
    assert writers == {
        "update_player_context",
        "create_watch",
        "track_goal",
        "show_chart",
        "prepare_action",  # records the action to verify (D-069)
        "verify_action",
    }
    assert tools["update_player_context"].annotations.destructive_hint is False
    assert set(tools["check_war"].input_schema["required"]) == {"target"}
    assert tools["check_war"].description == next(
        t["description"] for t in TOOL_DEFINITIONS if t["name"] == "check_war"
    )
    # A watch condition's fields are in the schema, not left to guess (D-041).
    condition = tools["create_watch"].input_schema["$defs"]["WatchCondition"]
    assert set(condition["required"]) == {"metric", "op", "value"}
    assert condition["properties"]["op"]["enum"] == [">=", "<=", "is"]
    assert "country" in condition["properties"] and "other" in condition["properties"]


def test_server_calls_tools(provider):
    server = build_server(provider[0])
    status = text_of(run(server.call_tool("get_save_status", {})))
    assert "Save: mini.eu4" in status
    assert "Date: 1471.10.2" in status
    war = text_of(run(server.call_tool("check_war", {"target": "TUR"})))
    assert war.startswith("# War check: HAB (HAB) vs TUR (TUR)")
    briefing = text_of(run(server.call_tool("get_country_briefing", {})))
    assert briefing.startswith("# Campaign briefing: HAB (HAB)")


def test_server_reports_lookup_errors_with_their_message(provider):
    from mcp.server.mcpserver.exceptions import ToolError

    server = build_server(provider[0])
    with pytest.raises(ToolError, match="No country named 'Narnia'"):
        run(server.call_tool("get_country_briefing", {"country": "Narnia"}))
    with pytest.raises(ToolError, match="EU4_GAME_DIR"):
        run(server.call_tool("get_missions", {}))


# --- configuration ---------------------------------------------------------------------


def test_desktop_config():
    settings = Settings(
        save_dir=Path("C:/saves"), game_dir=Path("C:/game"), api_key="secret", language="spanish"
    )
    entry = desktop_config(settings, executable="python.exe")["mcpServers"][SERVER_NAME]
    assert entry["command"] == "python.exe"
    assert entry["args"] == ["-m", "chancellor.app.cli", "mcp"]
    assert entry["env"] == {
        "EU4_SAVE_DIR": str(Path("C:/saves")),
        "EU4_GAME_DIR": str(Path("C:/game")),
        "EU4_LANGUAGE": "spanish",
    }
    assert "secret" not in json.dumps(entry)  # the API key is never written out


def test_mcp_config_command(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EU4_SAVE_DIR", str(tmp_path / "saves"))
    monkeypatch.delenv("EU4_GAME_DIR", raising=False)
    monkeypatch.delenv("EU4_LANGUAGE", raising=False)
    assert main(["mcp-config"]) == 0
    config = json.loads(capsys.readouterr().out)
    assert config["mcpServers"][SERVER_NAME]["env"] == {"EU4_SAVE_DIR": str(tmp_path / "saves")}
