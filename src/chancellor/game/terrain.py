"""Each province's terrain, from the map files (D-031).

The save does not store terrain, yet it changes what developing a province costs
(mountains +50%, hills +25%, ...). The game takes it from the map:

* ``map/terrain.txt``: terrain categories with their modifiers
  (``local_development_cost``), provinces fixed to a category (``terrain_override``),
  and which colour index of ``terrain.bmp`` belongs to which category;
* ``map/provinces.bmp``: every province in its own colour, listed in
  ``map/definition.csv``;
* ``map/terrain.bmp``: an 8-bit image whose colour indices are terrain.

A province's terrain is its override if it has one, otherwise the category covering most
of its pixels. The images are 5632x2048, so every second pixel in each direction is
sampled (about 2.9 million) and the result is cached until the game files change.
"""

from __future__ import annotations

import struct
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chancellor.game.cache import cached
from chancellor.game.modifiers import _decode
from chancellor.save.parser import parse

_SAMPLE_STEP = 2


@dataclass
class TerrainMap:
    """Terrain categories and the terrain of each province.

    Attributes:
        categories: Category → its numeric modifiers (``local_development_cost`` ...).
        provinces: Province id → its terrain category.
    """

    categories: dict[str, dict[str, float]] = field(default_factory=dict)
    provinces: dict[int, str] = field(default_factory=dict)

    def development_cost(self, province: int) -> float:
        """The terrain's change to the cost of developing a province (0 if unknown)."""
        category = self.provinces.get(province)
        return (
            self.categories.get(category, {}).get("local_development_cost", 0.0)
            if category
            else 0.0
        )

    @classmethod
    def load(cls, game_dir: Path) -> TerrainMap:
        """Load from the game installation, reusing the on-disk cache when possible."""
        map_dir = game_dir / "map"
        sources = [map_dir / name for name in ("terrain.txt", "definition.csv")]
        sources += [map_dir / "provinces.bmp", map_dir / "terrain.bmp"]
        return cached("terrain_map", sources, lambda: cls.parse_game(game_dir))

    @classmethod
    def parse_game(cls, game_dir: Path) -> TerrainMap:
        """Work out every province's terrain from the map files (empty without them)."""
        map_dir = game_dir / "map"
        needed = ("terrain.txt", "definition.csv", "provinces.bmp", "terrain.bmp")
        if not all((map_dir / name).is_file() for name in needed):
            return cls()
        document = parse(_decode((map_dir / "terrain.txt").read_bytes()))
        categories, overrides = _categories(document.get("categories"))
        palette = _palette(document.get("terrain"))
        colours = parse_definitions(_decode((map_dir / "definition.csv").read_bytes()))
        provinces = majority_terrain(
            (map_dir / "provinces.bmp").read_bytes(),
            (map_dir / "terrain.bmp").read_bytes(),
            colours,
            palette,
        )
        provinces.update(overrides)
        return cls(categories, provinces)


def parse_definitions(text: str) -> dict[tuple[int, int, int], int]:
    """``definition.csv``: (red, green, blue) → province id."""
    colours = {}
    for line in text.splitlines()[1:]:
        parts = line.split(";")
        if len(parts) >= 4 and all(p.strip().isdigit() for p in parts[:4]):
            province, red, green, blue = (int(p) for p in parts[:4])
            colours[(red, green, blue)] = province
    return colours


def majority_terrain(
    provinces_bmp: bytes,
    terrain_bmp: bytes,
    colours: dict[tuple[int, int, int], int],
    palette: dict[int, str],
    step: int = _SAMPLE_STEP,
) -> dict[int, str]:
    """The terrain category covering most of each province's (sampled) pixels.

    Args:
        provinces_bmp: The 24-bit province image.
        terrain_bmp: The 8-bit terrain image of the same size.
        colours: Province colour → id (``definition.csv``).
        palette: Terrain image colour index → category.
        step: Sample every ``step``-th pixel in each direction.
    """
    width, height, offset, bits = _bmp_header(provinces_bmp)
    t_width, t_height, t_offset, t_bits = _bmp_header(terrain_bmp)
    if (width, height) != (t_width, t_height) or bits != 24 or t_bits != 8:
        raise ValueError("The province and terrain images do not match")
    row = (width * 3 + 3) // 4 * 4
    t_row = (width + 3) // 4 * 4
    counts: dict[int, Counter[str]] = {}
    for y in range(0, height, step):
        base = offset + y * row
        t_base = t_offset + y * t_row
        pixels = provinces_bmp[base : base + width * 3]
        terrain = terrain_bmp[t_base : t_base + width]
        for x in range(0, width, step):
            category = palette.get(terrain[x])
            if category is None:
                continue
            i = x * 3
            province = colours.get((pixels[i + 2], pixels[i + 1], pixels[i]))  # stored as BGR
            if province is not None:
                counts.setdefault(province, Counter())[category] += 1
    return {province: tally.most_common(1)[0][0] for province, tally in counts.items()}


def _bmp_header(data: bytes) -> tuple[int, int, int, int]:
    """Width, height, pixel data offset and bits per pixel of a bottom-up BMP."""
    if data[:2] != b"BM":
        raise ValueError("Not a BMP image")
    offset = struct.unpack_from("<I", data, 10)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    bits = struct.unpack_from("<H", data, 28)[0]
    return width, abs(height), offset, bits


def _categories(block: Any) -> tuple[dict[str, dict[str, float]], dict[int, str]]:
    """Terrain categories: their numeric modifiers, and the provinces fixed to each."""
    categories: dict[str, dict[str, float]] = {}
    overrides: dict[int, str] = {}
    if not isinstance(block, dict):
        return categories, overrides
    for name, body in block.items():
        if not isinstance(body, dict):
            continue
        categories[name] = {
            k: float(v)
            for k, v in body.items()
            if isinstance(v, int | float) and not isinstance(v, bool)
        }
        fixed = body.get("terrain_override")
        for province in fixed if isinstance(fixed, list) else [fixed]:
            if isinstance(province, int):
                overrides[province] = name
    return categories, overrides


def _palette(block: Any) -> dict[int, str]:
    """``terrain = { grasslands = { type = grasslands color = { 0 } } }``: index → category."""
    palette: dict[int, str] = {}
    if not isinstance(block, dict):
        return palette
    for body in block.values():
        if not isinstance(body, dict):
            continue
        kind, colour = body.get("type"), body.get("color")
        index = colour[0] if isinstance(colour, list) and colour else colour
        if isinstance(kind, str) and isinstance(index, int):
            palette[index] = kind
    return palette
