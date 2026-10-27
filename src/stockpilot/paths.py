"""Canonical locations of the generated data.

``data/raw`` holds what the synthetic company's ERP exports would contain and is the only input
for audit, forecasting and optimisation code. ``data/truth`` holds the generator's ground truth;
only ``stockpilot.synth`` and scoring code may read it.
"""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR_ENV = "STOCKPILOT_DATA_DIR"


def data_dir() -> Path:
    """Root data directory: ``$STOCKPILOT_DATA_DIR`` if set, else ``data`` (relative to cwd)."""
    return Path(os.environ.get(DATA_DIR_ENV, "data"))


def raw_dir() -> Path:
    """Observable ERP-style exports."""
    return data_dir() / "raw"


def truth_dir() -> Path:
    """Ground truth for scoring only."""
    return data_dir() / "truth"
