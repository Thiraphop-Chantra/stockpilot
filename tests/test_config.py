"""Generator configuration presets."""

import json
from datetime import date

import pytest

from stockpilot.synth.config import SynthConfig


def test_default_preset_covers_five_calendar_years():
    cfg = SynthConfig.from_preset("default")
    assert (cfg.n_skus, cfg.n_customers, cfg.n_suppliers) == (2000, 600, 60)
    assert cfg.start == date(2021, 1, 1)
    assert cfg.history_end == date(2025, 12, 31)
    assert cfg.extraction_date == date(2026, 1, 1)
    assert cfg.horizon_end == date(2026, 6, 30)


def test_presets_scale_down_and_accept_overrides():
    small = SynthConfig.from_preset("small")
    tiny = SynthConfig.from_preset("tiny", seed=7)
    assert (small.n_skus, small.history_years) == (240, 2)
    assert (tiny.n_skus, tiny.history_years, tiny.seed) == (60, 1, 7)
    assert small.history_end == date(2022, 12, 31)


def test_unknown_preset_is_rejected():
    with pytest.raises(ValueError, match="preset"):
        SynthConfig.from_preset("huge")


def test_pattern_mix_must_sum_to_one():
    with pytest.raises(ValueError, match="pattern_mix"):
        SynthConfig(pattern_mix=(("smooth", 0.5), ("erratic", 0.2)))


def test_config_serialises_to_json():
    payload = json.loads(json.dumps(SynthConfig.from_preset("tiny").to_dict()))
    assert payload["preset"] == "tiny"
    assert payload["start"] == "2021-01-01"
    assert payload["pattern_mix"]["lumpy"] == 0.20
