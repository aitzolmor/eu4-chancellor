"""The local wiki index (D-032), on a small hand-written export (no real wiki text)."""

from pathlib import Path

import pytest

from chancellor.app.cli import main
from chancellor.context.tools import TOOL_DEFINITIONS, validate
from chancellor.wiki.store import import_exports, read_exports, render_hits, search, wiki_path
from chancellor.wiki.wikitext import clean, page_sections, redirect_target

EXPORT = """<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/" version="0.11">
  <page>
    <title>Relations</title>
    <revision><text>{{Version|1.30}}
Relations describe how countries feel about each other.
== Relation modifiers ==
{{SVersion|1.24}}
=== Aggressive expansion ===
{{expand|with=distance changes}}
'''Aggressive expansion''' lowers the opinion of [[Country|countries]] near a conquest.
It decays by {{green|+2}} per year.&lt;ref&gt;Patch notes&lt;/ref&gt;
{| class="wikitable"
! Modifier !! Effect
|-
| style="color:red" | Same culture || +50%
|-
| Same religion || +50%
|}
[[File:Map.png|thumb|A [[map]] caption]]
[[Category:Diplomacy]]
</text></revision>
  </page>
  <page>
    <title>Aggressive expansion</title>
    <redirect title="Relations" />
    <revision><text>#REDIRECT [[Relations#Aggressive expansion]]</text></revision>
  </page>
  <page>
    <title>Core</title>
    <revision><text>{{Version|1.29}}
A core lets a country hold a province without penalties.
== Coring costs ==
{{Main|Overextension}}
Creating a core costs administrative power for each point of development.
</text></revision>
  </page>
</mediawiki>
"""


@pytest.fixture
def export(tmp_path: Path) -> Path:
    path = tmp_path / "export.xml"
    path.write_text(EXPORT, encoding="utf-8")
    return path


def test_clean_keeps_text_and_drops_markup():
    text = clean(
        "'''Bold''' [[Country|countries]] and [[Coalition]] {{green|+2}} {{expand|x}} "
        "[[File:A.png|thumb|cap]] [[Category:X]]"
    )
    assert text == "Bold countries and Coalition +2"


def test_tables_become_rows():
    text = clean('{| class="t"\n! A !! B\n|-\n| style="x" | 1 || 2\n|}')
    assert text.splitlines() == ["A | B", "1 | 2"]


def test_sections_carry_headings_and_versions():
    pages = read_exports([_tmp_export()])
    sections = page_sections("Relations", pages["Relations"])
    assert [(s.heading, s.version) for s in sections] == [
        ("", "1.30"),
        ("Relation modifiers > Aggressive expansion", "1.24"),
    ]
    body = sections[1].text
    assert "Aggressive expansion lowers the opinion of countries near a conquest." in body
    assert "It decays by +2 per year." in body
    assert "Same culture | +50%" in body
    assert "Patch notes" not in body and "Map.png" not in body and "expand" not in body


def test_redirects():
    assert redirect_target("#REDIRECT [[Relations#Aggressive expansion]]") == (
        "Relations#Aggressive expansion"
    )
    assert redirect_target("Some text") is None


def test_import_and_search(export, tmp_path: Path):
    database = tmp_path / "wiki.sqlite"
    report = import_exports([export], database)
    assert (report.pages, report.redirects) == (2, 1)
    hits = search("aggressive expansion", 2, database)
    assert hits[0].page == "Relations"
    assert hits[0].heading == "Relation modifiers > Aggressive expansion"
    assert hits[0].version == "1.24"
    assert hits[0].url == "https://eu4.paradoxwikis.com/Relations#Aggressive_expansion"
    # Stemming: "cores" finds the Core page.
    assert search("cores costing", 1, database)[0].page == "Core"
    assert search("!!", 1, database) == []


def test_render_hits_cites_the_source(export, tmp_path: Path):
    database = tmp_path / "wiki.sqlite"
    import_exports([export], database)
    text = render_hits("core", search("core", 1, database))
    assert "_Source: https://eu4.paradoxwikis.com/Core" in text
    assert "last checked for game version 1.29" in text
    assert "can lag behind the installed 1.37" in text
    assert render_hits("nothing", []).startswith("No wiki section matches 'nothing'")


def test_search_without_an_index(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="wiki-import"):
        search("core", 1, tmp_path / "missing.sqlite")


def test_cli_import_and_search(export, capsys):
    assert main(["wiki-import", str(export)]) == 0
    assert wiki_path().is_file()  # in the test's own state folder (conftest)
    assert "Indexed 2 pages (1 redirects" in capsys.readouterr().err
    assert main(["wiki-search", "aggressive", "expansion", "--max", "1"]) == 0
    assert "## Relations > Relation modifiers > Aggressive expansion" in capsys.readouterr().out
    assert main(["wiki-import", "missing.xml"]) == 2


def test_the_tool_is_declared_and_validated():
    names = [tool["name"] for tool in TOOL_DEFINITIONS]
    assert "search_wiki" in names
    assert validate("search_wiki", {"query": "coalition", "max_results": 2}) == {
        "query": "coalition",
        "max_results": 2,
    }


def _tmp_export() -> Path:
    import tempfile

    folder = Path(tempfile.mkdtemp())
    path = folder / "export.xml"
    path.write_text(EXPORT, encoding="utf-8")
    return path
