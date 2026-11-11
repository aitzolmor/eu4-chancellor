import pytest

from chancellor.save.parser import parse


@pytest.mark.skip(reason="Parser not implemented yet (Phase 1).")
def test_parse_simple_pairs():
    assert parse('player="CAS"\ndate=1525.6.30') == {"player": "CAS", "date": "1525.6.30"}


@pytest.mark.skip(reason="Parser not implemented yet (Phase 1).")
def test_parse_repeated_keys_are_kept():
    result = parse("active_war={ name=a }\nactive_war={ name=b }")
    assert [w["name"] for w in result["active_war"]] == ["a", "b"]
