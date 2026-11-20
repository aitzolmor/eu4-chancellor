"""The probe mod and the game-log reader (D-044)."""

from pathlib import Path

from chancellor.live.gamelog import game_log_path, read_probe, render_probe
from chancellor.live.probe import (
    DEFAULT_CB_TYPES,
    FOLDER,
    LADDER_STEP,
    MOD_NAME,
    cb_types_from,
    install,
    probe_files,
)
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


def test_the_casus_belli_check_covers_the_types_and_the_targets(tmp_path: Path):
    events = probe_files(["cb_core", "cb_conquest"])["events/chancellor_probe.txt"]
    parse(events)  # still valid game script
    assert events.count("has_casus_belli") == 4  # the player and each subject
    assert "has_casus_belli = { type = cb_conquest target = PREV }" in events
    assert 'log = "CHANCELLOR|cb|[This.GetTag]|cb_conquest"' in events
    assert 'log = "CHANCELLOR|cbtarget|[This.GetTag]|[This.GetName]"' in events
    for target in ("is_neighbor_of = ROOT", "is_rival = ROOT", "is_claim = ROOT"):
        assert target in events
    assert len(probe_files()["events/chancellor_probe.txt"].split("has_casus_belli")) == 33


def test_the_types_come_from_the_game_files(tmp_path: Path):
    folder = tmp_path / "common" / "cb_types"
    folder.mkdir(parents=True)
    (folder / "00_cb_types.txt").write_text(
        "# casus belli\ncb_core = {\n\tvalid_for_subject = no\n}\ncb_conquest = { }\n",
        encoding="cp1252",
    )
    assert cb_types_from(tmp_path) == ["cb_core", "cb_conquest"]
    assert cb_types_from(None) == list(DEFAULT_CB_TYPES)
    assert cb_types_from(tmp_path / "missing") == list(DEFAULT_CB_TYPES)


CB_LOG = """EVENT [1534.07.22]:CHANCELLOR|heartbeat|1534|julio|Austria
EVENT [1534.07.22]:CHANCELLOR|cbtarget|VEN|Venecia
EVENT [1534.07.22]:CHANCELLOR|cb|VEN|cb_core
EVENT [1534.08.22]:CHANCELLOR|heartbeat|1534|agosto|Austria
EVENT [1534.08.22]:CHANCELLOR|cbtarget|VEN|Venecia
EVENT [1534.08.22]:CHANCELLOR|cbtarget|HUN|Hungr\xeda
EVENT [1534.08.22]:CHANCELLOR|cb|HUN|cb_conquest
EVENT [1534.08.22]:CHANCELLOR|cb|HUN|cb_insult
"""


def test_the_reader_keeps_the_last_month_of_casus_belli(tmp_path: Path):
    log = tmp_path / "game.log"
    log.write_bytes(CB_LOG.encode("cp1252"))
    report = read_probe(log)
    assert report.last_date == "1534.08.22"
    assert report.cb_targets == {"VEN": "Venecia", "HUN": "Hungría"}
    assert report.casus_belli == {"HUN": ["cb_conquest", "cb_insult"]}
    text = render_probe(report, log)
    assert "4. Casus belli (has_casus_belli), last month: 2 countries checked, 1 with" in text
    assert "   - Hungría (HUN): cb_conquest, cb_insult" in text
    old = tmp_path / "old.log"
    old.write_text("EVENT [1534.07.22]:CHANCELLOR|treasury|1\n", encoding="cp1252")
    assert "no check ran" in render_probe(read_probe(old), old)


def test_subjects_are_checked_too():
    events = probe_files(["cb_conquest"])["events/chancellor_probe.txt"]
    parse(events)
    assert "every_subject_country = {" in events
    assert "save_event_target_as = chancellor_subject" in events
    assert (
        "event_target:chancellor_subject = { has_casus_belli = { type = cb_conquest "
        "target = PREV } }" in events
    )
    assert "NOT = { is_subject_of = ROOT }" in events


SUBJECT_LOG = """EVENT [1535.03.22]:CHANCELLOR|heartbeat|1535|marzo|Austria
EVENT [1535.03.22]:CHANCELLOR|cbtarget|POL|Polonia
EVENT [1535.03.22]:CHANCELLOR|cb|POL|cb_humiliate_rotw
EVENT [1535.03.22]:CHANCELLOR|subject|HUN|Hungr\xeda
EVENT [1535.03.22]:CHANCELLOR|subcb|POL|Polonia|cb_conquest
EVENT [1535.03.22]:CHANCELLOR|subject|ALB|Albania
EVENT [1535.03.22]:CHANCELLOR|subject|HOL|Holanda
EVENT [1535.03.22]:CHANCELLOR|subcb|LIE|Lieja|cb_conquest
"""


def test_the_reader_groups_casus_belli_by_subject(tmp_path: Path):
    log = tmp_path / "game.log"
    log.write_bytes(SUBJECT_LOG.encode("cp1252"))
    report = read_probe(log)
    assert report.subjects == {"HUN": "Hungría", "ALB": "Albania", "HOL": "Holanda"}
    assert report.subject_cb == {"HUN": {"POL": ["cb_conquest"]}, "HOL": {"LIE": ["cb_conquest"]}}
    text = render_probe(report, log)
    assert "5. Subjects' casus belli, last month: 3 subjects, 2 with at least one" in text
    assert "   - Hungría (HUN) against Polonia (POL): cb_conquest" in text
    assert "   - Holanda (HOL) against Lieja (LIE): cb_conquest" in text
