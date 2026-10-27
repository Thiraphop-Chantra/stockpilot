"""Canonical data locations."""

from pathlib import Path

from stockpilot import paths


def test_data_dirs_default_to_relative_data(monkeypatch):
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    assert paths.data_dir() == Path("data")
    assert paths.raw_dir() == Path("data/raw")
    assert paths.truth_dir() == Path("data/truth")


def test_data_dirs_follow_environment_override(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path))
    assert paths.raw_dir() == tmp_path / "raw"
    assert paths.truth_dir() == tmp_path / "truth"
