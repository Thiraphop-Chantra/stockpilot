"""Seeded random streams: one independent, reproducible stream per named component."""

from stockpilot.synth.rng import stream


def test_same_seed_and_name_reproduce_the_same_draws():
    assert (stream(42, "demand").random(5) == stream(42, "demand").random(5)).all()


def test_other_name_or_seed_gives_a_different_stream():
    base = stream(42, "demand").random(5)
    assert not (base == stream(42, "customers").random(5)).any()
    assert not (base == stream(43, "demand").random(5)).any()
