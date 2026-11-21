"""The query functions, exposed to the chat agent as tools (D-009).

Every CLI command has a tool here that calls the same code and returns the same Markdown,
so what the player sees with ``chancellor war-check`` is exactly what the assistant reads.
The tool list is static and ordered, which keeps the request prefix stable for prompt
caching.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from chancellor.context.advice import Goal, goals_from, recommend, render_recommendations
from chancellor.context.ae import render_ae_section
from chancellor.context.alerts import ReadyNow, ready_now
from chancellor.context.campaign import Campaign, CountryLookupError, _date_key
from chancellor.context.coring import coring_costs
from chancellor.context.decisions import check_decisions, render_decisions
from chancellor.context.ledger import read_ledger, render_budget
from chancellor.context.missions import mission_tree, render_missions
from chancellor.context.power import power_report
from chancellor.context.summarizer import summarize
from chancellor.context.targets import find_targets, render_targets
from chancellor.context.trade import render_trade, trade_line, trade_report
from chancellor.context.war_check import check_war, render_war_check
from chancellor.context.wars import render_wars, war_reports
from chancellor.context.world import render_world, world_overview
from chancellor.game.ae_rules import AeRules
from chancellor.game.coring_rules import CoringRules
from chancellor.game.decisions import DecisionLibrary
from chancellor.game.development_rules import DevelopmentRules
from chancellor.game.imperial_reforms import ImperialReformLibrary
from chancellor.game.missions import MissionLibrary
from chancellor.game.modifiers import ModifierLibrary
from chancellor.game.power_rules import PowerRules
from chancellor.game.rules import GameRules
from chancellor.game.trade_nodes import TradeGraph
from chancellor.live.casus_belli import load_casus_belli
from chancellor.live.war_score import load_war_score
from chancellor.player.context import (
    KINDS,
    PlayerContextError,
    PlayerContextStore,
    SaveKey,
    context_path,
    refresh_watches,
    render_context,
    watch_lines,
)
from chancellor.player.goals import GoalError, Measure
from chancellor.player.goals import Progress as GoalProgress
from chancellor.player.goals import from_dict as measure_from
from chancellor.player.goals import progress as goal_progress
from chancellor.player.goals import render as render_goal
from chancellor.player.goals import to_dict as measure_dict
from chancellor.player.goals import validate as validate_measure
from chancellor.player.journal import (
    JournalStore,
    journal_entries,
    journal_path,
    render_journal,
    render_trends,
    take_snapshot,
    trend_data,
)
from chancellor.player.watches import (
    Watch,
    WatchError,
    check,
    describe,
    metric_list,
    show,
    validate_condition,
)
from chancellor.wiki.store import render_hits, search, wiki_path

WIKI_RESULTS = 4
JOURNAL_STEPS = 6  # journal steps shown by default
# A line added to these tools' results while the wiki is imported, so the model thinks of
# it for the strategy around the numbers (D-036). Queries are examples, in English.
WIKI_HINTS = {
    "get_country_briefing": "'idea groups guide', the country's English name plus "
    "'strategy', 'Holy Roman Empire', 'estates'",
    "get_expansion_targets": "'vassal', 'coalition', 'aggressive expansion', "
    "'casus belli', the target's English name",
    "check_war": "'coalition', 'aggressive expansion', 'peace treaty', 'war score'",
}
# One entry's label in the panel's "Your plan" (KINDS has the section headings).
PANEL_LABELS = {
    "goal": "Goal",
    "preference": "Want / limit",
    "decision": "Decision",
    "note": "Note",
    "player": "About you",
}
# Tools used to plan, whose results end with a line on the player's context (D-040).
PLAYER_HINT_TOOLS = frozenset(
    {
        "get_country_briefing",
        "get_expansion_targets",
        "check_war",
        "get_missions",
        "get_decisions",
    }
)


class ToolInputError(ValueError):
    """The model called a tool with arguments that do not match its schema."""


_COUNTRY = {
    "type": "string",
    "description": "Country tag (e.g. 'BUR') or name in the game's language (e.g. 'Borgoña').",
}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_country_briefing",
        "description": (
            "Briefing of one country from the current save: ruler, stability, economy, "
            "military, territory and overextension, technology and ideas, monarch power "
            "with what it buys (estimated cost of the next technology in each category with "
            "its parts, ideas, stability, generals; monthly gain; months until each next "
            "technology; leaders and advisors; what developing its provinces costs, "
            "cheapest first), "
            "estates, diplomacy, aggressive expansion held against it (who is near or in a "
            "coalition), its place in the Holy Roman Empire (with the next imperial reform), "
            "wars and the countries around "
            "it. For any country other than the player's it also shows "
            "the relation to the player and a strength comparison. Omit `country` for the "
            "player's own country."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"country": _COUNTRY},
            "additionalProperties": False,
        },
    },
    {
        "name": "check_war",
        "description": (
            "Who would fight if `attacker` (default: the player) declared war on `target` "
            "today: the target's allies, subjects, overlord, guarantors, the Holy Roman "
            "Emperor and coalitions, the attacker's allies and subjects, each marked "
            "certain/likely/possible, with regiments and manpower per side, and any truce "
            "(declaring war would break it; end date estimated), any ally of the attacker "
            "bound to defend the target, and the coalition risk: aggressive expansion the "
            "target and its neighbours already hold against the attacker (50 is the "
            "coalition threshold), and an estimate of the AE that taking the provinces the "
            "attacker has claims or cores on would add to each country nearby (who would "
            "cross 50). For the player, the casus belli against the target (their own and their "
            "subjects', which they can use) when the Chancellor probe mod is running in the "
            "game; otherwise it says they are unknown."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"target": _COUNTRY, "attacker": _COUNTRY},
            "required": ["target"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_world_overview",
        "description": (
            "The wider world: great powers, largest countries by development and army, "
            "the alliance networks of the major powers, ongoing wars by size, personal "
            "unions and the Holy Roman Empire."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_missions",
        "description": (
            "A country's mission tree from the game files with progress from the save: "
            "completed, available now (prerequisites done) or locked, with requirements and "
            "rewards (including the bonuses of granted modifiers). Each available mission's "
            "requirements are checked against the save ([x] met, [ ] not met, [?] could not "
            "be checked), with a summary of which can be completed now and which are one "
            "requirement away. Set `brief` for titles and status only. Omit `country` for "
            "the player."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "country": _COUNTRY,
                "brief": {"type": "boolean", "description": "Titles and status only."},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_decisions",
        "description": (
            "Formable nations and decisions a country can see, each with a requirement "
            "checklist: met, not met, or not checkable automatically. Set `formables_only` "
            "to list only nations it can form. Omit `country` for the player."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "country": _COUNTRY,
                "formables_only": {"type": "boolean", "description": "Only formable nations."},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_expansion_targets",
        "description": (
            "Where a country should expand: provinces wanted by its available missions, "
            "visible formable nations, claims and cores, grouped by who holds them, with a "
            "war check and a coalition risk against each owner (favourable, even and hard "
            "targets; owners under a truce or defended by your own allies last, high "
            "coalition risk after the rest; provinces held by subjects or allies listed "
            "apart). For the player, the casus belli against each owner when the Chancellor "
            "probe mod is running. Omit `country` for the player."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"country": _COUNTRY},
            "additionalProperties": False,
        },
    },
    {
        "name": "search_wiki",
        "description": (
            "Search the Europa Universalis 4 Wiki (a local copy the player imported) for how "
            "game mechanics work and for strategy: guides, idea groups, diplomacy, warfare, "
            "estates, the Holy Roman Empire, country pages such as Austria. Call it whenever "
            "advice goes beyond the campaign's numbers: choosing idea groups, judging an "
            "expansion plan or a war route, using subjects (vassals, marches, unions), "
            "handling coalitions and aggressive expansion, the Empire, estates, or explaining "
            "a mechanic. The other tools say what the campaign holds; this one says how "
            "experienced players use it. Write the query "
            "with English game terms (e.g. 'coalition', 'core creation cost', 'Austria "
            "strategy'), even when the player writes in another language. Each result gives "
            "the page, section, link and the game version it was last checked for. Numbers "
            "from the save and the computed mechanics in the other tools take precedence; use "
            "the wiki for how things work and for strategy, cite the page, and say so when it "
            "was checked for a much older version than 1.37."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "English game terms to look for."},
                "max_results": {
                    "type": "integer",
                    "description": "How many sections to return (1-8, default 4).",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_player_context",
        "description": (
            "What the player wants in this campaign, from earlier conversations: their "
            "goals, wants and limits (what they rule out), decisions taken and notes, and "
            "what they said about themselves (such as how well they know the game). Call it "
            "at the start of every conversation, before advising, so advice follows the "
            "player's own plans; it carries over between chats and models. Each entry has an "
            "id for update_player_context."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "update_player_context",
        "description": (
            "Record what the player says about their plans so later conversations know it. "
            "`add` an entry of a `kind`: goal (what they want to achieve), preference (what "
            "they want or rule out), decision (something they chose), note, or player "
            "(about the player, not the campaign). `remove` an entry by its id when a goal "
            "is reached or dropped, or `replace` its text when it changes. Record only what "
            "the player states or explicitly agrees to, never your own inference or "
            "suggestion; keep each entry short, in the player's language; and tell the "
            "player what you recorded."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "remove", "replace"]},
                "kind": {
                    "type": "string",
                    "enum": ["goal", "preference", "decision", "note", "player"],
                    "description": "For add.",
                },
                "text": {
                    "type": "string",
                    "description": "For add and replace: one short statement.",
                },
                "entry": {"type": "integer", "description": "For remove and replace: the id."},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_watch",
        "description": (
            'Set a watch when the player asks to be told when something happens ("tell me '
            'when France is weak enough to attack", "when I have 200 ducats", "when the '
            'truce with Naples ends"). Turn their words into conditions on the metrics '
            "below; all conditions must hold for the watch to fire. It is checked on every "
            "save, fires once, and shows in the panel and in the planning tools' results; "
            "get_player_context lists watches with their current values, and "
            "update_player_context removes one by its id. Make vague words concrete and tell "
            "the player the thresholds you chose (for 'weak enough to attack', for example, "
            "war_odds >= 1.5 with no truce). `country` and `other` are names or tags; both "
            "default to the player. Metrics: " + metric_list() + "."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "What the player asked for, in their words.",
                },
                "conditions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "metric": {"type": "string"},
                            "op": {"type": "string", "enum": [">=", "<=", "is"]},
                            "value": {"type": ["number", "boolean"]},
                            "country": {"type": "string"},
                            "other": {"type": "string"},
                        },
                        "required": ["metric", "op", "value"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["description", "conditions"],
            "additionalProperties": False,
        },
    },
    {
        "name": "track_goal",
        "description": (
            "Tie one of the player's recorded goals to measures read from every save, so "
            "its progress shows in get_player_context and the panel. Use it right after "
            "recording a goal with update_player_context (or for a goal listed as 'not "
            "measured yet'). Measures, from what the goal says: `mission` (key: a mission "
            "key from get_missions), `formable` (key: a decision key from get_decisions), "
            "`provinces` (key: an area, region or superregion name such as "
            "low_countries_region; `count`: how many, 0 for all; `subjects`: whether the "
            "subjects' provinces count, default true), `country` (key: a name or tag; "
            "`state`: subject or gone), `metric` (`condition`: a watch condition, metric "
            "op value as in create_watch). Replaces the goal's earlier measures. Tell the "
            "player what you measure. Metrics: " + metric_list() + "."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "goal": {"type": "integer", "description": "The goal's id (#n)."},
                "measures": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": ["mission", "formable", "provinces", "country", "metric"],
                            },
                            "key": {"type": "string"},
                            "count": {"type": "integer"},
                            "subjects": {"type": "boolean"},
                            "state": {"type": "string", "enum": ["subject", "gone"]},
                            "condition": {
                                "type": "object",
                                "properties": {
                                    "metric": {"type": "string"},
                                    "op": {"type": "string", "enum": [">=", "<=", "is"]},
                                    "value": {"type": ["number", "boolean"]},
                                    "country": {"type": "string"},
                                    "other": {"type": "string"},
                                },
                                "required": ["metric", "op", "value"],
                                "additionalProperties": False,
                            },
                        },
                        "required": ["kind"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["goal", "measures"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_campaign_journal",
        "description": (
            "What changed in the player's campaign between the saves the Chancellor has "
            "read: provinces gained, lost or cored; wars begun and ended; allies, subjects, "
            "rivals, truces and coalition members gained or lost; a new ruler or heir; ideas "
            "and technology taken; a new Emperor or imperial reform; and the key numbers "
            "(treasury, income, manpower, regiments, development, AE ...), newest first. "
            "Use it for questions about what happened recently, how the campaign is "
            "trending, or to remember what came before this chat."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "saves": {
                    "type": "integer",
                    "description": "How many steps back to show (1-30, default 6).",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_trends",
        "description": (
            "How the player's key numbers moved over the campaign, from the journal's "
            "record of each save read: treasury, monthly income and expenses, manpower, "
            "regiments, development, provinces, prestige, overextension and countries at "
            "50+ AE, as a table of up to 12 dates from the first record to this save, with "
            "the main events (wars, rulers) between them, and the player's development, "
            "regiments and income against their rivals (or the countries the player picked "
            "in the panel, or the up to three `countries` given). Use it for 'how is my "
            "economy doing', 'am I growing', 'am I ahead of France', or to judge a plan "
            "against the trend."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "countries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 3,
                    "description": "Countries to compare with (names or tags); default rivals.",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_trade",
        "description": (
            "A country's trade, read from the save: its home trade node and its share of "
            "the trade power there, what it collects there each month, where its merchants "
            "are and whether each collects or steers, its light ships protecting trade, its "
            "trade power and share in every node (home first, then the nodes that feed it, "
            "nearest first), the nodes feeding home where it has no power, and who embargoes "
            "it. Use it for any question about trade income, merchants, trade steering or "
            "where to put a trade capital or centre of trade. Omit `country` for the player."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"country": _COUNTRY},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_wars",
        "description": (
            "A country's wars in detail, from the save: when each began (the declaration), "
            "the war goal and who controls it, both sides, every province one side occupies "
            "of the other (with development, by owner), the losses of each side in battle, "
            "to attrition and in ships, some recorded battles, participation, and the war "
            "score the game recorded at its last quarterly check. Use it for anything about a "
            "war in progress: how it is going, what to demand at the peace, whether to make "
            "a separate peace. The war score is against the enemy war leader: monthly when "
            "the probe mod runs, otherwise the game's last quarterly check. "
            "Omit `country` for the player."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"country": _COUNTRY},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_budget",
        "description": (
            "Where a country's money comes from and where it goes, from the ledger in the "
            "save: income by source (taxation, production, trade, gold, vassals, war "
            "reparations...) and expenses by category (army, fleet and fort maintenance, "
            "advisors, state maintenance, interest, buildings...), for last month, this year "
            "so far and last year, the recurring balance, and the largest spending since the "
            "campaign began. Use it for any question about a deficit, debt, what to cut or "
            "how to earn more. Omit `country` for the player."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"country": _COUNTRY},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_recommendations",
        "description": (
            "What the player should do now: a ranked list of concrete actions, each with "
            "the facts behind it and the tool with the details. Built from rules over the "
            "save: missions and nations ready to claim, a deficit or loans, monarch power "
            "near the cap or a technology to buy, overextension and the cheapest cores, "
            "the best expansion targets (odds, coalition risk, casus belli when known), "
            "aggressive expansion to let cool down, missions one requirement away. Marks "
            "the ones that touch the player's recorded goals, and gives each one's steps in "
            "the game (screens and buttons, in the game's language). Use it for 'what should I "
            "do?', 'what next?' or at the start of a session; then weigh the options with "
            "the player's goals and say which to take first. Omit `country` for the player."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"country": _COUNTRY},
            "additionalProperties": False,
        },
    },
]


@dataclass
class _Field:
    kind: type
    required: bool = False


_SCHEMAS: dict[str, dict[str, _Field]] = {
    "get_country_briefing": {"country": _Field(str)},
    "check_war": {"target": _Field(str, required=True), "attacker": _Field(str)},
    "get_world_overview": {},
    "get_missions": {"country": _Field(str), "brief": _Field(bool)},
    "get_decisions": {"country": _Field(str), "formables_only": _Field(bool)},
    "get_expansion_targets": {"country": _Field(str)},
    "get_recommendations": {"country": _Field(str)},
    "search_wiki": {"query": _Field(str, required=True), "max_results": _Field(int)},
    "get_player_context": {},
    "get_campaign_journal": {"saves": _Field(int)},
    "get_trends": {"countries": _Field(list)},
    "get_trade": {"country": _Field(str)},
    "get_wars": {"country": _Field(str)},
    "get_budget": {"country": _Field(str)},
    "create_watch": {
        "description": _Field(str, required=True),
        "conditions": _Field(list, required=True),
    },
    "track_goal": {
        "goal": _Field(int, required=True),
        "measures": _Field(list, required=True),
    },
    "update_player_context": {
        "action": _Field(str, required=True),
        "kind": _Field(str),
        "text": _Field(str),
        "entry": _Field(int),
    },
}


# Game data the toolbox loads lazily; shared when the save changes (see with_campaign).
# Words a model may write for the player's own country instead of omitting `country`.
PLAYER_WORDS = frozenset(
    {"player", "the player", "me", "my country", "mine", "myself", "self", "root", "you", "yours"}
)
_GAME_DATA = ("_missions", "_decisions", "_rules", "_modifiers", "_trade_graph")


class Toolbox:
    """Runs tools against one loaded save; game data is loaded on first use."""

    def __init__(
        self,
        campaign: Campaign,
        game_dir: Path | None,
        context_file: Path | None = None,
        game_log: Path | None = None,
    ) -> None:
        """Bind the tools to a campaign and, optionally, the game installation.

        Args:
            campaign: The loaded save.
            game_dir: The game installation, for the tools that read game files.
            context_file: Where the player's context is kept (:func:`context_path`);
                the app's state folder by default.
            game_log: The game's ``logs/game.log``, where the probe mod writes the casus
                belli (D-051); ``None`` leaves them out.
        """
        self.campaign = campaign
        self.game_dir = game_dir
        self.context_file = context_file or context_path(None)
        self.game_log = game_log

    @property
    def definitions(self) -> list[dict[str, Any]]:
        """Tool definitions for the Messages API (stable order for prompt caching)."""
        return TOOL_DEFINITIONS

    def with_campaign(self, campaign: Campaign) -> Toolbox:
        """A toolbox for another save that reuses the game data already loaded here."""
        other = Toolbox(campaign, self.game_dir, self.context_file, self.game_log)
        for name in _GAME_DATA:
            if name in self.__dict__:  # cached_property values live in the instance dict
                other.__dict__[name] = self.__dict__[name]
        return other

    def run(self, name: str, arguments: Any) -> str:
        """Run a tool and return its Markdown output.

        Raises:
            ToolInputError: If the arguments do not match the tool's schema.
            CountryLookupError: If a country name matches nothing or several countries.
            KeyError: If the tool does not exist.
        """
        args = validate(name, arguments)
        handler: Callable[[dict[str, Any]], str] = getattr(self, f"_{name}")
        text = handler(args)
        hint = WIKI_HINTS.get(name)
        if hint and wiki_path().is_file():
            text = (
                f"{text.rstrip()}\n\n_For the strategy behind these numbers, search_wiki has "
                f"the game wiki; for example {hint}._\n"
            )
        if name in PLAYER_HINT_TOOLS:
            text = f"{text.rstrip()}\n\n{self._player_hint()}\n"
        return text

    def _player_hint(self) -> str:
        """One line on the player's recorded context, for the planning tools (D-040)."""
        store = PlayerContextStore(self.context_file)
        key = self._save_key()
        watches = refresh_watches(store, key, self.campaign)
        view = store.view(key)
        entries = view.campaign.entries if view.campaign else []
        fired = [w for w, _ in watches if w.fired]
        alert = "".join(
            f" WATCH FIRED #{w.id} at {w.fired}: {w.description} (tell the player)." for w in fired
        )
        latest = self.journal(1)
        since = ""
        if latest and latest[0][2]:
            since = (
                f" Since the previous save ({latest[0][0]}): {len(latest[0][2])} changes "
                "(get_campaign_journal)."
            )
        recorded = self._recorded_dates()
        if len(recorded) >= 2:  # point to the trends for "how has it evolved?" (D-045)
            since += (
                f" The journal holds {len(recorded)} saves from {recorded[0]} to "
                f"{recorded[-1]}: for how the economy, army or growth evolved, use get_trends."
            )
        if not entries and not watches:
            return (
                "_Player context: nothing recorded for this campaign yet. If the player "
                "states goals, wants, limits or decisions in this conversation, record each "
                "with update_player_context and tell them; if they ask to be told when "
                f"something happens, set a watch with create_watch.{since}_"
            )
        counts: dict[str, int] = {}
        for entry in entries:
            label = KINDS[entry.kind].lower() if entry.kind in KINDS else entry.kind
            counts[label] = counts.get(label, 0) + 1
        waiting = len(watches) - len(fired)
        if waiting:
            counts["watches waiting"] = waiting
        listed = ", ".join(f"{n} {label}" for label, n in counts.items()) or "only fired watches"
        return (
            f"_Player context: {listed} recorded for this campaign (get_player_context; "
            f"follow them). Record new ones the player states with update_player_context.{alert}"
            f"{since}_"
        )

    # --- handlers -----------------------------------------------------------------------

    def _get_country_briefing(self, args: dict[str, Any]) -> str:
        tag = self._tag(args.get("country"))
        development = (self._development_rules, self._rules) if self.game_dir else None
        text = summarize(
            self.campaign,
            tag,
            reforms=self._imperial_reforms,
            power_rules=self._power_rules,
            development=development,
            coring=self._coring_rules if self.game_dir else None,
        )
        if self.game_dir is not None:  # a pointer to the trade tool (D-046)
            line = trade_line(trade_report(self.campaign, self._trade_graph, tag))
            if line:
                text = f"{text.rstrip()}\n\n_{line}_\n"
        return text

    def _get_wars(self, args: dict[str, Any]) -> str:
        tag = self._tag(args.get("country"))
        live = load_war_score(self.campaign, self.game_log) if tag == self.campaign.player else None
        return render_wars(
            self.campaign, war_reports(self.campaign, tag), live=live.data if live else None
        )

    def _get_budget(self, args: dict[str, Any]) -> str:
        tag = self._tag(args.get("country"))
        return render_budget(self.campaign, read_ledger(self.campaign, tag))

    def _get_trade(self, args: dict[str, Any]) -> str:
        tag = self._tag(args.get("country"))
        report = trade_report(self.campaign, self._trade_graph, tag)
        return render_trade(self.campaign, report)

    def _check_war(self, args: dict[str, Any]) -> str:
        target = self._tag(args["target"])
        attacker = self._tag(args.get("attacker"))
        text = render_war_check(
            self.campaign,
            check_war(self.campaign, target, attacker),
            load_casus_belli(self.campaign, self.game_log),
        )
        if self.game_dir is None:
            return text
        section = render_ae_section(self.campaign, self._ae_rules, self._rules, target, attacker)
        return f"{text}\n{section}"

    def _get_world_overview(self, args: dict[str, Any]) -> str:
        return render_world(self.campaign, world_overview(self.campaign))

    def _get_missions(self, args: dict[str, Any]) -> str:
        tag = self._tag(args.get("country"))
        tree = mission_tree(self.campaign, self._missions, tag, self._rules)
        brief = bool(args.get("brief"))
        return render_missions(self.campaign, tree, brief=brief, modifiers=self._modifiers)

    def _get_decisions(self, args: dict[str, Any]) -> str:
        tag = self._tag(args.get("country"))
        checks = check_decisions(
            self.campaign,
            self._rules,
            self._decisions,
            tag,
            missions=self._missions,
            formables_only=bool(args.get("formables_only")),
        )
        return render_decisions(self.campaign, tag, checks, self._modifiers)

    def _get_player_context(self, args: dict[str, Any]) -> str:
        key = self._save_key()
        store = PlayerContextStore(self.context_file)
        results = refresh_watches(store, key, self.campaign)
        view = store.view(key)
        lines = watch_lines(self.campaign, results)
        progress = {gid: render_goal(items) for gid, items in self.goal_progress().items()}
        return render_context(view, key, self.campaign.label(key.tag), lines, progress)

    def _track_goal(self, args: dict[str, Any]) -> str:
        if not args["measures"]:
            raise ToolInputError("track_goal needs at least one measure")
        try:
            measures = [validate_measure(item) for item in args["measures"]]
        except GoalError as exc:
            raise ToolInputError(str(exc)) from exc
        for measure in measures:  # names to tags, and keys the game files know
            self._check_measure(measure)
        store = PlayerContextStore(self.context_file)
        try:
            goal = store.track_goal(
                self._save_key(), int(args["goal"]), [measure_dict(m) for m in measures]
            )
        except PlayerContextError as exc:
            raise ToolInputError(str(exc)) from exc
        items = self.goal_progress().get(goal.id, [])
        return f"Goal #{goal.id} measured: {render_goal(items)}"

    def _check_measure(self, measure: Measure) -> None:
        """Resolve countries to tags and check keys against the game files."""
        if measure.kind == "country":
            measure.key = self._tag(measure.key)
        if measure.kind == "metric":
            for field_name in ("country", "other"):
                if measure.condition.get(field_name):
                    measure.condition[field_name] = self._tag(measure.condition[field_name])
        if self.game_dir is None:
            return
        if measure.kind == "mission" and self._missions.mission(measure.key) is None:
            raise ToolInputError(f"No mission '{measure.key}' in the game files.")
        if measure.kind == "formable" and self._decisions.get(measure.key) is None:
            raise ToolInputError(f"No decision '{measure.key}' in the game files.")
        if measure.kind == "provinces" and measure.key not in self._rules.geography:
            raise ToolInputError(
                f"'{measure.key}' is not an area, region or superregion (use the game's key, "
                "such as low_countries_region)."
            )

    def goal_progress(self) -> dict[int, list[GoalProgress]]:
        """Each measured goal's progress on this save (D-061)."""
        store = PlayerContextStore(self.context_file)
        view = store.view(self._save_key())
        goals = [e for e in (view.campaign.entries if view.campaign else []) if e.track]
        if not goals:
            return {}
        measures = {g.id: [m for m in map(measure_from, g.track) if m] for g in goals}
        kinds = {m.kind for ms in measures.values() for m in ms}
        missions: dict[str, Any] = {}
        decisions: dict[str, Any] = {}
        geography: dict[str, frozenset[int]] = {}
        cache = self.__dict__.setdefault("_goal_data", {})  # once per save: ~3 seconds
        if self.game_dir is not None:
            if "mission" in kinds:
                if "missions" not in cache:
                    tree = mission_tree(
                        self.campaign, self._missions, self.campaign.player, self._rules
                    )
                    cache["missions"] = {
                        m.mission.name: m for c in tree.columns for m in c.missions
                    }
                missions = cache["missions"]
            if "formable" in kinds:
                if "decisions" not in cache:
                    checks = check_decisions(
                        self.campaign,
                        self._rules,
                        self._decisions,
                        self.campaign.player,
                        self._missions,
                    )
                    cache["decisions"] = {c.decision.name: c for c in checks}
                decisions = cache["decisions"]
            if "provinces" in kinds:
                geography = self._rules.geography
        return {
            goal_id: [
                goal_progress(
                    self.campaign,
                    m,
                    missions=missions,
                    decisions=decisions,
                    geography=geography,
                )
                for m in items
            ]
            for goal_id, items in measures.items()
        }

    def _create_watch(self, args: dict[str, Any]) -> str:
        raw = args["conditions"]
        if not raw:
            raise ToolInputError("create_watch needs at least one condition")
        try:
            conditions = [validate_condition(item) for item in raw]
        except WatchError as exc:
            raise ToolInputError(str(exc)) from exc
        for condition in conditions:  # countries by name or tag, stored as tags
            if condition.country:
                condition.country = self._tag(condition.country)
            if condition.other:
                condition.other = self._tag(condition.other)
        key = self._save_key()
        store = PlayerContextStore(self.context_file)
        try:
            watch = store.add_watch(key, args["description"], conditions)
        except PlayerContextError as exc:
            raise ToolInputError(str(exc)) from exc
        readings = check(self.campaign, watch)
        now = "; ".join(
            f"{describe(r.condition, self.campaign)}: now {show(r.value)}" for r in readings
        )
        state = (
            "All conditions already hold: it fires with this save."
            if all(r.met for r in readings)
            else "It fires on the first save where all conditions hold."
        )
        return f"Watch #{watch.id} set: {watch.description}. {now}. {state}"

    def _update_player_context(self, args: dict[str, Any]) -> str:
        store = PlayerContextStore(self.context_file)
        key = self._save_key()
        action, text, entry_id = args["action"], args.get("text"), args.get("entry")
        try:
            if action == "add":
                if "kind" not in args or text is None:
                    raise ToolInputError("add needs `kind` and `text`")
                entry = store.add(key, args["kind"], text)
                if entry.kind == "goal":  # D-061: a goal is worth measuring
                    return (
                        f"Recorded #{entry.id} (goal): {entry.text}. Measure it with "
                        f"track_goal (goal {entry.id})."
                    )
                return f"Recorded #{entry.id} ({entry.kind}): {entry.text}"
            if action in ("remove", "replace"):
                if entry_id is None:
                    raise ToolInputError(f"{action} needs `entry` (the id)")
                if action == "remove":
                    removed = store.remove(key, entry_id)
                    if isinstance(removed, Watch):
                        return f"Removed watch #{removed.id}: {removed.description}"
                    return f"Removed #{removed.id} ({removed.kind}): {removed.text}"
                if text is None:
                    raise ToolInputError("replace needs `text`")
                entry = store.replace(key, entry_id, text)
                return f"Replaced #{entry_id} with #{entry.id} ({entry.kind}): {entry.text}"
        except PlayerContextError as exc:
            raise ToolInputError(str(exc)) from exc
        raise ToolInputError("`action` must be add, remove or replace")

    def remember_save(self) -> bool:
        """Record this save in the campaign's journal (D-043); once per in-game date.

        Returns:
            Whether a new snapshot was written.
        """
        key = self._save_key()
        campaign_key = PlayerContextStore(self.context_file).campaign_key(key)
        journal = JournalStore(journal_path(self.context_file))
        # The countries picked to compare with are tracked in full (D-049).
        snapshot = take_snapshot(self.campaign, extra=self._picked(), ready=self.ready())
        return journal.record(campaign_key, snapshot)

    def ready(self) -> ReadyNow | None:
        """What the player can claim on this save (D-055).

        ``None`` without the game files. Computed once per save (about 3 seconds).
        """
        if self.game_dir is None:
            return None
        if "_ready_now" not in self.__dict__:
            self.__dict__["_ready_now"] = ready_now(
                self.campaign, self._rules, self._missions, self._decisions
            )
        return self.__dict__["_ready_now"]

    def remember_other(self, campaign: Campaign) -> bool:
        """Record another save of this campaign in this campaign's journal (backfill)."""
        campaign_key = PlayerContextStore(self.context_file).campaign_key(self._save_key())
        journal = JournalStore(journal_path(self.context_file))
        return journal.record(campaign_key, take_snapshot(campaign, extra=self._picked()))

    def trends(self, countries: list[str] | None = None) -> dict[str, Any]:
        """The journal's numbers up to this save, and its main events, for charts (D-045).

        Args:
            countries: Tags to compare with; by default the ones the player picked
                (D-049), else their rivals.
        """
        key = self._save_key()
        view = PlayerContextStore(self.context_file).view(key)
        if view.campaign is None:
            return {"dates": [], "series": {}, "events": [], "compare": []}
        snapshots = JournalStore(journal_path(self.context_file)).snapshots(view.campaign.key)
        chosen = countries or view.campaign.compare or None
        return trend_data(snapshots, key.date, self.campaign, chosen)

    def compare_options(self) -> dict[str, Any]:
        """What the charts can compare with: the countries with a recorded history."""
        key = self._save_key()
        view = PlayerContextStore(self.context_file).view(key)
        tracked: set[str] = set()
        if view.campaign is not None:
            journal = JournalStore(journal_path(self.context_file))
            for snapshot in journal.snapshots(view.campaign.key):
                tracked.update(snapshot.get("others", {}))
        options = sorted(
            (t for t in tracked if t != key.tag and self.campaign.exists(t)),
            key=lambda t: self.campaign.name(t),
        )
        return {
            "picked": self._picked(),
            "options": [{"tag": t, "name": self.campaign.name(t)} for t in options],
        }

    def set_compare(self, countries: list[str]) -> list[str]:
        """Pick the countries the charts compare with (names or tags; none: rivals)."""
        tags = [self._tag(c) for c in countries]
        return PlayerContextStore(self.context_file).set_compare(self._save_key(), tags)

    def _picked(self) -> list[str]:
        view = PlayerContextStore(self.context_file).view(self._save_key())
        return list(view.campaign.compare) if view.campaign else []

    def _recorded_dates(self) -> list[str]:
        """Dates of the journal's snapshots up to this save, oldest first (cheap)."""
        key = self._save_key()
        view = PlayerContextStore(self.context_file).view(key)
        if view.campaign is None:
            return []
        snapshots = JournalStore(journal_path(self.context_file)).snapshots(view.campaign.key)
        dates = [str(s.get("date", "")) for s in snapshots]
        return [d for d in dates if _date_key(d) <= _date_key(key.date)]

    def journal(self, saves: int = JOURNAL_STEPS) -> list[tuple[str, str, list[str]]]:
        """The journal's steps up to this save, newest first (see :func:`journal_entries`)."""
        key = self._save_key()
        view = PlayerContextStore(self.context_file).view(key)
        if view.campaign is None:
            return []
        snapshots = JournalStore(journal_path(self.context_file)).snapshots(view.campaign.key)
        return journal_entries(snapshots, key.date, self.campaign, saves)

    def _get_trends(self, args: dict[str, Any]) -> str:
        countries = [self._tag(c) for c in args.get("countries") or []][:3]
        data = self.trends(countries or None)
        return render_trends(data, self.campaign.label(self.campaign.player))

    def _get_campaign_journal(self, args: dict[str, Any]) -> str:
        saves = min(max(int(args.get("saves") or JOURNAL_STEPS), 1), 30)
        key = self._save_key()
        view = PlayerContextStore(self.context_file).view(key)
        recorded = 0
        if view.campaign is not None:
            recorded = len(
                JournalStore(journal_path(self.context_file)).snapshots(view.campaign.key)
            )
        return render_journal(self.journal(saves), self.campaign.label(key.tag), recorded)

    def _save_key(self) -> SaveKey:
        campaign = self.campaign
        return SaveKey(campaign.campaign_id, campaign.player, campaign.date)

    def player_plan(self) -> dict[str, Any]:
        """The player's context and watches as plain values, for the panel (D-041).

        Checks the watches on this save first, so ones that now hold are fired.
        """
        store = PlayerContextStore(self.context_file)
        key = self._save_key()
        results = refresh_watches(store, key, self.campaign)
        view = store.view(key)
        entries = [*(view.campaign.entries if view.campaign else []), *view.player]
        progress = {gid: render_goal(items) for gid, items in self.goal_progress().items()}
        return {
            "entries": [
                {
                    "id": e.id,
                    "kind": e.kind,
                    "label": PANEL_LABELS.get(e.kind, e.kind),
                    "text": e.text,
                    "progress": progress.get(e.id, ""),  # D-061
                }
                for e in entries
            ],
            "waiting": [
                {
                    "id": w.id,
                    "description": w.description,
                    "now": "; ".join(
                        f"{describe(r.condition, self.campaign)} (now {show(r.value)})"
                        for r in readings
                    ),
                }
                for w, readings in results
                if not w.fired
            ],
            "fired": [
                {"id": w.id, "description": w.description, "fired": w.fired}
                for w, _ in results
                if w.fired
            ],
            "since": [
                {"from": start, "to": end, "events": events}
                for start, end, events in self.journal(1)
            ],
        }

    def _search_wiki(self, args: dict[str, Any]) -> str:
        query = str(args["query"])
        limit = min(max(int(args.get("max_results") or WIKI_RESULTS), 1), 8)
        try:
            return render_hits(query, search(query, limit))
        except FileNotFoundError as exc:
            return str(exc)

    def _get_expansion_targets(self, args: dict[str, Any]) -> str:
        tag = self._tag(args.get("country"))
        report = find_targets(self.campaign, self._rules, self._missions, self._decisions, tag)
        return render_targets(
            self.campaign, report, casus_belli=load_casus_belli(self.campaign, self.game_log)
        )

    def _get_recommendations(self, args: dict[str, Any]) -> str:
        tag = self._tag(args.get("country"))
        player = tag == self.campaign.player
        goals: list[Goal] = []
        if player:
            view = PlayerContextStore(self.context_file).view(self._save_key())
            goals = goals_from(view.campaign.entries if view.campaign else [])
        missing = []
        inputs: dict[str, Any] = {}
        # The probe mod's casus belli and live war score (D-051, D-063), for the player.
        cb = load_casus_belli(self.campaign, self.game_log) if player else None
        if cb is not None and cb.data is not None:
            inputs["casus_belli"] = cb.data
        else:
            missing.append(
                (cb.reason if cb else "Casus belli are only known for the player's country").rstrip(
                    "."
                )
            )
        live = load_war_score(self.campaign, self.game_log) if player else None
        wars = war_reports(self.campaign, tag)
        if self.game_dir is None:
            missing.append("missions, nations, monarch power, coring and targets (no game files)")
        else:
            inputs |= {
                "ready": (
                    self.ready()
                    if player
                    else ready_now(self.campaign, self._rules, self._missions, self._decisions, tag)
                ),
                "tree": mission_tree(self.campaign, self._missions, tag, self._rules),
                "power": (
                    power_report(self.campaign, self._power_rules, tag)
                    if self._power_rules
                    else None
                ),
                "coring": coring_costs(self.campaign, self._coring_rules, self._rules, tag),
                "targets": find_targets(
                    self.campaign, self._rules, self._missions, self._decisions, tag
                ),
            }
        found = recommend(
            self.campaign,
            tag=tag,
            ledger=read_ledger(self.campaign, tag),
            goals=goals,
            wars=wars,
            live=live.data if live else None,
            **inputs,
        )
        return render_recommendations(self.campaign, found, goals, tag, missing)

    # --- helpers ------------------------------------------------------------------------

    def _tag(self, country: str | None) -> str:
        # Smaller models write "player" or "me" for the player instead of leaving the
        # field out (D-062); those words are no country's name.
        if not country or " ".join(country.lower().split()) in PLAYER_WORDS:
            return self.campaign.player
        return self.campaign.resolve_country(country)

    def _game_dir(self) -> Path:
        if self.game_dir is None:
            raise ToolInputError("This tool needs the game files, and EU4_GAME_DIR is not set.")
        return self.game_dir

    @cached_property
    def _missions(self) -> MissionLibrary:
        return MissionLibrary.load(self._game_dir())

    @cached_property
    def _decisions(self) -> DecisionLibrary:
        return DecisionLibrary.load(self._game_dir())

    @cached_property
    def _rules(self) -> GameRules:
        return GameRules.load(self._game_dir())

    @cached_property
    def _modifiers(self) -> ModifierLibrary:
        return ModifierLibrary.load(self._game_dir())

    @cached_property
    def _development_rules(self) -> DevelopmentRules:
        return DevelopmentRules.load(self._game_dir())

    @cached_property
    def _ae_rules(self) -> AeRules:
        return AeRules.load(self._game_dir())

    @cached_property
    def _trade_graph(self) -> TradeGraph:
        return TradeGraph.load(self._game_dir())

    @cached_property
    def _coring_rules(self) -> CoringRules:
        return CoringRules.load(self._game_dir())

    @cached_property
    def _power_rules(self) -> PowerRules | None:
        """Optional: without the game files the briefing leaves out what points buy."""
        return PowerRules.load(self.game_dir) if self.game_dir else None

    @cached_property
    def _imperial_reforms(self) -> ImperialReformLibrary | None:
        """Optional: briefings work without the game files, just without the next reform."""
        return ImperialReformLibrary.load(self.game_dir) if self.game_dir else None


def validate(name: str, arguments: Any) -> dict[str, Any]:
    """Check tool arguments against the tool's schema.

    Tool inputs arrive as model output (and, with streamed inputs, may be truncated), so
    they are validated before anything runs.

    Raises:
        KeyError: Unknown tool.
        ToolInputError: Wrong shape, unknown or missing fields, or wrong types.
    """
    schema = _SCHEMAS[name]
    if not isinstance(arguments, dict):
        raise ToolInputError(f"{name} expects an object of arguments")
    unknown = set(arguments) - set(schema)
    if unknown:
        raise ToolInputError(f"{name} got unknown arguments: {', '.join(sorted(unknown))}")
    for field, spec in schema.items():
        if field not in arguments:
            if spec.required:
                raise ToolInputError(f"{name} needs `{field}`")
            continue
        value = arguments[field]
        if not isinstance(value, spec.kind) or (spec.kind is str and not value.strip()):
            raise ToolInputError(f"{name}: `{field}` must be a {spec.kind.__name__}")
    return arguments


__all__ = ["TOOL_DEFINITIONS", "CountryLookupError", "ToolInputError", "Toolbox", "validate"]
