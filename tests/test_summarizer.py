import shutil
from pathlib import Path

import pytest

from chancellor.context.summarizer import summarize_save
from chancellor.game.localisation import Localisation
from chancellor.save.loader import load_save

FIXTURE = Path(__file__).parent / "fixtures" / "mini_save.txt"


@pytest.fixture
def raw(tmp_path: Path):
    path = tmp_path / "mini.eu4"
    shutil.copy(FIXTURE, path)
    return load_save(path)


@pytest.fixture
def briefing(raw) -> str:
    loc = Localisation(
        {"HAB": "Austria", "TUR": "Ottomans", "PROV134": "Wien", "PROV150": "Nikopol"}
    )
    return summarize_save(raw, loc)


def test_header(briefing: str):
    assert briefing.startswith("# Campaign briefing: Austria (HAB), 1471.10.2")
    assert "- Capital: Wien" in briefing
    assert "Great Power, rank #7 in score" in briefing


def test_ruler_resolved_from_history(briefing: str):
    assert "- Ruler: Ladislaus von Habsburg (3/3/2), age 31" in briefing
    assert "industrious personality" in briefing  # humanised when not localised


def test_economy(briefing: str):
    assert "- Treasury: 36.1 ducats" in briefing
    assert "- Last month balance: +1.7 ducats" in briefing
    assert "- Loans: 2 totalling 176.0 ducats" in briefing


def test_military(briefing: str):
    assert "- Manpower: 63,781 / 63,781" in briefing
    assert "- Land forces: 3 regiments in 2 armies" in briefing
    assert "- Navy: 1 ships in 1 fleets" in briefing


def test_only_player_wars_are_listed(briefing: str):
    assert "Austrian Conquest of Nikopol" in briefing
    assert "we are attacker" in briefing
    assert "Nikopol" in briefing
    assert "Unrelated war" not in briefing


def test_key_countries_table(briefing: str):
    assert "| Ottomans (TUR) | our rival, rivals us, at war | 498 | 2 | 6 | -25" in briefing
    assert "| BOH (BOH) | ally, neighbour | 170 | 1 | 5 | +150" in briefing
    assert "| HUN (HUN) | subject, neighbour | 298 | 0 | 5 | +42" in briefing


def test_dynamic_country_uses_name_from_save(raw):
    from chancellor.context.summarizer import _Context

    ctx = _Context(
        tag="HAB",
        date="1471.10.2",
        country={},
        countries={"C00": {"name": "Austrian Antilles"}},
        gamestate={},
        loc=Localisation(),
    )
    assert ctx.name("C00") == "Austrian Antilles"
    assert ctx.name("HAB") == "HAB"


def test_works_without_localisation(raw):
    text = summarize_save(raw)
    assert "# Campaign briefing: HAB (HAB)" in text


def test_peace_when_no_wars(tmp_path: Path):
    path = tmp_path / "peace.eu4"
    text = FIXTURE.read_text(encoding="cp1252").split("active_war=")[0]
    path.write_bytes(text.encode("cp1252"))
    assert "At peace." in summarize_save(load_save(path))
