"""The trade node map, from ``common/tradenodes`` (D-046).

Trade flows downstream along fixed links, from node to node, until an end node
(Venice, the English Channel, Genoa ...). Which nodes feed the player's home node is
what decides where steering merchants pay off, and the save does not say it: it is in
the game files, as each node's ``outgoing`` links.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from chancellor.game.cache import cached
from chancellor.game.modifiers import _decode
from chancellor.save.parser import get_all, parse


@dataclass
class TradeGraph:
    """The trade nodes and their links.

    Attributes:
        outgoing: Node → the nodes its trade flows to, in the file's order.
        location: Node → the province its marker sits in.
        ends: Nodes where trade stops (no outgoing links).
    """

    outgoing: dict[str, list[str]] = field(default_factory=dict)
    location: dict[str, int] = field(default_factory=dict)
    ends: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, game_dir: Path) -> TradeGraph:
        """Load from the game installation, reusing the on-disk cache when possible."""
        folder = game_dir / "common" / "tradenodes"
        return cached("trade_graph", [folder], lambda: cls.parse_folder(folder))

    @classmethod
    def parse_folder(cls, folder: Path) -> TradeGraph:
        """Read every file of ``common/tradenodes``."""
        graph = cls()
        for path in sorted(folder.glob("*.txt")) if folder.is_dir() else []:
            graph.add_document(_decode(path.read_bytes()))
        return graph

    def add_document(self, text: str) -> None:
        """Add the nodes of one file."""
        for name, block in parse(text).items():
            if not isinstance(block, dict):
                continue
            links = [
                str(link["name"])
                for link in get_all(block, "outgoing")
                if isinstance(link, dict) and link.get("name")
            ]
            self.outgoing[name] = links
            if isinstance(block.get("location"), int):
                self.location[name] = block["location"]
            if not links or block.get("end") is True:
                self.ends.add(name)

    def upstream(self, node: str) -> dict[str, int]:
        """Every node whose trade reaches ``node``, with how many steps away it is."""
        incoming: dict[str, list[str]] = {}
        for source, targets in self.outgoing.items():
            for target in targets:
                incoming.setdefault(target, []).append(source)
        found: dict[str, int] = {}
        frontier = [node]
        steps = 0
        while frontier:
            steps += 1
            following = []
            for current in frontier:
                for source in incoming.get(current, []):
                    if source not in found and source != node:
                        found[source] = steps
                        following.append(source)
            frontier = following
        return found

    def incoming(self, node: str) -> list[str]:
        """The nodes that flow straight into ``node``."""
        return [source for source, targets in self.outgoing.items() if node in targets]
