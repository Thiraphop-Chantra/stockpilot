# TASKS

Checklist for the 7 roadmap steps (`docs/ROADMAP.md`). Every session ticks what it finished,
adds what it discovered, and appends one line to the session log at the bottom.
Legend: `[x]` done · `[ ]` open · `[~]` partially done (explain in the item).

## Step 1 — Foundation + synthetic data

- [ ] Toolchain: pyproject (src layout), uv.lock, ruff, pytest, Makefile, `.python-version`
- [ ] CI: lint + tests (Python 3.11 and 3.13) + reproducibility job
- [ ] Governance: CLAUDE.md, docs/ROADMAP.md, TASKS.md, README.md, CHANGELOG.md, LICENSE (MIT)
- [ ] `stockpilot.patterns`: ADI/CV² demand-pattern classifier
- [ ] `stockpilot.synth`: config presets, seeded streams, Thai business calendar
- [ ] Master data: materials, suppliers, customers, warehouses
- [ ] Demand: patterns, trend, seasonality, holidays, promotions, lifecycle, structural break
- [ ] Inventory simulation: purchase orders, variable lead times, stockouts, month-end stock
- [ ] Data quality issues injected with complete truth labels
- [ ] Parquet writer, manifest, validation, `stockpilot synth` / `stockpilot validate` CLI
- [ ] Tests: determinism (incl. CPU paths), pattern mix vs target, issue counts vs truth
- [ ] docs/DATA.md with generated statistics and data dictionary
- [ ] `make data`, `make lint`, `make test` pass; PR into `main`

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
