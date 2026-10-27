"""Guard rails for project-wide rules: truth isolation and English-only sources."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "src" / "stockpilot"

# Ground truth may only be touched by the generator, the path helpers and (later) scoring code.
TRUTH_PATTERN = re.compile(r"truth_dir|TRUTH_DIR|[/\"']truth\b|\btruth[/\"']")
TRUTH_ALLOWED_PREFIXES = ("synth/", "scoring/", "paths.py")
# The generator can rebuild the truth from a seed, so only the CLI and scoring may import it.
SYNTH_IMPORT = re.compile(r"^\s*(?:from|import)\s+stockpilot\.synth\b", re.MULTILINE)
SYNTH_IMPORT_ALLOWED_PREFIXES = ("synth/", "scoring/", "cli.py")

# Thai script is allowed only in the synthetic-data word list.
THAI_SCRIPT = re.compile("[\u0e00-\u0e7f]")
THAI_ALLOWED_FILES = {"src/stockpilot/synth/resources/th_words.json"}


def truth_violations(package: Path) -> list[str]:
    """Return package-relative modules outside the allowlist that reference the truth directory."""
    violations = []
    for path in sorted(package.rglob("*.py")):
        rel = path.relative_to(package).as_posix()
        text = path.read_text(encoding="utf-8")
        reads_truth = not rel.startswith(TRUTH_ALLOWED_PREFIXES) and TRUTH_PATTERN.search(text)
        imports_generator = not rel.startswith(
            SYNTH_IMPORT_ALLOWED_PREFIXES
        ) and SYNTH_IMPORT.search(text)
        if reads_truth or imports_generator:
            violations.append(rel)
    return violations


def repo_text_files(repo: Path) -> list[str]:
    """Tracked plus untracked-but-not-ignored files, as repo-relative paths."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(set(result.stdout.splitlines()))


def thai_violations(repo: Path, files: list[str]) -> list[str]:
    """Return files (outside the allowlist) whose text contains Thai script."""
    violations = []
    for rel in files:
        path = repo / rel
        if rel in THAI_ALLOWED_FILES or not path.is_file():
            continue
        data = path.read_bytes()
        if b"\x00" in data:  # binary file
            continue
        if THAI_SCRIPT.search(data.decode("utf-8", errors="ignore")):
            violations.append(rel)
    return violations


def test_truth_is_only_referenced_by_generator_and_scoring():
    assert (PACKAGE / "paths.py").is_file(), "guard must not pass on an empty package"
    assert truth_violations(PACKAGE) == []


def test_truth_guard_flags_readers_outside_the_allowlist(tmp_path):
    package = tmp_path / "stockpilot"
    (package / "synth").mkdir(parents=True)
    files = {
        "synth/export.py": "SUBDIR = 'truth'\nfrom stockpilot.synth import rng\n",
        "cli.py": "from stockpilot.synth import generate\n",
        "notes.py": '"""This module never reads the truth."""\n',
        "audit.py": "from stockpilot.paths import truth_dir\n",
        "forecast.py": 'labels = Path("data/truth") / "issues.parquet"\n',
        "optimize.py": 'path = f"{root}/truth"\n',
        "mcp.py": "from stockpilot.synth import generate\n",
        "dashboard.py": "import stockpilot.synth.config as config\n",
    }
    for name, text in files.items():
        (package / name).write_text(text, encoding="utf-8")
    expected = ["audit.py", "dashboard.py", "forecast.py", "mcp.py", "optimize.py"]
    assert truth_violations(package) == expected


@pytest.mark.skipif(not (REPO / ".git").exists(), reason="needs a git checkout")
def test_no_thai_text_outside_the_synthetic_word_list():
    files = repo_text_files(REPO)
    assert "pyproject.toml" in files, "guard must see the repository files"
    assert thai_violations(REPO, files) == []


def test_language_guard_flags_thai_text(tmp_path):
    (tmp_path / "notes.md").write_text("summary\n" + chr(0x0E01) + "\n", encoding="utf-8")
    (tmp_path / "plain.md").write_text("english only\n", encoding="utf-8")
    assert thai_violations(tmp_path, ["notes.md", "plain.md"]) == ["notes.md"]
