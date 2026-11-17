"""A country's trade: power in each node, merchants and what feeds its home node (D-046).

The save's ``trade`` block has one entry per trade node with its totals and one entry
per country present in it. From a country's entries:

* ``val``: its trade power there (``province_power`` from provinces, ``ship_power`` from
  light ships protecting trade, ``light_ship`` how many);
* ``has_trader``: a merchant of it is there, steering when ``type=1``, else collecting;
* ``has_capital``: it is the country's home node (where its trade capital is);
* ``money``: what it collects there a month.

A node's value is what stays in it (``current``) plus what flows on (``outgoing``); its
``total`` is everyone's trade power. Which nodes feed the home node comes from the game
files (:class:`TradeGraph`); the direction a steering merchant pushes is not in the
save, so the report says whether a node lies upstream of home.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chancellor.context.campaign import Campaign, as_list
from chancellor.game.trade_nodes import TradeGraph
from chancellor.save.parser import LazyBlock, get_all


@dataclass
class NodeShare:
    """A country's place in one trade node.

    Attributes:
        node: The node's key (``venice``).
        name: Its name in the player's language.
        value: Trade value in the node (kept there plus flowing on), ducats a month.
        total_power: Everyone's trade power there.
        power: The country's trade power there.
        province_power: The part from its provinces.
        ship_power: The part from light ships protecting trade.
        light_ships: Light ships it has protecting trade there.
        merchant: ``collecting``, ``steering`` or ``None``.
        money: What it collects there a month.
        home: Whether it is the country's home node.
        steps_to_home: How many links downstream to the home node (``None``: not upstream).
    """

    node: str
    name: str
    value: float
    total_power: float
    power: float
    province_power: float = 0.0
    ship_power: float = 0.0
    light_ships: int = 0
    merchant: str | None = None
    money: float = 0.0
    home: bool = False
    steps_to_home: int | None = None

    @property
    def share(self) -> float:
        """The country's share of the node's trade power."""
        return self.power / self.total_power if self.total_power else 0.0


@dataclass
class TradeReport:
    """A country's trade.

    Attributes:
        tag: The country.
        home: Its home node, if any.
        nodes: Nodes where it has trade power: home, then those feeding it, then the rest.
        upstream_without_power: Nodes feeding home where it has no power, by value.
        embargoed_by: Countries embargoing it.
        home_is_end: Whether the home node is an end node (its trade goes no further).
    """

    tag: str
    home: NodeShare | None
    nodes: list[NodeShare] = field(default_factory=list)
    upstream_without_power: list[tuple[str, float, int]] = field(default_factory=list)
    embargoed_by: list[str] = field(default_factory=list)
    home_is_end: bool = False


def trade_report(campaign: Campaign, graph: TradeGraph, tag: str | None = None) -> TradeReport:
    """Read a country's trade from the save (the player's by default).

    Raises:
        KeyError: If the country is not in the save.
    """
    tag = tag or campaign.player
    country = campaign.country(tag)
    if country is None:
        raise KeyError(f"Country {tag} is not in the save")
    block = campaign.gamestate.get("trade", {})
    trade = block.parse() if isinstance(block, LazyBlock) else block
    nodes = [n for n in get_all(trade, "node") if isinstance(n, dict)] if trade else []

    shares = []
    values: dict[str, float] = {}
    for node in nodes:
        key = str(node.get("definitions", ""))
        value = _float(node.get("current")) + _float(node.get("outgoing"))
        values[key] = value
        entry = node.get(tag)
        if not isinstance(entry, dict) or _float(entry.get("val")) <= 0:
            continue
        merchant = None
        if entry.get("has_trader") is True:
            merchant = "steering" if entry.get("type") == 1 else "collecting"
        shares.append(
            NodeShare(
                node=key,
                name=campaign.text(key),
                value=value,
                total_power=_float(node.get("total")),
                power=_float(entry.get("val")),
                province_power=_float(entry.get("province_power")),
                ship_power=_float(entry.get("ship_power")),
                light_ships=int(_float(entry.get("light_ship"))),
                merchant=merchant,
                money=_float(entry.get("money")),
                home=entry.get("has_capital") is True,
            )
        )
    home = next((s for s in shares if s.home), None)
    upstream = graph.upstream(home.node) if home else {}
    for share in shares:
        share.steps_to_home = upstream.get(share.node)
    held = {s.node for s in shares}
    missing = sorted(
        ((n, values.get(n, 0.0), steps) for n, steps in upstream.items() if n not in held),
        key=lambda item: -item[1],
    )
    # Home first, then the nodes that feed it (nearest first), then the rest by value.
    shares.sort(key=lambda s: (not s.home, s.steps_to_home is None, s.steps_to_home or 0, -s.value))
    embargo = country.get("trade_embargoed_by")
    return TradeReport(
        tag=tag,
        home=home,
        nodes=shares,
        upstream_without_power=missing,
        embargoed_by=[str(t) for t in as_list(embargo) if isinstance(t, str)],
        home_is_end=home is not None and home.node in graph.ends,
    )


def render_trade(campaign: Campaign, report: TradeReport, shown: int = 12) -> str:
    """Markdown for the ``get_trade`` tool."""
    lines = [f"# Trade: {campaign.label(report.tag)}", ""]
    home = report.home
    if home is None:
        lines.append("No home trade node found: the country has no trade power recorded.")
        return "\n".join(lines) + "\n"
    merchants = [s for s in report.nodes if s.merchant]
    lines += [
        f"- Home node: **{home.name}**"
        + (" (an end node: its trade goes nowhere else)" if report.home_is_end else "")
        + f": {_pct(home.share)} of its trade power ({home.power:.0f} of "
        f"{home.total_power:.0f}), value {home.value:.1f} a month, collecting "
        f"{home.money:.2f} a month there.",
        f"- Merchants placed: {len(merchants)}: "
        + (", ".join(f"{s.name} ({s.merchant})" for s in merchants) or "none")
        + ".",
        "- Light ships protecting trade: "
        + (
            ", ".join(f"{s.light_ships} in {s.name}" for s in report.nodes if s.light_ships)
            or "none"
        )
        + ".",
    ]
    if report.embargoed_by:
        names = ", ".join(campaign.name(t) for t in report.embargoed_by)
        lines.append(f"- Embargoed by: {names} (lowers its trade power where they meet).")
    lines += [
        "",
        "## Trade power by node",
        "",
        "| Node | Value | Your power | Share | Base: provinces / ships | Merchant | Feeds home |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for share in report.nodes[:shown]:
        feeds = (
            "home"
            if share.home
            else f"yes, {share.steps_to_home} step{'s' if share.steps_to_home != 1 else ''}"
            if share.steps_to_home
            else "no"
        )
        lines.append(
            f"| {share.name} | {share.value:.1f} | {share.power:.0f} | {_pct(share.share)} "
            f"| {share.province_power:.0f} / {share.ship_power:.0f} "
            f"| {share.merchant or '-'} | {feeds} |"
        )
    if len(report.nodes) > shown:
        lines.append(f"\n{len(report.nodes) - shown} smaller nodes left out.")
    if report.upstream_without_power:
        lines += [
            "",
            f"Nodes feeding {home.name} where the country has no trade power: "
            + ", ".join(
                f"{campaign.text(n)} (value {v:.1f}, {s} step{'s' if s != 1 else ''})"
                for n, v, s in report.upstream_without_power[:6]
            )
            + ".",
        ]
    lines += [
        "",
        "_From the save's trade nodes and the game's node map. The save does not record "
        "which way a steering merchant pushes; 'Feeds home' says whether the node's trade "
        "can reach the home node at all. For how trade works and strategy, search_wiki "
        "('trade', 'trade steering')._",
    ]
    return "\n".join(lines) + "\n"


def trade_line(report: TradeReport) -> str | None:
    """One briefing line: the home node, the share there and the merchants."""
    home = report.home
    if home is None:
        return None
    merchants = [s for s in report.nodes if s.merchant]
    return (
        f"Trade: home node {home.name}, {_pct(home.share)} of its power, collecting "
        f"{home.money:.2f} a month; {len(merchants)} merchants placed. Node by node, with "
        "what feeds the home node: get_trade."
    )


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _float(value: Any) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0
