from pathlib import Path

import pytest

from chancellor.context.campaign import Campaign
from chancellor.context.status import campaign_status
from chancellor.game.localisation import Localisation
from chancellor.save.parser import parse_lazy

SAVE = """
great_powers={
    original={ rank=1 country="FRA" value=700.0 }
    original={ rank=4 country="HAB" value=456.0 }
}
countries={
    HAB={ owned_provinces={ 1 } treasury=48.892 manpower=64.351 max_manpower=83.576
          stability=1.000 prestige=87.919 legitimacy=100.000 raw_development=191.000
          powers={ 450 79 425 }
          ledger={ lastmonthincome=27.961 lastmonthexpense=27.894 }
          loan={ amount=88.000 } loan={ amount=88.000 }
          army={ regiment={ } regiment={ } }
          navy={ ship={ } army={ regiment={ } } } }
    VEN={ owned_provinces={ 2 } }
}
active_war={ name="Guerra veneciana" attackers={ VEN } defenders={ HAB } }
"""


@pytest.fixture
def campaign() -> Campaign:
    meta = {"player": "HAB", "date": "1475.6.21"}
    return Campaign(meta, parse_lazy(SAVE), Localisation({"HAB": "Austria"}))


def test_campaign_status(campaign: Campaign):
    status = campaign_status(campaign, Path("saves/Austria1475_06_21.eu4"))
    assert (status.tag, status.name, status.date) == ("HAB", "Austria", "1475.6.21")
    assert status.save_name == "Austria1475_06_21.eu4"
    assert (status.treasury, status.income, status.expenses) == (48.892, 27.961, 27.894)
    assert status.loans == 2
    assert (status.manpower, status.max_manpower) == (64351.0, 83576.0)  # thousands → men
    assert status.regiments == 3  # including the army at sea
    assert status.monarch_power == (450, 79, 425)
    assert status.great_power_rank == 4
    assert status.wars == ["Guerra veneciana"]


def test_missing_values_stay_empty(campaign: Campaign):
    status = campaign_status(campaign, tag="VEN")
    assert status.save_name is None
    assert status.treasury is None and status.monarch_power is None
    assert status.great_power_rank is None
    assert status.to_dict()["wars"] == ["Guerra veneciana"]


def test_unknown_country_raises(campaign: Campaign):
    with pytest.raises(KeyError):
        campaign_status(campaign, tag="XXX")
