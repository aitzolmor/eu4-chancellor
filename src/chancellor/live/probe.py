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

Every line starts with ``CHANCELLOR|`` so :mod:`chancellor.live.gamelog` can find it.
Nothing here changes the game: the event is hidden and only sets the mod's variables.
"""

from __future__ import annotations

from pathlib import Path

MOD_NAME = "Chancellor probe"
FOLDER = "chancellor_probe"
NAMESPACE = "chancellor_probe"
LADDER_STEP = 5
SUPPORTED_VERSION = "1.37.*.*"


def probe_files() -> dict[str, str]:
    """The mod's files, by path inside the mod folder."""
    return {
        "descriptor.mod": _descriptor(),
        "common/on_actions/zz_chancellor_probe.txt": _on_actions(),
        f"events/{NAMESPACE}.txt": _events(),
    }


def install(mod_dir: Path) -> list[Path]:
    """Write the mod into the game's ``mod`` folder (``Documents/.../mod``).

    The launcher lists a mod from its ``<name>.mod`` file next to the folder.

    Returns:
        The files written.
    """
    root = mod_dir / FOLDER
    written = []
    for relative, text in probe_files().items():
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


def _events() -> str:
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
\t}}

\toption = {{
\t\tname = {NAMESPACE}.1.a
\t}}
}}
"""
