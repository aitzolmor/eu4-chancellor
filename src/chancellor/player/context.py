"""The player's context, kept per campaign outside any chat (D-039).

The tools read the campaign from the save; nothing in the save says what the *player*
wants. This store keeps it: goals, wants and limits, decisions taken and notes for each
campaign, and what the player said about themselves. The model reads it at the start of
a chat (``get_player_context``) and records what the player states
(``update_player_context``), so a new chat, or another model, starts where the last one
left off.

A campaign is recognised by the save's ``campaign_id``. That id changes within one
campaign (the user's Austria game had four between 1455 and 1519), so a save with an
unknown id is matched to the campaign of the same country whose first recorded date is
not later than the save's; a new game of the same country starts in 1444 and stays
apart. On the next write the new id joins that campaign.

The file lives in the game's user data folder (next to ``save games``), not under
``AppData``: Claude Desktop is a Store app whose processes see a private copy of
``AppData`` (see the handoff), and the MCP server it starts, the panel and the CLI must
all read the same file.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date as real_date
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from chancellor.context.campaign import Campaign

from chancellor.app.state import state_dir
from chancellor.player.watches import Condition, Reading, Watch, check, describe, from_dict, show

FILE_NAME = "player_context.json"
FOLDER = "eu4-chancellor"
MAX_TEXT = 300
MAX_COMPARED = 3  # countries the charts compare with at most (three colours pass, D-048)

# Kind → heading, in the order shown. "player" entries belong to the player, not to a
# campaign.
KINDS: dict[str, str] = {
    "goal": "Goals",
    "preference": "Wants and limits",
    "decision": "Decisions taken",
    "note": "Notes",
    "player": "About the player",
}


def context_path(save_dir: Path | None) -> Path:
    """Where the context is kept: the game's user data folder when known."""
    if save_dir is not None:
        return save_dir.parent / FOLDER / FILE_NAME
    return state_dir() / FILE_NAME


@dataclass
class Entry:
    """One thing the player said.

    Attributes:
        id: Number, unique in the file.
        kind: One of :data:`KINDS`.
        text: What the player wants, rules out, decided or said.
        game_date: In-game date of the save it was recorded with.
        written: Real date it was recorded.
        track: For a goal, the measures of its progress (D-061), as plain dicts.
    """

    id: int
    kind: str
    text: str
    game_date: str
    written: str
    track: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CampaignRecord:
    """One campaign's entries.

    Attributes:
        tag: The player's country.
        campaign_ids: Every ``campaign_id`` seen for it.
        first_date: Earliest in-game date recorded.
        last_date: Latest in-game date recorded.
        entries: What the player said about it.
        watches: What the player asked to be told about (D-041).
        key: Stable name of the campaign, for its journal (D-043): its first campaign
            id, or the country and first date.
        compare: Countries the player picked to compare with in the charts (D-049);
            empty means their rivals.
    """

    tag: str
    campaign_ids: list[str] = field(default_factory=list)
    first_date: str = ""
    last_date: str = ""
    entries: list[Entry] = field(default_factory=list)
    watches: list[Watch] = field(default_factory=list)
    key: str = ""
    compare: list[str] = field(default_factory=list)


@dataclass
class SaveKey:
    """What identifies a save's campaign."""

    campaign_id: str | None
    tag: str
    date: str


@dataclass
class ContextView:
    """The context for one save.

    Attributes:
        campaign: Its campaign record, if any.
        matched_by_country: Whether it was matched by country and date, not by id.
        player: Entries about the player.
    """

    campaign: CampaignRecord | None
    matched_by_country: bool
    player: list[Entry]


class PlayerContextError(ValueError):
    """A request the store cannot carry out (bad kind, unknown entry, empty text)."""


class PlayerContextStore:
    """Reads and writes the context file. A missing or unreadable file is empty."""

    def __init__(self, path: Path) -> None:
        """Use the file at ``path`` (created on the first write)."""
        self.path = path

    # --- reading ------------------------------------------------------------------------

    def view(self, key: SaveKey) -> ContextView:
        """The context for a save."""
        data = self._load()
        index, by_country = _match(data["campaigns"], key)
        campaign = data["campaigns"][index] if index is not None else None
        return ContextView(campaign, by_country, data["player"])

    # --- writing ------------------------------------------------------------------------

    def add(self, key: SaveKey, kind: str, text: str) -> Entry:
        """Record an entry for the save's campaign (or about the player)."""
        if kind not in KINDS:
            raise PlayerContextError(f"Unknown kind '{kind}'; use one of: {', '.join(KINDS)}.")
        text = " ".join(text.split())
        if not text:
            raise PlayerContextError("The text is empty.")
        if len(text) > MAX_TEXT:
            raise PlayerContextError(f"Keep it under {MAX_TEXT} characters; it is one entry.")
        data = self._load()
        entry = Entry(data["next_id"], kind, text, key.date, real_date.today().isoformat())
        data["next_id"] += 1
        if kind == "player":
            data["player"].append(entry)
        else:
            self._campaign_for_write(data, key).entries.append(entry)
        self._save(data)
        return entry

    def add_watch(self, key: SaveKey, description: str, conditions: list[Condition]) -> Watch:
        """Set a watch for the save's campaign."""
        description = " ".join(description.split())
        if not description:
            raise PlayerContextError("The description is empty.")
        if len(description) > MAX_TEXT:
            raise PlayerContextError(f"Keep the description under {MAX_TEXT} characters.")
        if not conditions:
            raise PlayerContextError("A watch needs at least one condition.")
        data = self._load()
        watch = Watch(
            data["next_id"], description, conditions, key.date, real_date.today().isoformat()
        )
        data["next_id"] += 1
        self._campaign_for_write(data, key).watches.append(watch)
        self._save(data)
        return watch

    def track_goal(self, key: SaveKey, goal_id: int, measures: list[dict[str, Any]]) -> Entry:
        """Attach measures to one of the campaign's goals, replacing any it had (D-061).

        Raises:
            PlayerContextError: If there is no goal with that id in the save's campaign.
        """
        data = self._load()
        index, _ = _match(data["campaigns"], key)
        entries = data["campaigns"][index].entries if index is not None else []
        goal = next((e for e in entries if e.id == goal_id), None)
        if goal is None or goal.kind != "goal":
            raise PlayerContextError(f"No goal #{goal_id} in this campaign.")
        goal.track = list(measures)
        self._save(data)
        return goal

    def fire(self, key: SaveKey, ids: list[int]) -> None:
        """Mark watches as fired on the save's date."""
        if not ids:
            return
        data = self._load()
        index, _ = _match(data["campaigns"], key)
        if index is None:
            return
        for watch in data["campaigns"][index].watches:
            if watch.id in ids and not watch.fired:
                watch.fired = key.date
        self._save(data)

    def set_compare(self, key: SaveKey, tags: list[str]) -> list[str]:
        """Pick the countries the charts compare with (none: the rivals again)."""
        chosen = list(dict.fromkeys(t for t in tags if t))[:MAX_COMPARED]
        data = self._load()
        self._campaign_for_write(data, key).compare = chosen
        self._save(data)
        return chosen

    def campaign_key(self, key: SaveKey) -> str:
        """The stable key of the save's campaign, recording the campaign if it is new.

        Reading a save is enough to start a campaign's record: its journal (D-043) needs
        one before the player says anything.
        """
        data = self._load()
        index, by_country = _match(data["campaigns"], key)
        before = len(data["campaigns"])
        campaign = self._campaign_for_write(data, key)
        if index is None or by_country or len(data["campaigns"]) != before:
            self._save(data)
        return campaign.key

    def remove(self, key: SaveKey, entry_id: int) -> Entry | Watch:
        """Remove an entry or a watch (a goal reached or dropped, a watch done with)."""
        data = self._load()
        for entries in self._lists(data, key):
            for entry in entries:
                if entry.id == entry_id:
                    entries.remove(entry)
                    self._save(data)
                    return entry
        index, _ = _match(data["campaigns"], key)
        watches = data["campaigns"][index].watches if index is not None else []
        for watch in watches:
            if watch.id == entry_id:
                watches.remove(watch)
                self._save(data)
                return watch
        raise PlayerContextError(f"No entry #{entry_id} for this campaign or the player.")

    def replace(self, key: SaveKey, entry_id: int, text: str) -> Entry:
        """Change an entry's text, keeping its kind; it is dated again."""
        old = self.remove(key, entry_id)
        if isinstance(old, Watch):
            self._restore_watch(key, old)
            raise PlayerContextError(f"#{entry_id} is a watch: remove it and set a new one.")
        try:
            return self.add(key, old.kind, text)
        except PlayerContextError:
            self._restore(key, old)
            raise

    # --- helpers ------------------------------------------------------------------------

    def _restore_watch(self, key: SaveKey, watch: Watch) -> None:
        data = self._load()
        self._campaign_for_write(data, key).watches.append(watch)
        self._save(data)

    def _restore(self, key: SaveKey, entry: Entry) -> None:
        data = self._load()
        if entry.kind == "player":
            data["player"].append(entry)
        else:
            self._campaign_for_write(data, key).entries.append(entry)
        self._save(data)

    def _lists(self, data: dict[str, Any], key: SaveKey) -> list[list[Entry]]:
        index, _ = _match(data["campaigns"], key)
        lists = [data["player"]]
        if index is not None:
            lists.insert(0, data["campaigns"][index].entries)
        return lists

    def _campaign_for_write(self, data: dict[str, Any], key: SaveKey) -> CampaignRecord:
        """The save's campaign, created or joined by this save's id and date."""
        campaigns: list[CampaignRecord] = data["campaigns"]
        index, _ = _match(campaigns, key)
        if index is None:
            name = key.campaign_id or f"{key.tag}@{key.date}"
            campaigns.append(
                CampaignRecord(key.tag, first_date=key.date, last_date=key.date, key=name)
            )
            index = len(campaigns) - 1
        campaign = campaigns[index]
        if key.campaign_id and key.campaign_id not in campaign.campaign_ids:
            campaign.campaign_ids.append(key.campaign_id)
        if not campaign.first_date or _date(key.date) < _date(campaign.first_date):
            campaign.first_date = key.date
        if _date(key.date) > _date(campaign.last_date):
            campaign.last_date = key.date
        return campaign

    def _load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        campaigns = [
            CampaignRecord(
                tag=str(c.get("tag", "")),
                campaign_ids=[str(i) for i in c.get("campaign_ids", [])],
                first_date=str(c.get("first_date", "")),
                last_date=str(c.get("last_date", "")),
                entries=[_entry(e) for e in c.get("entries", []) if isinstance(e, dict)],
                watches=[from_dict(w) for w in c.get("watches", []) if isinstance(w, dict)],
                key=str(c.get("key") or _default_key(c)),
                compare=[str(t) for t in c.get("compare", []) if t],
            )
            for c in raw.get("campaigns", [])
            if isinstance(c, dict)
        ]
        player = [_entry(e) for e in raw.get("player", []) if isinstance(e, dict)]
        ids = [e.id for c in campaigns for e in c.entries] + [e.id for e in player]
        ids += [w.id for c in campaigns for w in c.watches]
        next_id = max([int(raw.get("next_id", 1)), *(i + 1 for i in ids)])
        return {"next_id": next_id, "campaigns": campaigns, "player": player}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "next_id": data["next_id"],
            "player": [asdict(e) for e in data["player"]],
            "campaigns": [asdict(c) for c in data["campaigns"]],
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), "utf-8")
        temporary.replace(self.path)


def refresh_watches(
    store: PlayerContextStore, key: SaveKey, campaign: Campaign
) -> list[tuple[Watch, list[Reading]]]:
    """Check the campaign's watches on this save; fire those whose conditions all hold.

    Returns every watch with its readings (none for watches that had already fired).
    """
    record = store.view(key).campaign
    if record is None:
        return []
    results = []
    newly = []
    for watch in record.watches:
        readings = [] if watch.fired else check(campaign, watch)
        if readings and all(r.met for r in readings):
            watch.fired = key.date
            newly.append(watch.id)
        results.append((watch, readings))
    store.fire(key, newly)
    return results


def watch_lines(campaign: Campaign, results: list[tuple[Watch, list[Reading]]]) -> list[str]:
    """Markdown lines for the watches: fired first, then those waiting with their values."""
    lines = []
    for watch, _ in results:
        if watch.fired:
            lines.append(
                f"- #{watch.id} **FIRED** at {watch.fired}: {watch.description} (tell the "
                "player; remove it once they have seen it)"
            )
    for watch, readings in results:
        if not watch.fired:
            parts = "; ".join(
                f"{describe(r.condition, campaign)} (now {show(r.value)})" for r in readings
            )
            lines.append(f"- #{watch.id} waiting: {watch.description}. {parts}")
    return lines


def render_context(
    view: ContextView,
    key: SaveKey,
    country: str,
    watches: list[str] | None = None,
    progress: dict[int, str] | None = None,
) -> str:
    """Markdown for ``get_player_context``.

    Args:
        view: The context for the save.
        key: The save.
        country: The player's country, labelled.
        watches: Lines from :func:`watch_lines`.
        progress: Goal id → its progress line (D-061).
    """
    lines = [f"# Player context: {country}", ""]
    campaign = view.campaign
    if campaign is None or not (campaign.entries or campaign.watches):
        lines.append(f"Nothing recorded yet for this campaign ({country}, save of {key.date}).")
    else:
        lines.append(
            f"Recorded in this campaign's chats, saves from {campaign.first_date} to "
            f"{campaign.last_date}; this save is {key.date}."
        )
        if view.matched_by_country:
            lines.append(
                "This save has a new campaign id, so the campaign was matched by country "
                "and date. If the player says this is a different game, do not use it."
            )
    for kind, heading in KINDS.items():
        entries = view.player if kind == "player" else _of_kind(campaign, kind)
        if entries:
            lines += ["", f"## {heading}", ""]
            for e in entries:
                lines.append(f"- #{e.id} {e.text} (recorded at {e.game_date})")
                if progress and e.id in progress:
                    lines.append(f"  - Progress: {progress[e.id]}")
                elif kind == "goal" and not e.track:
                    lines.append("  - Not measured yet: track_goal can tie it to the save.")
    if watches:
        lines += ["", "## Watches", "", *watches]
    lines += [
        "",
        "_Recorded from what the player said. Follow it when advising. When the player "
        "states a new goal, preference, limit or decision, or one is reached, dropped or "
        "changed, update it with update_player_context and tell them. Record only what "
        "the player says, never your own suggestions._",
    ]
    return "\n".join(lines) + "\n"


def _of_kind(campaign: CampaignRecord | None, kind: str) -> list[Entry]:
    return [e for e in campaign.entries if e.kind == kind] if campaign else []


def _match(campaigns: list[CampaignRecord], key: SaveKey) -> tuple[int | None, bool]:
    """The save's campaign: by id, else by country and date. ``(index, by_country)``."""
    if key.campaign_id:
        for index, campaign in enumerate(campaigns):
            if key.campaign_id in campaign.campaign_ids:
                return index, False
    candidates = [
        index
        for index, campaign in enumerate(campaigns)
        if campaign.tag == key.tag and _date(campaign.first_date) <= _date(key.date)
    ]
    if not candidates:
        return None, False
    # The latest campaign that had reached this far, if several (an older game kept).
    best = max(candidates, key=lambda i: _date(campaigns[i].last_date))
    return best, True


def _default_key(raw: dict[str, Any]) -> str:
    """The key of a campaign recorded before keys existed: stable across reads."""
    ids = raw.get("campaign_ids") or []
    return str(ids[0]) if ids else f"{raw.get('tag', '')}@{raw.get('first_date', '')}"


def _entry(raw: dict[str, Any]) -> Entry:
    return Entry(
        id=int(raw.get("id", 0)),
        kind=str(raw.get("kind", "note")),
        text=str(raw.get("text", "")),
        game_date=str(raw.get("game_date", "")),
        written=str(raw.get("written", "")),
        track=[m for m in raw.get("track", []) if isinstance(m, dict)],
    )


def _date(text: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in text.split("."))
    except ValueError:
        return (0,)
