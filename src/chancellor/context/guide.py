"""Guide: the game's screens and buttons for each recommendation (Phase 6; D-059).

The second rung of the vision's ladder (Advise, Guide, Act). A recommendation has a
stable ``kind`` and ``target`` (D-056); this module turns them into steps in the game's
interface, naming every screen and button with the game's own text in the player's
language, read from its localisation files, so the steps match what the player sees.

Only what the game's files settle is used: F1 opens the country screen (``topbar.gui``);
the tabs and buttons are named by their localisation keys. The other tabs' function keys
live in the game's code, not its files, so the steps go through F1 and the tab.
"""

from __future__ import annotations

from chancellor.context.alerts import title
from chancellor.context.campaign import Campaign

# Interface text: localisation key, and the English fallback when the key is missing.
UI: dict[str, tuple[str, str]] = {
    "court": ("HEADER_COURT", "Court"),
    "diplomacy": ("HEADER_DIPLOMACY", "Diplomacy"),
    "economy": ("HEADER_ECONOMY", "Economy"),
    "technology": ("HEADER_TECHNOLOGY", "Technology"),
    "ideas": ("HEADER_IDEAS", "Ideas"),
    "missions": ("HEADER_MISSIONS", "Missions"),
    "decisions": ("HEADER_MISSION_REMOVE", "Decisions"),
    "stability": ("HEADER_STABILITY_EXPANSION", "Stability and Expansion"),
    "declare_war": ("WARTITLE", "Declare War"),
    "sue_for_peace": ("PEACETITLE", "Sue for Peace"),
    "improve_relations": ("HINT_IMPROVERELATIONS_TITLE", "Improve Relations"),
    "fabricate_claim": ("FABRICATE_CLAIM", "Fabricate Claim"),
    "make_core": ("CV_BUILD_CORE", "Make core"),
    "repay_loan": ("CV_REPAY_LOAN", "Repay Loan"),
    "boost_stability": ("CV_BOOST_STABILITY", "Boost stability"),
    "dismiss": ("DISMISS", "Dismiss"),
    "army_maintenance": ("ARMYMAINTENANCE", "Army Maintenance"),
    "fort_maintenance": ("EXPENSEFORTM", "Fort Maintenance"),
    "adm": ("adm_tech", "Administrative Technology"),
    "dip": ("dip_tech", "Diplomatic Technology"),
    "mil": ("mil_tech", "Military Technology"),
}
COUNTRY_SCREEN = "F1 (your country)"


def ui(campaign: Campaign, name: str) -> str:
    """An interface text in the game's language, in «guillemets»."""
    key, fallback = UI[name]
    return f"«{campaign.loc.get(key, '') or fallback}»"


def steps(campaign: Campaign, kind: str, target: str | None) -> list[str]:
    """The steps in the game for a recommendation, or none when it is not one action.

    Args:
        campaign: The loaded save (for names in the game's language).
        kind: The recommendation's kind (``complete_mission``, ``declare_war``, ...).
        target: Its target: a mission or decision key, a country tag, a province id or
            a technology category.
    """
    tab = lambda name: f"{COUNTRY_SCREEN} → {ui(campaign, name)} tab"  # noqa: E731
    named = f"«{title(campaign, target)}»" if target else "it"
    if kind in ("complete_mission", "time_mission"):
        found = [tab("missions"), f"click {named}: it is highlighted when it can be completed"]
        if kind == "time_mission":
            found.append("or leave it until the better reward's condition holds")
        return found
    if kind == "form_nation":
        return [tab("decisions"), f"click {named} and confirm"]
    if kind == "buy_technology" and target in ("adm", "dip", "mil"):
        return [tab("technology"), f"click the button under {ui(campaign, target)}"]
    if kind == "buy_idea":
        return [tab("ideas"), "click the next idea of the group"]
    if kind == "raise_stability":
        return [tab("stability"), f"click {ui(campaign, 'boost_stability')}"]
    if kind == "core_province" and target:
        # The name the map shows: the save's, which follows renames (Widin, not Vidin).
        data = campaign.province(int(target)) if target.isdigit() else None
        province = str((data or {}).get("name") or campaign.loc.province(target))
        return [
            f"click {province} on the map (or find it with the map's search)",
            f"click {ui(campaign, 'make_core')} in the province window",
        ]
    if kind == "repay_loan":
        return [tab("economy"), f"click {ui(campaign, 'repay_loan')} beside a loan"]
    if kind == "fix_deficit":
        return [
            tab("economy"),
            f"lower {ui(campaign, 'army_maintenance')} or {ui(campaign, 'fort_maintenance')} "
            "while at peace",
            f"or {ui(campaign, 'court')} tab: {ui(campaign, 'dismiss')} an advisor you can spare",
        ]
    if kind == "declare_war" and target:
        return [
            f"click any province of {campaign.name(target)} on the map, then its flag in the "
            f"province window to open its {ui(campaign, 'diplomacy')}",
            f"click {ui(campaign, 'declare_war')} and choose the casus belli",
        ]
    if kind == "get_casus_belli" and target:
        return [
            f"click a province of {campaign.name(target)} next to yours",
            f"click {ui(campaign, 'fabricate_claim')} (it sends a diplomat)",
        ]
    if kind == "make_peace" and target:
        return [
            f"click any province of {campaign.name(target)} on the map, then its flag to open "
            f"its {ui(campaign, 'diplomacy')}",
            f"click {ui(campaign, 'sue_for_peace')}, choose what to demand, and send it",
        ]
    if kind == "hold_expansion":
        return [
            "for each country named, click one of its provinces, then its flag to open its "
            f"{ui(campaign, 'diplomacy')}",
            f"click {ui(campaign, 'improve_relations')} (it sends a diplomat)",
        ]
    if kind in ("spend_power", "save_power") and target in ("adm", "dip", "mil"):
        return [tab("technology"), f"see what {ui(campaign, target)} and ideas cost"]
    if kind == "work_towards_mission":
        return [tab("missions"), f"hover {named} for what it still needs"]
    return []
