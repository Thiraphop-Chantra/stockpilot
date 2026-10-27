# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Project toolchain: uv-locked environment (one dependency version for every supported Python),
  ruff, pytest, Makefile and GitHub Actions CI (lint, tests on Python 3.11 and 3.13, and a
  reproducibility job that regenerates the dataset and checks the documented numbers).
- Working agreement (`CLAUDE.md`), roadmap of the 7 steps (`docs/ROADMAP.md`), the shared
  checklist (`TASKS.md`) and an MIT license.
- `stockpilot.patterns`: ADI/CV² demand-pattern classification (Syntetos–Boylan–Croston).
- `stockpilot.synth`: deterministic generator of a synthetic Thai distributor — master data,
  customer-level daily demand with four demand patterns, Thai holidays, promotions, lifecycle and
  a lost key account, a simulated replenishment policy with variable lead times and stockouts,
  ERP-style exports with labelled data-quality problems, and separate ground truth.
- `stockpilot synth`, `stockpilot validate` and `stockpilot docs-stats` commands; `make data`,
  `make validate-data`, `make docs-stats` and `make docs-check`.
- `docs/DATA.md` with generated statistics and data dictionary.
- Guard tests that keep ground truth out of non-scoring code and the repository English-only.
