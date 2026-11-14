"""A local, searchable copy of the game wiki (D-032).

The wiki blocks automated downloads, so the player exports pages from it in their own
browser (``Special:Export``, logged in) and ``chancellor wiki-import`` indexes the XML
files here. Pages become plain sections (:mod:`chancellor.wiki.wikitext`) in a SQLite
full-text index (FTS5, BM25 ranking, English stemming) kept with the app's state, out of
the cache and out of the repository. Redirects are kept as aliases of their target, so
searching for "aggressive expansion" finds the section on the "Relations" page.

Every result carries its page, section, link and the game version it was last checked
for, because the wiki lags behind patches.
"""

from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from chancellor.app.state import state_dir
from chancellor.wiki.wikitext import page_sections, redirect_target

WIKI_URL = "https://eu4.paradoxwikis.com/"
_DB = "wiki.sqlite"
_MAX_CHUNK = 1500  # characters per indexed chunk; long sections are split at lines


@dataclass(frozen=True)
class WikiHit:
    """One search result."""

    page: str
    heading: str
    version: str | None
    url: str
    text: str


@dataclass(frozen=True)
class ImportReport:
    """What an import added."""

    pages: int
    redirects: int
    chunks: int


def wiki_path() -> Path:
    """Where the index lives."""
    return state_dir() / _DB


def read_exports(paths: Iterable[Path]) -> dict[str, str]:
    """Page title → wikitext, from one or more MediaWiki XML exports (later files win)."""
    pages: dict[str, str] = {}
    for path in paths:
        root = ET.parse(path).getroot()
        namespace = root.tag.split("}")[0].strip("{") if root.tag.startswith("{") else ""
        ns = {"mw": namespace} if namespace else {}
        prefix = "mw:" if namespace else ""
        for page in root.findall(f"{prefix}page", ns):
            title = page.findtext(f"{prefix}title", namespaces=ns)
            text = page.findtext(f"{prefix}revision/{prefix}text", namespaces=ns)
            if title and text is not None:
                pages[title] = text
    return pages


def import_exports(paths: Iterable[Path], database: Path | None = None) -> ImportReport:
    """Build the index from MediaWiki XML exports, replacing any earlier one."""
    pages = read_exports(paths)
    database = database or wiki_path()
    database.parent.mkdir(parents=True, exist_ok=True)
    temporary = database.with_suffix(".tmp")
    temporary.unlink(missing_ok=True)
    aliases: dict[tuple[str, str], list[str]] = {}
    redirects = 0
    for title, text in pages.items():
        target = redirect_target(text)
        if target:
            redirects += 1
            page, _, anchor = target.partition("#")
            aliases.setdefault((page.strip(), anchor.strip()), []).append(title)

    connection = sqlite3.connect(temporary)
    chunks = 0
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE chunks USING fts5("
            "title, body, page UNINDEXED, heading UNINDEXED, anchor UNINDEXED, "
            "version UNINDEXED, tokenize = 'porter unicode61 remove_diacritics 2')"
        )
        for title, text in pages.items():
            if redirect_target(text):
                continue
            page_aliases = aliases.get((title, ""), [])
            for section in page_sections(title, text):
                names = [title, section.heading, *page_aliases]
                names += aliases.get((title, section.anchor), [])
                for piece in _split(section.text):
                    connection.execute(
                        "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            " ".join(n for n in names if n),
                            piece,
                            section.page,
                            section.heading,
                            section.anchor,
                            section.version,
                        ),
                    )
                    chunks += 1
        connection.commit()
    finally:
        connection.close()
    temporary.replace(database)
    return ImportReport(len(pages) - redirects, redirects, chunks)


def search(query: str, limit: int = 5, database: Path | None = None) -> list[WikiHit]:
    """The best-matching sections for ``query`` (English words work best).

    Raises:
        FileNotFoundError: If the wiki has not been imported.
    """
    database = database or wiki_path()
    if not database.is_file():
        raise FileNotFoundError(
            "The wiki is not imported: export pages from the wiki (Special:Export) and run "
            "`chancellor wiki-import FILE...`."
        )
    terms = _terms(query)
    if not terms:
        return []
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute(
            "SELECT page, heading, anchor, version, body FROM chunks WHERE chunks MATCH ? "
            "ORDER BY bm25(chunks, 8.0, 1.0) LIMIT ?",
            (" OR ".join(terms), limit),
        ).fetchall()
    finally:
        connection.close()
    return [
        WikiHit(page, heading, version, _url(page, anchor), body)
        for page, heading, anchor, version, body in rows
    ]


def render_hits(query: str, hits: list[WikiHit], max_chars: int = 1200) -> str:
    """Markdown for the search tool: each hit with its source and version."""
    if not hits:
        return f"No wiki section matches '{query}'. Try other English game terms."
    lines = [f"# Wiki: {query}", ""]
    for hit in hits:
        where = hit.page + (f" > {hit.heading}" if hit.heading else "")
        checked = f", last checked for game version {hit.version}" if hit.version else ""
        text = (
            hit.text
            if len(hit.text) <= max_chars
            else hit.text[:max_chars].rsplit(" ", 1)[0] + " …"
        )
        lines += [f"## {where}", f"_Source: {hit.url}{checked}._", "", text, ""]
    lines.append(
        "_From the Europa Universalis 4 Wiki (community-written; it can lag behind the "
        "installed 1.37). Numbers from the save and the computed mechanics take precedence._"
    )
    return "\n".join(lines) + "\n"


def _terms(query: str) -> list[str]:
    """FTS5 terms from free text: words of two or more letters, quoted."""
    words = []
    for word in "".join(c if c.isalnum() else " " for c in query.lower()).split():
        if len(word) >= 2 and word not in words:
            words.append(f'"{word}"')
    return words


def _split(text: str) -> list[str]:
    """Split a long section at line breaks into chunks of about ``_MAX_CHUNK``."""
    if len(text) <= _MAX_CHUNK:
        return [text]
    chunks, current = [], ""
    for line in text.splitlines():
        if current and len(current) + len(line) > _MAX_CHUNK:
            chunks.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def _url(page: str, anchor: str) -> str:
    url = WIKI_URL + quote(page.replace(" ", "_"))
    return url + ("#" + quote(anchor.replace(" ", "_")) if anchor else "")
