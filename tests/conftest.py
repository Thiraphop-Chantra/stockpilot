"""Session fixtures: generator stages built once, in memory, for the `small` preset."""

import pytest

from stockpilot.synth.calendar import build_calendar
from stockpilot.synth.config import SynthConfig
from stockpilot.synth.demand import build_rates, generate_lines
from stockpilot.synth.master import build_master
from stockpilot.synth.promotions import build_promotions


@pytest.fixture(scope="session")
def small_cfg():
    return SynthConfig.from_preset("small")


@pytest.fixture(scope="session")
def small_cal(small_cfg):
    return build_calendar(small_cfg)


@pytest.fixture(scope="session")
def small_master(small_cfg, small_cal):
    return build_master(small_cfg, small_cal)


@pytest.fixture(scope="session")
def small_promos(small_cfg, small_cal, small_master):
    return build_promotions(small_cfg, small_cal, small_master)


@pytest.fixture(scope="session")
def small_rates(small_cfg, small_cal, small_master, small_promos):
    return build_rates(small_cfg, small_cal, small_master, small_promos)


@pytest.fixture(scope="session")
def small_lines(small_cfg, small_cal, small_master, small_rates):
    return generate_lines(small_cfg, small_cal, small_master, small_rates)
