import pytest

from chancellor.save.parser import LazyBlock, Repeated, get_all, parse, parse_lazy

# --- scalars ---------------------------------------------------------------------------


def test_simple_pairs():
    assert parse('player="CAS"\ndate=1525.6.30') == {"player": "CAS", "date": "1525.6.30"}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("42", 42),
        ("-3", -3),
        ("187.317", 187.317),
        ("-0.500", -0.5),
        ("yes", True),
        ("no", False),
        ("1444.11.11", "1444.11.11"),
        ("HAB", "HAB"),
        ('"123"', "123"),
        ('"yes"', "yes"),
        ('""', ""),
    ],
)
def test_scalar_conversion(source, expected):
    value = parse(f"key={source}")["key"]
    assert value == expected
    assert type(value) is type(expected)


def test_escaped_quotes():
    assert parse(r'name="The \"Great\""')["name"] == 'The "Great"'


def test_non_ascii_strings():
    assert parse('name="Náinnas Yugra"')["name"] == "Náinnas Yugra"


# --- blocks ----------------------------------------------------------------------------


def test_nested_blocks():
    result = parse('country={ treasury=10.5 ruler={ name="Juan" adm=3 } }')
    assert result == {"country": {"treasury": 10.5, "ruler": {"name": "Juan", "adm": 3}}}


def test_bare_value_list():
    assert parse("institutions={ 0 1 0 }")["institutions"] == [0, 1, 0]


def test_quoted_value_list():
    assert parse('players_countries={ "Player" "HAB" }')["players_countries"] == ["Player", "HAB"]


def test_list_of_blocks():
    result = parse("goals={ { id=1 } { id=2 } }")
    assert result["goals"] == [{"id": 1}, {"id": 2}]


def test_empty_block_is_empty_dict():
    assert parse("flags={ }")["flags"] == {}


def test_numeric_and_date_keys():
    result = parse("provinces={ -1={ owner=CAS } 1444.11.11={ x=1 } }")
    assert result["provinces"] == {"-1": {"owner": "CAS"}, "1444.11.11": {"x": 1}}


def test_mixed_block_stores_bare_values_under_empty_key():
    assert parse("b={ a=1 7 }")["b"] == {"a": 1, "": 7}


def test_key_without_equals_before_block():
    result = parse("map_area_data{\nbrittany_area={ state=1 }\n}")
    assert result == {"map_area_data": {"brittany_area": {"state": 1}}}


def test_indentation_is_ignored():
    assert parse("a={\nb={\n\t\t\tc=1\n}\n}") == {"a": {"b": {"c": 1}}}


# --- repeated keys ---------------------------------------------------------------------


def test_repeated_keys_are_kept():
    result = parse("active_war={ name=a }\nactive_war={ name=b }")
    assert isinstance(result["active_war"], Repeated)
    assert [w["name"] for w in result["active_war"]] == ["a", "b"]


def test_repeated_key_differs_from_list_value():
    assert not isinstance(parse("x={ 1 2 }")["x"], Repeated)
    assert isinstance(parse("x=1 x=2")["x"], Repeated)


def test_get_all():
    block = parse("a=1 b=2 b=3")
    assert get_all(block, "a") == [1]
    assert get_all(block, "b") == [2, 3]
    assert get_all(block, "missing") == []


# --- other syntax ----------------------------------------------------------------------


def test_comments_are_ignored():
    assert parse('# header\na=1 # trailing\nb="x # not a comment"') == {
        "a": 1,
        "b": "x # not a comment",
    }


@pytest.mark.parametrize("op", ["<", ">", "<=", ">=", "!=", "?="])
def test_comparison_operators_act_as_assignment(op):
    assert parse(f"value {op} 5") == {"value": 5}


def test_stray_closing_brace_is_ignored():
    assert parse("a=1 } b=2") == {"a": 1, "b": 2}


def test_unterminated_block_is_closed():
    assert parse("a={ b=1") == {"a": {"b": 1}}


def test_key_with_missing_value():
    assert parse("a={ b= }") == {"a": {"b": ""}}


def test_header_less_bare_document():
    assert parse("1 2 3") == {"": [1, 2, 3]}


# --- lazy parsing ----------------------------------------------------------------------

DOC = """
date=1525.6.30
countries={
\tCAS={ treasury=187.317 ruler={ name="Juan" } }
\tPOR={ treasury=50.0 }
}
active_war={ name="a" }
active_war={ name="b" }
map_area_data{
brittany_area={ x=1 }
}
"""


def test_lazy_top_level_keeps_scalars_and_defers_blocks():
    doc = parse_lazy(DOC)
    assert doc["date"] == "1525.6.30"
    assert isinstance(doc["countries"], LazyBlock)
    assert isinstance(doc["map_area_data"], LazyBlock)


def test_lazy_block_parse_matches_full_parse():
    full = parse(DOC)
    lazy = parse_lazy(DOC)
    assert lazy["countries"].parse() == full["countries"]
    assert lazy["map_area_data"].parse() == full["map_area_data"]


def test_lazy_nested_levels():
    countries = parse_lazy(DOC)["countries"].lazy()
    assert set(countries) == {"CAS", "POR"}
    cas = countries["CAS"].lazy()
    assert cas["treasury"] == 187.317
    assert cas["ruler"].parse() == {"name": "Juan"}


def test_lazy_repeated_blocks():
    wars = get_all(parse_lazy(DOC), "active_war")
    assert [w.parse()["name"] for w in wars] == ["a", "b"]


def test_lazy_ignores_braces_in_strings_and_comments():
    doc = parse_lazy('a={ name="{ not a block }" } # { nor this\nb=2')
    assert doc["a"].parse() == {"name": "{ not a block }"}
    assert doc["b"] == 2


def test_lazy_list_of_blocks():
    goals = parse_lazy("goals={ { id=1 } { id=2 } }")["goals"].lazy()
    assert [g.parse() for g in goals] == [{"id": 1}, {"id": 2}]


def test_lazy_value_list():
    assert parse_lazy("x={ 1 2 3 }")["x"].parse() == [1, 2, 3]


def test_lazy_reuses_child_spans_from_the_first_scan(monkeypatch):
    from chancellor.save import parser

    doc = parse_lazy('countries={ A={ x=1 } B={ name="{ tricky }" y={ 2 } } }')
    calls = []
    original = parser._scan_two_levels
    monkeypatch.setattr(
        parser, "_scan_two_levels", lambda *args: calls.append(args) or original(*args)
    )
    countries = doc["countries"].lazy()  # spans already known: no new scan
    assert calls == []
    assert countries["A"].parse() == {"x": 1}
    assert countries["B"].parse() == {"name": "{ tricky }", "y": [2]}
    countries["B"].lazy()  # third level was not recorded: scanned now
    assert len(calls) == 1


def test_lazy_unterminated_inner_block():
    countries = parse_lazy("countries={ A={ x=1 ")["countries"].lazy()
    assert countries["A"].parse() == {"x": 1}
