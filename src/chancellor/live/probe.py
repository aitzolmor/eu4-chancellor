"""A probe mod: does the game let a mod report values the save does not hold? (D-044).

The save has no war score and no casus belli, and mods cannot make network requests. The
one channel out is the ``log`` effect, which writes to ``logs/game.log`` while the game
runs. This prototype mod answers, in one game session, the questions that decide whether
that channel is worth building on:

1. Does ``on_monthly_pulse`` run the mod's event? A ``heartbeat`` line each month.
2. Does a ``log`` string show a variable? ``treasury`` exports the treasury, a value the
   save also has, as a control.
3. Can the war score be read? Two ways, for each enemy of the player:
   ``direct`` exports ``trigger_value:war_score`` (it may not exist), and ``ladder``
   narrows the score down with ``war_score_against`` checks every 5 points, a trigger
   the game's own events use.
4. Which casus belli does the player have, and against whom? For each country worth
   attacking (neighbours, rivals both ways, and holders of the player's claims or cores)
   the mod logs a ``cbtarget`` line, then a ``cb`` line for each casus belli type that
   ``has_casus_belli`` finds against it. The types come from the game's
   ``common/cb_types``. Whether that trigger also sees the casus belli the game derives
   on the fly (claims, cores, rivals), not only those added by events, is part of the
   question; the diplomacy screen is the reference. The same check runs for each of the
   player's subjects (``subject`` then ``subcb`` lines), whose casus belli the overlord
   can use: neighbours of the player or of the subject, the player's rivals, and
   holders of the player's claims or cores, leaving out the player's own subjects.

Every line starts with ``CHANCELLOR|`` so :mod:`chancellor.live.gamelog` can find it.
Nothing here changes the game: the event is hidden and only sets the mod's variables.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

MOD_NAME = "Chancellor probe"
FOLDER = "chancellor_probe"
NAMESPACE = "chancellor_probe"
LADDER_STEP = 5
SUPPORTED_VERSION = "1.37.*.*"
# Used when the game folder is unknown: the casus belli a player most often has.
DEFAULT_CB_TYPES = (
    "cb_core",
    "cb_conquest",
    "cb_fabricated_claims",
    "cb_restore_personal_union",
    "cb_claim_throne",
    "cb_vassalize_mission",
    "cb_insult",
    "cb_border_war",
    "cb_humiliate",
    "cb_trade_conflict",
    "cb_religious_conformance",
    "cb_heretic",
    "cb_crusade",
    "cb_imperial",
    "cb_hegemon",
    "cb_super_badboy",
)
_TOP_LEVEL = re.compile(r"^([A-Za-z0-9_]+)\s*=\s*\{", re.MULTILINE)


def cb_types_from(game_dir: Path | None) -> list[str]:
    """Every casus belli type in the game's ``common/cb_types``, in file order.

    Falls back to :data:`DEFAULT_CB_TYPES` when the folder is unknown or empty.
    """
    folder = game_dir / "common" / "cb_types" if game_dir else None
    if folder is None or not folder.is_dir():
        return list(DEFAULT_CB_TYPES)
    names: list[str] = []
    for path in sorted(folder.glob("*.txt")):
        text = path.read_bytes().decode("cp1252", errors="replace")
        names += [name for name in _TOP_LEVEL.findall(text) if name not in names]
    return names or list(DEFAULT_CB_TYPES)


def probe_files(cb_types: Sequence[str] = DEFAULT_CB_TYPES) -> dict[str, str]:
    """The mod's files, by path inside the mod folder.

    Args:
        cb_types: The casus belli types to check against each country.
    """
    return {
        "descriptor.mod": _descriptor(),
        "common/on_actions/zz_chancellor_probe.txt": _on_actions(),
        f"events/{NAMESPACE}.txt": _events(cb_types),
    }


def install(mod_dir: Path, cb_types: Sequence[str] = DEFAULT_CB_TYPES) -> list[Path]:
    """Write the mod into the game's ``mod`` folder (``Documents/.../mod``).

    The launcher lists a mod from its ``<name>.mod`` file next to the folder; without
    the launcher, ``dlc_load.json`` in the game's user folder enables it.

    Args:
        mod_dir: The game's ``mod`` folder.
        cb_types: The casus belli types to check (:func:`cb_types_from`).

    Returns:
        The files written.
    """
    root = mod_dir / FOLDER
    written = []
    for relative, text in probe_files(cb_types).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)
    launcher = mod_dir / f"{FOLDER}.mod"
    launcher.write_text(_descriptor(path=f"mod/{FOLDER}"), encoding="utf-8")
    written.append(launcher)
    return written


def _descriptor(path: str | None = None) -> str:
    lines = [
        'version="0.1"',
        'tags={ "Utilities" }',
        f'name="{MOD_NAME}"',
        f'supported_version="{SUPPORTED_VERSION}"',
    ]
    if path:
        lines.append(f'path="{path}"')
    return "\n".join(lines) + "\n"


def _on_actions() -> str:
    # on_monthly_pulse is empty in the base game (1.37), so defining it here takes
    # nothing away whether the game merges or replaces on_action blocks.
    return f"on_monthly_pulse = {{\n\tevents = {{\n\t\t{NAMESPACE}.1\n\t}}\n}}\n"


def _events(cb_types: Sequence[str]) -> str:
    checks = "\n".join(
        f"\t\t\tif = {{ limit = {{ ROOT = {{ has_casus_belli = {{ type = {cb} target = PREV }} }} "
        f'}} log = "CHANCELLOR|cb|[This.GetTag]|{cb}" }}'
        for cb in cb_types
    )
    # A subject's casus belli are the overlord's to use too (the diplomacy screen lists
    # them with the subject's name), so each subject is checked as well.
    subject_checks = "\n".join(
        f"\t\t\t\tif = {{ limit = {{ event_target:chancellor_subject = {{ has_casus_belli = "
        f"{{ type = {cb} target = PREV }} }} }} "
        f'log = "CHANCELLOR|subcb|[This.GetTag]|[This.GetName]|{cb}" }}'
        for cb in cb_types
    )
    ladder = "\n".join(
        f"\t\t\t\tif = {{ limit = {{ war_score_against = {{ who = PREV value = {value} }} }} "
        f"set_variable = {{ which = chancellor_ladder value = {value} }} }}"
        for value in range(-100 + LADDER_STEP, 101, LADDER_STEP)
    )
    return f"""namespace = {NAMESPACE}

# Monthly, for every country (on_monthly_pulse); only the player's country logs.
country_event = {{
\tid = {NAMESPACE}.1
\ttitle = {NAMESPACE}.1.t
\tdesc = {NAMESPACE}.1.d
\tpicture = DIPLOMACY_eventpicture
\thidden = yes
\tis_triggered_only = yes

\ttrigger = {{
\t\tai = no
\t}}

\timmediate = {{
\t\tlog = "CHANCELLOR|heartbeat|[GetYear]|[GetMonth]|[Root.GetName]"
\t\texport_to_variable = {{
\t\t\twhich = chancellor_treasury
\t\t\tvalue = treasury
\t\t}}
\t\tlog = "CHANCELLOR|treasury|[Root.chancellor_treasury.GetValue]"
\t\texport_to_variable = {{
\t\t\twhich = chancellor_direct
\t\t\tvalue = trigger_value:war_score
\t\t}}
\t\tlog = "CHANCELLOR|direct|[Root.chancellor_direct.GetValue]"
\t\tevery_country = {{
\t\t\tlimit = {{
\t\t\t\twar_with = ROOT
\t\t\t}}
\t\t\tROOT = {{
\t\t\t\tset_variable = {{ which = chancellor_ladder value = -100 }}
{ladder}
\t\t\t}}
\t\t\tlog = "CHANCELLOR|ladder|[This.GetName]|[Root.chancellor_ladder.GetValue]"
\t\t}}
\t\tevery_country = {{
\t\t\tlimit = {{
\t\t\t\tNOT = {{ tag = ROOT }}
\t\t\t\tOR = {{
\t\t\t\t\tis_neighbor_of = ROOT
\t\t\t\t\tis_rival = ROOT
\t\t\t\t\tROOT = {{ is_rival = PREV }}
\t\t\t\t\tany_owned_province = {{
\t\t\t\t\t\tOR = {{
\t\t\t\t\t\t\tis_claim = ROOT
\t\t\t\t\t\t\tis_core = ROOT
\t\t\t\t\t\t}}
\t\t\t\t\t}}
\t\t\t\t}}
\t\t\t}}
\t\t\tlog = "CHANCELLOR|cbtarget|[This.GetTag]|[This.GetName]"
{checks}
\t\t}}
\t\tevery_subject_country = {{
\t\t\tlog = "CHANCELLOR|subject|[This.GetTag]|[This.GetName]"
\t\t\tsave_event_target_as = chancellor_subject
\t\t\tevery_country = {{
\t\t\t\tlimit = {{
\t\t\t\t\tNOT = {{ tag = ROOT }}
\t\t\t\t\tNOT = {{ is_subject_of = ROOT }}
\t\t\t\t\tOR = {{
\t\t\t\t\t\tis_neighbor_of = ROOT
\t\t\t\t\t\tis_neighbor_of = event_target:chancellor_subject
\t\t\t\t\t\tis_rival = ROOT
\t\t\t\t\t\tany_owned_province = {{
\t\t\t\t\t\t\tOR = {{
\t\t\t\t\t\t\t\tis_claim = ROOT
\t\t\t\t\t\t\t\tis_core = ROOT
\t\t\t\t\t\t\t}}
\t\t\t\t\t\t}}
\t\t\t\t\t}}
\t\t\t\t}}
{subject_checks}
\t\t\t}}
\t\t}}
\t}}

\toption = {{
\t\tname = {NAMESPACE}.1.a
\t}}
}}
"""
