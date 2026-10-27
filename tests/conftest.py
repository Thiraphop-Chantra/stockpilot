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


@pytest.fixture(scope="session")
def small_inventory(small_cfg, small_cal, small_master, small_lines, small_promos):
    from stockpilot.synth.inventory import simulate

    return simulate(small_cfg, small_cal, small_master, small_lines, small_promos.planning)


@pytest.fixture(scope="session")
def small_sales(small_cfg, small_cal, small_master, small_lines, small_inventory, small_promos):
    from stockpilot.synth.sales import build_sales_clean

    return build_sales_clean(
        small_cfg, small_cal, small_master, small_lines, small_inventory, small_promos
    )


@pytest.fixture(scope="session")
def small_injected(small_cfg, small_cal, small_master, small_sales):
    from stockpilot.synth.issues import inject

    return inject(small_cfg, small_cal, small_master, small_sales)


@pytest.fixture(scope="session")
def tiny_injected():
    from stockpilot.synth.inventory import simulate
    from stockpilot.synth.issues import inject
    from stockpilot.synth.sales import build_sales_clean

    cfg = SynthConfig.from_preset("tiny")
    cal = build_calendar(cfg)
    master = build_master(cfg, cal)
    promos = build_promotions(cfg, cal, master)
    lines = generate_lines(cfg, cal, master, build_rates(cfg, cal, master, promos))
    inv = simulate(cfg, cal, master, lines, promos.planning)
    return inject(cfg, cal, master, build_sales_clean(cfg, cal, master, lines, inv, promos))
