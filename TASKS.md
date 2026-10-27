# TASKS

Checklist for the 7 roadmap steps (`docs/ROADMAP.md`). Every session ticks what it finished,
adds what it discovered, and appends one line to the session log at the bottom.
Legend: `[x]` done · `[ ]` open · `[~]` partially done (explain in the item).

## Step 1 — Foundation + synthetic data

- [x] Toolchain: pyproject (src layout), uv.lock, ruff, pytest, Makefile, `.python-version`
- [x] CI: lint + tests (Python 3.11 and 3.13) + reproducibility job (`make data`, `make docs-check`)
- [x] Governance: CLAUDE.md, docs/ROADMAP.md, TASKS.md, README.md, CHANGELOG.md, LICENSE (MIT)
- [x] `stockpilot.patterns`: ADI/CV² demand-pattern classifier
- [x] `stockpilot.synth`: config presets, seeded streams, Thai business calendar
- [x] Master data: materials, suppliers, customers, warehouses
- [x] Demand: patterns, trend, seasonality, holidays, promotions, lifecycle, structural break
- [x] Inventory simulation: purchase orders, variable lead times, stockouts, month-end stock
- [x] Data quality issues injected with complete truth labels
- [x] Parquet writer, manifest, validation, `stockpilot synth` / `stockpilot validate` CLI
- [x] Tests: determinism (incl. CPU paths), pattern mix vs target, issue counts vs truth
- [x] docs/DATA.md with generated statistics and data dictionary
- [x] `make data`, `make lint`, `make test` pass; PR into `main`

Follow-ups found in the final review (not blocking; pick up in Step 7 or when touching the code):

- [ ] Determinism test: add an AVX2-only + `OPENBLAS_CORETYPE=Haswell` variant and committed
      tiny-preset hashes that both Python CI jobs check (today CI compares only the rounded
      statistics across machines).
- [ ] Issue tests: assert that a row carrying both `truncated_material_code` and `duplicate_row`
      exists; check the extra-zero `net_value=kept/scaled` detail.
- [ ] Inventory test: bound the length of stockout runs per active series.
- [ ] CLI/Makefile polish: friendly errors for `--skus 0`, `--seed -1` and `docs-stats` without a
      manifest; `make help` prints `$(DATA_DIR)` literally; `make ci` omits the reproducibility job.

## Step 2 — Data quality audit

- [ ] `stockpilot.audit` reading `data/raw` only; `data/clean/` output
- [ ] Checks for every issue family in `docs/DATA.md` (codes, duplicates, units, outliers, dates,
      missing values, duplicate customers) and stockout-suspect flags
- [ ] `stockpilot.scoring` (precision/recall vs `data/truth/issues`)
- [ ] `make audit`; `docs/AUDIT.md` with generated numbers; thresholds in the roadmap met

## Step 3 — Forecasting tournament

- [ ] Series segmentation with `stockpilot.patterns`; censored-history handling
- [ ] Baselines, smoothing/Theta, intermittent methods, global ML model; quantile forecasts
- [ ] Rolling-origin backtest + hidden-horizon scoring via `stockpilot.scoring`
- [ ] `make forecast`; `docs/FORECAST.md` with generated numbers

## Step 4 — Inventory optimisation & simulation

- [ ] Lead-time distributions from purchase-order history
- [ ] Safety stock / reorder point / order-up-to per SKU × warehouse
- [ ] Policy simulator in THB (current vs proposed) on the hidden horizon
- [ ] `make optimize`, `make simulate`; `docs/INVENTORY.md` with generated numbers

## Step 5 — MCP agent layer

- [ ] `stockpilot.mcp` stdio server with documented tools (no truth access)
- [ ] Integration tests per tool; `make mcp`; `docs/MCP.md`

## Step 6 — Static dashboard on GitHub Pages

- [ ] Static site generator from artefacts; synthetic-data banner on every page
- [ ] Pages workflow; `make dashboard`; README link

## Step 7 — Hardening, independent review, release v1.0

- [ ] Clean-clone end-to-end run; type checks; coverage threshold
- [ ] Independent review; findings resolved or documented
- [ ] CHANGELOG complete; tag `v1.0.0`; release notes

## Open decisions

- (none)

## Session log

| Session | Date | Step | Summary | PR |
|---|---|---|---|---|
| 1 | 2026-10-27 | 1 | Toolchain, CI, governance docs, ADI/CV² classifier, synthetic data generator with labelled issues and truth, DATA.md; final review fixes (duplicate-account leak, numbered brand labels, truth guard, successors) | [#1](https://github.com/Thiraphop-Chantra/stockpilot/pull/1) |
