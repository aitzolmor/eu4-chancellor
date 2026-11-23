from pathlib import Path

from chancellor.game.localisation import (
    DEFAULT_LANGUAGE,
    Localisation,
    detect_language,
    parse_defined_texts,
    parse_localisation,
)


def test_parse_localisation_lines():
    text = 'l_spanish:\n CAS:0 "Castilla"\n PROV219:0 "Toledo" # comment\n # just a comment\n'
    assert parse_localisation(text) == {"CAS": "Castilla", "PROV219": "Toledo"}


def test_inner_quotes_are_kept():
    assert parse_localisation(' KEY:0 "Say "hi""')["KEY"] == 'Say "hi"'


def test_load_reads_only_selected_language_and_bom(tmp_path: Path):
    folder = tmp_path / "localisation"
    (folder / "replace").mkdir(parents=True)
    (folder / "countries_l_spanish.yml").write_text(
        'l_spanish:\n CAS:0 "Castilla"\n', encoding="utf-8-sig"
    )
    (folder / "countries_l_english.yml").write_text(
        'l_english:\n CAS:0 "Castile"\n', encoding="utf-8-sig"
    )
    (folder / "replace" / "z_l_spanish.yml").write_text(
        'l_spanish:\n PROV219:0 "Toledo"\n', encoding="utf-8-sig"
    )

    loc = Localisation.load(tmp_path, "spanish")

    assert loc.country("CAS") == "Castilla"
    assert loc.province(-219) == "Toledo"
    assert len(loc) == 2


def test_fallbacks():
    loc = Localisation()
    assert loc.country("XYZ") == "XYZ"
    assert loc.province(5) == "Province 5"
    assert loc.get("some_key") == "some_key"
    assert loc.get("some_key", "default") == "default"


def test_load_missing_folder_is_empty(tmp_path: Path):
    assert len(Localisation.load(tmp_path, "spanish")) == 0


def test_detect_language(tmp_path: Path):
    (tmp_path / "settings.txt").write_text('language="l_spanish"\nx=1\n', encoding="utf-8")
    assert detect_language(tmp_path) == "spanish"


def test_detect_language_default(tmp_path: Path):
    assert detect_language(tmp_path) == DEFAULT_LANGUAGE


DEFINED = """
defined_text = {
    name = GetUnionTitle
    text = { localisation_key = union_title trigger = { always = yes } }
}
defined_text = {
    name = GetDynastyTitle
    text = { localisation_key = dynasty_title trigger = { government = monarchy } }
    text = { localisation_key = no_dynasty_title trigger = { NOT = { government = monarchy } } }
}
"""


def test_parse_defined_texts():
    texts = parse_defined_texts(DEFINED)
    assert texts["GetUnionTitle"] == [("union_title", {"always": True})]
    assert [key for key, _ in texts["GetDynastyTitle"]] == ["dynasty_title", "no_dynasty_title"]


def test_load_reads_defined_texts(tmp_path: Path):
    folder = tmp_path / "customizable_localization"
    folder.mkdir()
    (folder / "00_custom.txt").write_bytes(DEFINED.encode("cp1252"))
    assert set(Localisation.parse_game(tmp_path).defined_texts) == {
        "GetUnionTitle",
        "GetDynastyTitle",
    }
