"""Turn MediaWiki wikitext into plain sections for searching (D-032).

Pages from the game wiki arrive as wikitext. Searching it as is would match markup and
show it to Claude, so each page becomes a list of :class:`Section`: its heading path and
plain text. Templates are dropped except for the few that carry text (coloured numbers,
"main article" notes) or the game version a page was checked for (``{{SVersion|1.25}}``);
links keep their label; files, categories, references and comments go; tables become
one line per row with cells joined by ``|``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_VERSION_TEMPLATES = {"version", "sversion"}
# Templates with no text worth keeping (maintenance notes, layout, icons, navigation).
_DROPPED_TEMPLATES = {
    "expand",
    "outdated",
    "stub",
    "cleanup",
    "icon",
    "iconify",
    "clear",
    "toc",
    "tocright",
    "box",
    "boxbegin",
    "boxend",
    "navbox",
    "infobox",
    "image",
    "flag",
    "rq",
    "anchor",
    "disambiguation",
    "for",
}
# Templates whose first argument is the text to show (e.g. {{green|+10%}}).
_FIRST_ARGUMENT_TEMPLATES = {
    "green",
    "red",
    "yellow",
    "orange",
    "blue",
    "color",
    "tooltip",
    "hover",
}
_MAIN_TEMPLATES = {"main", "see also", "seealso", "further"}
_HEADING = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$")
_FILE_LINK = re.compile(
    r"\[\[(?:File|Image|Category|Media):[^\[\]]*(?:\[\[[^\]]*\]\][^\[\]]*)*\]\]", re.I
)
_LINK = re.compile(r"\[\[([^\[\]|]*)(?:\|([^\[\]]*))?\]\]")
_EXTERNAL = re.compile(r"\[(?:https?:)?//\S+\s+([^\]]+)\]")
_REF = re.compile(r"<ref[^>/]*?/>|<ref[^>]*>.*?</ref>", re.S | re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_REDIRECT = re.compile(r"^\s*#REDIRECT\s*\[\[([^\]|]+)\]\]", re.I)


@dataclass(frozen=True)
class Section:
    """One section of a wiki page.

    Attributes:
        page: Page title.
        heading: Heading path below the page, e.g. ``"Relation modifiers > Aggressive
            expansion"`` (empty for the page's introduction).
        anchor: The last heading, used in the page's URL (empty for the introduction).
        version: The game version the section (or its page) was last checked for.
        text: Plain text.
    """

    page: str
    heading: str
    anchor: str
    version: str | None
    text: str


def redirect_target(text: str) -> str | None:
    """``#REDIRECT [[Relations#Aggressive expansion]]`` → ``Relations#Aggressive expansion``."""
    match = _REDIRECT.match(text)
    return match.group(1).strip() if match else None


def page_sections(title: str, text: str) -> list[Section]:
    """Split a page's wikitext into plain sections with their headings and versions."""
    text = _COMMENT.sub("", text)
    text = _REF.sub("", text)
    page_version = _first_version(text)
    sections: list[Section] = []
    path: list[str] = []
    versions: list[str | None] = []  # the version at each heading level of ``path``
    lines: list[str] = []
    version = page_version

    def flush() -> None:
        body = clean(" \n".join(lines))
        if body:
            heading = " > ".join(path)
            sections.append(Section(title, heading, path[-1] if path else "", version, body))

    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            flush()
            level = len(match.group(1)) - 2
            path = [*path[:level], clean(match.group(2))]
            # A subsection starts with the version of the section it belongs to.
            versions = versions[:level]
            version = versions[-1] if versions else page_version
            versions.append(version)
            lines = []
            continue
        found = _first_version(line)
        if found:
            version = found
            if versions:
                versions[-1] = found
        lines.append(line)
    flush()
    return sections


def clean(text: str) -> str:
    """Plain text from wikitext: no templates, links, tables markup or formatting."""
    text = _templates(text)
    text = _FILE_LINK.sub("", text)
    text = _LINK.sub(lambda m: (m.group(2) or m.group(1).split("#")[-1]).strip(), text)
    text = _EXTERNAL.sub(r"\1", text)
    text = _TAG.sub("", text)
    text = text.replace("'''", "").replace("''", "")
    text = _tables(text)
    text = re.sub(r"^[*#:;]+\s*", "- ", text, flags=re.M)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line and line not in {"-", "|"})
    return text.strip()


# --- internals -------------------------------------------------------------------------------


def _first_version(text: str) -> str | None:
    match = re.search(r"\{\{\s*S?Version\s*\|\s*([0-9][0-9.]*)", text, re.I)
    return match.group(1) if match else None


def _templates(text: str) -> str:
    """Replace templates from the innermost out, keeping only text worth reading."""
    pattern = re.compile(r"\{\{([^{}]*)\}\}")
    for _ in range(20):  # nesting depth
        replaced = pattern.sub(lambda m: _template(m.group(1)), text)
        if replaced == text:
            break
        text = replaced
    return text.replace("{{", "").replace("}}", "")


def _template(body: str) -> str:
    parts = [p.strip() for p in body.split("|")]
    name = parts[0].lower().replace("_", " ").strip()
    args = [p for p in parts[1:] if "=" not in p.split(" ")[0]]
    if name in _VERSION_TEMPLATES or name in _DROPPED_TEMPLATES or name.startswith("#"):
        return ""
    if name in _MAIN_TEMPLATES:
        return f"(See: {', '.join(args)}.)" if args else ""
    if name in _FIRST_ARGUMENT_TEMPLATES:
        return args[0] if args else ""
    # Unknown templates: keep a short last argument (often a number or a name).
    if args and len(args[-1]) <= 60:
        return args[-1]
    return ""


def _tables(text: str) -> str:
    """Tables become one line per row with cells joined by ``|``."""
    out: list[str] = []
    row: list[str] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("{|"):
            in_table, row = True, []
            continue
        if not in_table:
            out.append(line)
            continue
        if stripped.startswith("|}"):
            if row:
                out.append(" | ".join(row))
            in_table, row = False, []
            continue
        if stripped.startswith("|-") or stripped.startswith("|+"):
            if row:
                out.append(" | ".join(row))
            row = []
            continue
        if stripped.startswith(("|", "!")):
            for cell in re.split(r"\|\||!!", stripped[1:]):
                # Drop cell attributes: `style="..." | text`.
                if "|" in cell and "=" in cell.split("|")[0]:
                    cell = cell.split("|", 1)[1]
                cell = cell.strip()
                if cell:
                    row.append(cell)
        elif stripped and row:
            row[-1] += " " + stripped
    if row:
        out.append(" | ".join(row))
    return "\n".join(out)
