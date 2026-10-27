"""Generated documentation blocks: rendering, in-place sync and drift detection."""

import json

import pytest

from stockpilot.cli import main
from stockpilot.synth import generate, write
from stockpilot.synth.config import SynthConfig
from stockpilot.synth.report import render_dictionary, render_stats, sync_block

DOC = """# Title

Hand-written intro.

<!-- generated:data-stats:start -->
stale
<!-- generated:data-stats:end -->

Hand-written outro.
"""


@pytest.fixture(scope="module")
def tiny_dataset(tmp_path_factory):
    out = tmp_path_factory.mktemp("tiny-docs")
    return out, write(generate(SynthConfig.from_preset("tiny")), out)


def test_stats_render_the_manifest_numbers(tiny_dataset):
    _, manifest = tiny_dataset
    text = render_stats(manifest)
    volume = manifest["stats"]["volume"]
    assert f"{volume['sales_rows_raw']:,}" in text
    fill = manifest["stats"]["service"]["fill_rate"]
    assert f"{fill * 100:.1f}%" in text
    assert "synthetic" in text.lower()
    assert render_stats(manifest) == text


def test_dictionary_lists_every_table_and_column():
    text = render_dictionary()
    assert "raw/sales" in text and "truth/issues" in text
    assert "| `posting_date` | date32 |" in text


def test_sync_replaces_only_the_generated_block(tmp_path):
    doc = tmp_path / "DOC.md"
    doc.write_text(DOC, encoding="utf-8")
    assert sync_block(doc, "data-stats", "fresh numbers", check=False) is True
    text = doc.read_text(encoding="utf-8")
    assert "fresh numbers" in text and "stale" not in text
    assert text.startswith("# Title\n\nHand-written intro.") and text.endswith("outro.\n")
    assert sync_block(doc, "data-stats", "fresh numbers", check=False) is False


def test_check_mode_reports_drift_without_writing(tmp_path):
    doc = tmp_path / "DOC.md"
    doc.write_text(DOC, encoding="utf-8")
    assert sync_block(doc, "data-stats", "fresh numbers", check=True) is True
    assert doc.read_text(encoding="utf-8") == DOC


def test_missing_markers_are_an_error(tmp_path):
    doc = tmp_path / "DOC.md"
    doc.write_text("# no markers\n", encoding="utf-8")
    with pytest.raises(ValueError, match="data-stats"):
        sync_block(doc, "data-stats", "x", check=False)


def test_docs_stats_cli_fixes_then_passes_the_check(tmp_path, tiny_dataset):
    data, _ = tiny_dataset
    doc = tmp_path / "DATA.md"
    doc.write_text(
        DOC
        + "\n<!-- generated:data-dictionary:start -->\n<!-- generated:data-dictionary:end -->\n",
        encoding="utf-8",
    )
    args = ["docs-stats", "--data", str(data), "--docs", str(doc)]
    assert main([*args, "--check"]) == 1
    assert main(args) == 0
    assert main([*args, "--check"]) == 0
    manifest = json.loads((data / "manifest.json").read_text())
    assert f"{manifest['stats']['volume']['sales_rows_raw']:,}" in doc.read_text(encoding="utf-8")
