"""The generator is a pure function of its configuration and seed."""

import json
import os
import subprocess
import sys

import pytest

from stockpilot.synth import generate, write
from stockpilot.synth.config import SynthConfig

WRITE_TINY = (
    "import sys; from stockpilot.synth import generate, write; "
    "from stockpilot.synth.config import SynthConfig; "
    "write(generate(SynthConfig.from_preset('tiny')), sys.argv[1])"
)
ENABLED_DISPATCH = (
    "from numpy._core._multiarray_umath import __cpu_dispatch__, __cpu_features__; "
    "print(' '.join(f for f in __cpu_dispatch__ if __cpu_features__.get(f)))"
)


def table_hashes(manifest: dict) -> dict:
    return {name: entry["sha256"] for name, entry in manifest["tables"].items()}


@pytest.fixture(scope="module")
def tiny_manifest(tmp_path_factory):
    return write(generate(SynthConfig.from_preset("tiny")), tmp_path_factory.mktemp("tiny-a"))


def test_same_seed_gives_byte_identical_files(tmp_path, tiny_manifest):
    again = write(generate(SynthConfig.from_preset("tiny")), tmp_path)
    assert again == tiny_manifest
    on_disk = json.loads((tmp_path / "manifest.json").read_text())
    assert on_disk == tiny_manifest


def test_another_seed_gives_different_data(tmp_path, tiny_manifest):
    other = write(generate(SynthConfig.from_preset("tiny", seed=43)), tmp_path)
    assert other["tables"]["raw/sales"]["sha256"] != tiny_manifest["tables"]["raw/sales"]["sha256"]


def test_other_cpu_dispatch_path_and_hash_seed_give_identical_files(tmp_path, tiny_manifest):
    features = subprocess.run(
        [sys.executable, "-c", ENABLED_DISPATCH], capture_output=True, text=True, check=True
    ).stdout.split()
    if not features:
        pytest.skip("this CPU runs numpy's baseline code path only")
    env = dict(os.environ, NPY_DISABLE_CPU_FEATURES=" ".join(features), PYTHONHASHSEED="12345")
    subprocess.run([sys.executable, "-c", WRITE_TINY, str(tmp_path)], env=env, check=True)
    other = json.loads((tmp_path / "manifest.json").read_text())
    assert table_hashes(other) == table_hashes(tiny_manifest)
    assert other["stats"] == tiny_manifest["stats"]
