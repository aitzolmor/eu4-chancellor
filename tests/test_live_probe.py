"""The probe mod and the game-log reader (D-044)."""

from pathlib import Path

from chancellor.live.gamelog import game_log_path, read_probe, render_probe
from chancellor.live.probe import FOLDER, LADDER_STEP, MOD_NAME, install, probe_files
from chancellor.save.parser import parse


def test_the_mod_files_parse_and_hook_the_monthly_pulse():
    files = probe_files()
    on_actions = parse(files["common/on_actions/zz_chancellor_probe.txt"])
    assert on_actions["on_monthly_pulse"]["events"] == ["chancellor_probe.1"]
    events = files["events/chancellor_probe.txt"]
    parsed = parse(events)
    event = parsed["country_event"]
    assert event["id"] == "chancellor_probe.1"
    assert event["hidden"] is True and event["is_triggered_only"] is True
    assert event["trigger"] == {"ai": False}
    # The ladder: one check every 5 points from -95 to 100.
    assert events.count("war_score_against") == len(range(-100 + LADDER_STEP, 101, LADDER_STEP))
    assert 'log = "CHANCELLOR|heartbeat|' in events
    assert f'name="{MOD_NAME}"' in files["descriptor.mod"]


def test_install_writes_the_mod_and_its_launcher_file(tmp_path: Path):
    written = install(tmp_path / "mod")
    assert (
        (tmp_path / "mod" / f"{FOLDER}.mod").read_text("utf-8").endswith(f'path="mod/{FOLDER}"\n')
    )
    assert (tmp_path / "mod" / FOLDER / "events" / "chancellor_probe.txt").is_file()
    assert len(written) == 4


LOG = """[eventwindow.cpp:486]: Selected event option 0 for event estate_regency_events.7
[effectimplementation.cpp:21890]: CHANCELLOR|heartbeat|1520|2|Austria
[effectimplementation.cpp:21890]: CHANCELLOR|treasury|603.350
[effectimplementation.cpp:21890]: CHANCELLOR|direct|12.500
[effectimplementation.cpp:21890]: CHANCELLOR|ladder|Gelre|35.000
[effectimplementation.cpp:21890]: CHANCELLOR|heartbeat|1520|3|Austria
[province.cpp:15513]: Santa Elena was colonized by Espa\xf1a in 1525.04.26
"""


def test_the_reader_answers_each_question(tmp_path: Path):
    log = tmp_path / "logs" / "game.log"
    log.parent.mkdir()
    log.write_bytes(LOG.encode("cp1252"))
    report = read_probe(log)
    assert report.heartbeats == [("1520", "2", "Austria"), ("1520", "3", "Austria")]
    assert (report.treasury, report.direct) == ("603.350", "12.500")
    assert report.ladder == {"Gelre": "35.000"}
    text = render_probe(report, log)
    assert "1. Monthly pulse: 2 heartbeats, from 1520.2 to 1520.3 (Austria)" in text
    assert "3b. War score, ladder (war_score_against every 5): Gelre 35.000" in text
    assert game_log_path(tmp_path / "save games") == log


def test_an_empty_log_explains_why(tmp_path: Path):
    log = tmp_path / "game.log"
    log.write_text("[x.cpp:1]: nothing\n", encoding="cp1252")
    assert "No Chancellor lines" in render_probe(read_probe(log), log)
