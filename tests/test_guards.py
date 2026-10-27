"""Guard rails for project-wide rules: truth isolation and English-only sources."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "src" / "stockpilot"

# Ground truth may only be touched by the generator, the path helpers and (later) scoring code.
TRUTH_PATTERN = re.compile(r"truth_dir|TRUTH_DIR|[\"']truth[\"']|/truth/")
TRUTH_ALLOWED_PREFIXES = ("synth/", "scoring/", "paths.py")

# Thai script is allowed only in the synthetic-data word list.
THAI_SCRIPT = re.compile("[\u0e00-\u0e7f]")
THAI_ALLOWED_FILES = {"src/stockpilot/synth/resources/th_words.json"}


def truth_violations(package: Path) -> list[str]:
    """Return package-relative modules outside the allowlist that reference the truth directory."""
    violations = []
    for path in sorted(package.rglob("*.py")):
        rel = path.relative_to(package).as_posix()
        if rel.startswith(TRUTH_ALLOWED_PREFIXES):
            continue
        if TRUTH_PATTERN.search(path.read_text(encoding="utf-8")):
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


def test_truth_guard_flags_a_reader_outside_the_allowlist(tmp_path):
    package = tmp_path / "stockpilot"
    (package / "synth").mkdir(parents=True)
    (package / "synth" / "export.py").write_text("SUBDIR = 'truth'\n", encoding="utf-8")
    (package / "audit.py").write_text("from stockpilot.paths import truth_dir\n", encoding="utf-8")
    assert truth_violations(package) == ["audit.py"]


@pytest.mark.skipif(not (REPO / ".git").exists(), reason="needs a git checkout")
def test_no_thai_text_outside_the_synthetic_word_list():
    files = repo_text_files(REPO)
    assert "pyproject.toml" in files, "guard must see the repository files"
    assert thai_violations(REPO, files) == []


def test_language_guard_flags_thai_text(tmp_path):
    (tmp_path / "notes.md").write_text("summary\n" + chr(0x0E01) + "\n", encoding="utf-8")
    (tmp_path / "plain.md").write_text("english only\n", encoding="utf-8")
    assert thai_violations(tmp_path, ["notes.md", "plain.md"]) == ["notes.md"]
