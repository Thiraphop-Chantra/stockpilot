"""Reproducible random streams, one per named component.

Each component (customers, demand, issues, ...) draws from its own stream derived from the run
seed and a stable checksum of the component name, so changing how many numbers one component
draws never shifts the numbers another component sees.
"""

from __future__ import annotations

import zlib

import numpy as np


def stream(seed: int, name: str) -> np.random.Generator:
    """Independent generator for component ``name`` under run ``seed``."""
    key = zlib.crc32(name.encode("utf-8"))
    return np.random.default_rng(np.random.SeedSequence(entropy=seed, spawn_key=(key,)))
