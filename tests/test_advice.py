"""Structured action recommendations (Phase 6, "Advise"; D-056)."""

from pathlib import Path

from chancellor.context.advice import Goal, goals_from, recommend, render_recommendations
from chancellor.context.alerts import ReadyNow
from chancellor.context.campaign import Campaign
from chancellor.context.coring import CoringCost
from chancellor.context.ledger import Ledger
from chancellor.context.power import PowerReport, TechCost
from chancellor.context.targets import Target, TargetReport
from chancellor.context.tools import Toolbox
from chancellor.context.war_check import CoalitionRisk
from chancellor.game.localisation import Localisation
from chancellor.save.parser import parse

WORLD = """
countries={
    HAB={ treasury=300.0 overextension_percentage=0.06 loan={ amount=200 interest=4 } }
    POL={ } LIE={ } TEU={ } SWI={ } LBV={ } UBV={ }
}
"""
NAMES = {
    "HAB": "Austria",
    "POL": "Polonia",
    "LIE": "Lieja",
    "TEU": "Orden Teutónica",
    "NAP": "Nápoles",
    "hab_milan_title": "Ducado de Milán",
    "cb_conquest": "Conquista",
}


class _Cb:
    """A stand-in for the probe mod's check: a conquest casus belli on Liège only."""

    def against(self, target: str) -> list[tuple[str | None, str]]:
        return [(None, "cb_conquest")] if target == "LIE" else []

    def covers(self, target: str) -> bool:
        return target in ("LIE", "POL")


def _campaign() -> Campaign:
    campaign = Campaign({"player": "HAB", "date": "1535.8.2"}, parse(WORLD), Localisation(NAMES))
    return campaign


def _power(adm: int = 111) -> PowerReport:
    return PowerReport(
        points={"adm": adm, "dip": 950, "mil": 400},
        monthly={"adm": 8.0, "dip": 9.0, "mil": 10.0},
        monthly_parts={},
        techs={
            "adm": TechCost("adm", 10, 1518, 531),
            "dip": TechCost("dip", 9, 1505, 477),
            "mil": TechCost("mil", 11, 1550, 300, months_ahead=120),
        },
        idea_cost=400,
        ideas_taken=10,
        idea_groups=[("Aristocratic", 7), ("Quality", 3)],
        idea_slots=2,
        next_slot=None,
        stability_cost=100,
        general_cost=50,
        leaders=[],
        free_leaders=0,
        leader_upkeep=0.0,
        advisors=[],
        stability=1.0,
    )


def _target(owner: str, odds: tuple[int, int], reasons: list[str], level: str = "low") -> Target:
    return Target(
        owner=owner,
        provinces=[1, 2],
        development=40.0,
        reasons=reasons,
        attacker_regiments=odds[0],
        defender_regiments=odds[1],
        coalition_risk=CoalitionRisk(level, 0.0, [], 0, False),  # type: ignore[arg-type]
    )


def _inputs() -> dict:
    return {
        "ready": ReadyNow(missions=["hab_milan"]),
        "power": _power(),
        "coring": [CoringCost(1, "Widin", 10.0, 35, 32, True, False)],
        "ledger": Ledger(
            "HAB",
            last_month_income={"Taxation": 25.0, "War reparations": 10.4},
            last_month_expenses={"Army maintenance": 35.1},
            recurring_income=35.4,
            recurring_expenses=40.0,
        ),
        "targets": TargetReport(
            "HAB",
            "1535.8.2",
            [
                _target("POL", (250, 90), ["mission: Ducado de Milán (any 3)"]),  # ready
                _target("LIE", (250, 100), ["claims"], "medium"),
                _target("TEU", (250, 50), ["formable: Alemania"]),
                _target("SWI", (250, 200), ["claims"]),  # odds too low
            ],
            [],
        ),
        "casus_belli": _Cb(),
        "goals": [Goal(2, "Ir a por Nápoles; antes, expandirse por Lieja")],
    }


def test_the_rules_and_their_order():
    found = recommend(_campaign(), **_inputs())
    now = {r.kind for r in found if r.priority == "now"}
    assert now == {"complete_mission", "fix_deficit", "buy_technology"}
    priorities = [r.priority for r in found]
    assert priorities == sorted(priorities, key=["now", "soon", "consider"].index)
    by_kind = {r.kind: r for r in found}
    assert by_kind["complete_mission"].action == "Complete the mission «Ducado de Milán»"
    assert by_kind["fix_deficit"].reasons[0] == "recurring balance -4.60 ducats a month"
    assert by_kind["repay_loan"].priority == "soon"
    assert by_kind["plan_income"].priority == "consider"
    assert by_kind["core_province"].action == "Core Widin"
    assert (
        "Widin 35 adm, 32 months; you have 111 administrative power"
        in (by_kind["core_province"].reasons[1])
    )
    techs = [r for r in found if r.kind == "buy_technology"]
    assert [(r.target, r.priority) for r in techs] == [("dip", "now")]  # capped; mil ahead
    assert [r.target for r in found if r.kind == "buy_idea"] == ["dip"]


def test_war_targets_use_the_casus_belli_and_skip_ready_missions():
    found = recommend(_campaign(), **_inputs())
    wars = [r for r in found if r.kind in ("declare_war", "get_casus_belli")]
    assert [(r.kind, r.target, r.priority) for r in wars] == [
        ("declare_war", "LIE", "soon"),  # has a conquest casus belli
        ("declare_war", "TEU", "consider"),  # not checked by the mod
    ]
    liege = wars[0]
    assert "casus belli: Conquista" in liege.reasons
    assert "coalition risk: medium" in liege.reasons
    assert liege.goals == [2]  # the goal names Lieja
    assert all(r.target != "POL" for r in wars)  # its only reason is a ready mission


def test_without_inputs_only_what_the_save_alone_gives():
    assert recommend(_campaign()) == []
    text = render_recommendations(_campaign(), [], [], missing=["casus belli"])
    assert "Nothing stands out" in text and "Not covered here: casus belli." in text


def test_rendering():
    campaign = _campaign()
    inputs = _inputs()
    found = recommend(campaign, **inputs)
    text = render_recommendations(campaign, found, inputs["goals"])
    assert text.startswith("# What to do now: Austria (HAB), 1535.8.2")
    assert "Recorded goals: #2 Ir a por Nápoles" in text
    assert "## Now" in text and "## Soon" in text and "## To consider" in text
    assert "**War on Lieja** (goal #2) `[declare_war LIE]`" in text
    assert "   - Details: check_war" in text


def test_goals_come_from_the_context_entries():
    class Entry:
        def __init__(self, id: int, kind: str, text: str) -> None:
            self.id, self.kind, self.text = id, kind, text

    entries = [Entry(1, "goal", "Gelre"), Entry(2, "note", "x"), Entry(3, "goal", "Nápoles")]
    assert goals_from(entries) == [Goal(1, "Gelre"), Goal(3, "Nápoles")]


def test_the_tool_without_game_files(tmp_path: Path):
    toolbox = Toolbox(_campaign(), None, tmp_path / "context.json")
    text = toolbox.run("get_recommendations", {})
    assert text.startswith("# What to do now: Austria (HAB)")
    assert "no game files" in text
    assert "Repay a loan" in text  # the budget comes from the save alone


def test_a_mission_whose_reward_improves_later_is_a_timing_choice():
    from chancellor.context.missions import (
        MissionColumn,
        MissionState,
        MissionTree,
        RewardCondition,
    )
    from chancellor.game.missions import Mission

    mission = Mission(name="hab_milan", series="s", position=1, required=[])
    state = MissionState(mission, "Ducado de Milán", "available", [])
    state.reward_conditions = [
        RewardCondition(
            False,
            ["- Polonia: Not: development 300"],
            ["- add_casus_belli:", "  - type: cb_restore_personal_union"],
            ["Polonia: development with its subjects 695, needs less than 300"],
        )
    ]
    tree = MissionTree("HAB", [MissionColumn(1, ["s"], [state])], [])
    inputs = {**_inputs(), "tree": tree}
    inputs["targets"].targets[0].reasons = ["mission: Ducado de Milán (any 3)"]
    found = recommend(_campaign(), **inputs)
    timing = next(r for r in found if r.kind == "time_mission")
    assert timing.priority == "soon"
    assert timing.action == "Complete «Ducado de Milán» now, or wait for the better reward"
    assert "now Polonia: development with its subjects 695, needs less than 300" in timing.reasons
    assert not any(r.kind == "complete_mission" for r in found)
    # Poland is a target again: shrinking it brings the better reward closer.
    poland = next(r for r in found if r.target == "POL")
    assert any("brings a mission's better reward closer" in reason for reason in poland.reasons)
