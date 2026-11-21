"""The live war score, from what the probe mod wrote to ``game.log`` (D-044, D-063).

The save holds a war's score only as the game recorded it at its last quarterly check
(``last_warscore_quarter``, D-050). The probe mod logs it every month:

* ``direct``: ``trigger_value:war_score``, exact; checked in the user's war against
  Poland (+87 on the game's screen, 87.999 logged), it is the score against the enemy
  war leader. With more than one war it is not said which war it is, so it is only
  used when the player is in one;
* ``ladder``: ``war_score_against`` in steps of 5 for each enemy; it answers only for an
  enemy war leader (-100 for its allies, whose scores the game shows but the trigger
  does not give), so it serves for each war when there are several.

As with the casus belli (D-051), the log is only trusted when it is the save's country's
and within a year of the save's date.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from chancellor.context.campaign import Campaign
from chancellor.live.casus_belli import MAX_AGE_DAYS, _days
from chancellor.live.gamelog import read_probe

NOT_LEADER = -100.0  # what the ladder gives against a country that is not a war leader


@dataclass
class LiveWarScore:
    """The probe mod's latest war score readings.

    Attributes:
        date: The game date of the reading.
        direct: The exact score (``trigger_value:war_score``), or ``None``.
        ladder: Enemy name (in the game's language) → its score, in steps of 5.
    """

    date: str
    direct: float | None
    ladder: dict[str, float]

    def against(self, campaign: Campaign, leader: str, wars: int) -> tuple[float, str] | None:
        """The live score against an enemy war leader: ``(score, how)``, or ``None``.

        Args:
            campaign: The loaded save (for the leader's name, as the log writes it).
            leader: The enemy war leader's tag.
            wars: How many wars the player is in; the exact value needs just one.
        """
        if wars == 1 and self.direct is not None:
            return self.direct, "exact"
        value = self.ladder.get(campaign.name(leader))
        if value is None or value <= NOT_LEADER:
            return None
        return value, "to the nearest 5 below"


@dataclass
class LiveWarScoreLookup:
    """The reading, when it can be used, or why it cannot."""

    data: LiveWarScore | None
    reason: str = ""


def load_war_score(campaign: Campaign, log: Path | None) -> LiveWarScoreLookup:
    """The probe mod's latest war score, if it speaks for this save."""
    off = "The live war score needs the Chancellor probe mod running in the game"
    if log is None or not log.is_file():
        return LiveWarScoreLookup(None, f"{off} (no game log found).")
    try:
        report = read_probe(log)
    except OSError as exc:
        return LiveWarScoreLookup(None, f"{off} (the game log could not be read: {exc}).")
    ladder = {}
    for name, raw in report.ladder.items():
        try:
            ladder[name] = float(raw)
        except ValueError:
            continue
    direct = None
    if report.direct is not None:
        try:
            direct = float(report.direct)
        except ValueError:
            direct = None
    if not report.last_date or (direct is None and not ladder):
        return LiveWarScoreLookup(None, f"{off}: the game log has no war score yet.")
    country = report.heartbeats[-1][2] if report.heartbeats else ""
    player = campaign.player
    if player and country and country not in (campaign.name(player), player):
        return LiveWarScoreLookup(
            None, f"The game log's war score is {country}'s, not {campaign.name(player)}'s."
        )
    save_date = campaign.date
    age = _days(save_date) - _days(report.last_date) if save_date[:1].isdigit() else 0
    if abs(age) > MAX_AGE_DAYS:
        return LiveWarScoreLookup(
            None,
            f"The game log's war score is from {report.last_date}, too far from the save's "
            f"date ({save_date}).",
        )
    return LiveWarScoreLookup(LiveWarScore(report.last_date, direct, ladder))
