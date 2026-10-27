# StockPilot roadmap

StockPilot is delivered in 7 steps, one per working session. Each session starts without memory
of the previous ones, so every step must leave the repository in a state that the next session
can pick up from `CLAUDE.md`, this file and `TASKS.md` alone.

Rules that apply to every step are in `CLAUDE.md` (synthetic data only, reproducible numbers,
English only, offline, truth for scoring only, determinism). A step is **done** only when every
item of its definition of done is true, `make lint` and `make test` pass, `TASKS.md` is updated,
and the work is pushed with a PR into `main`.

| Step | Theme | Main make targets | Main outputs |
|---|---|---|---|
| 1 | Foundation + synthetic data | `data`, `test`, `lint` | `stockpilot.synth`, `data/raw`, `data/truth` |
| 2 | Data quality audit | `audit` | `stockpilot.audit`, `stockpilot.scoring`, `data/clean` |
| 3 | Forecasting tournament | `forecast` | `stockpilot.forecast`, `data/forecasts` |
| 4 | Inventory optimisation & simulation | `optimize`, `simulate` | `stockpilot.inventory`, `data/policies`, `data/simulation` |
| 5 | MCP agent layer | `mcp` | `stockpilot.mcp` server + tools |
| 6 | Static dashboard on GitHub Pages | `dashboard` | `site/` build, Pages workflow |
| 7 | Hardening, independent review, release v1.0 | `release` | tag `v1.0.0`, release notes |

---

## Step 1 — Foundation + synthetic data

**Goal.** A working toolchain, the governance documents, and a deterministic generator of a
realistic synthetic Thai distributor with ground truth for later scoring.

**Scope.** Python ≥ 3.11 package `stockpilot` (src layout) with uv, pytest, ruff, Makefile and
GitHub Actions; `CLAUDE.md`, this roadmap, `TASKS.md`; `stockpilot.synth` producing master data
(18-digit SAP-style material codes, prices, costs, units, MOQ, suppliers with variable lead
times, customers with Thai coordinates), five years of daily customer-level sales with
smooth/erratic/intermittent/lumpy demand, trend, weekly and yearly seasonality, Thai public
holidays, promotions with uplift and post-promotion dip, product launches and discontinuations,
structural breaks, and stockouts that censor sales; deliberate data quality problems; ground truth
in `data/truth/`; `docs/DATA.md`.

**Definition of done.**
- `make data` regenerates the default dataset (about 2,000 SKUs, 3 warehouses, several hundred
  customers, 5 years) into `data/` within a few minutes; scale is configurable.
- Tests prove: the generator is deterministic (also across CPU dispatch paths); the demand-pattern
  mix measured with ADI/CV² on the generated data matches the configured target; the number of
  injected issues matches the truth labels, and no unlabelled corruption exists.
- `docs/DATA.md` explains what is simulated, why it is realistic, and its limitations, with
  statistics rendered from the run manifest.
- CI runs lint, tests and a reproducibility check; `make lint` and `make test` pass.

## Step 2 — Data quality audit

**Goal.** Detect and repair the problems in `data/raw` without looking at the truth, then measure
how well that worked against the truth.

**Scope.** `stockpilot.audit` (reads `data/raw` only): schema and type checks; material-code
normalisation (restore stripped leading zeros); duplicate rows; unit mismatches (box vs piece)
via implied unit prices; quantity outliers such as extra-zero typos; future and Buddhist-era
dates (repairable from the billing-document sequence); missing prices and values; duplicate
customers across Thai/English spellings (transliteration, geography, purchase overlap); flags for
suspected stockout-censored periods (sales gaps vs receipts and month-end stock). Output a cleaned
dataset in `data/clean/` plus an audit report. `stockpilot.scoring` compares findings with
`data/truth/issues` and `data/truth/sales_clean`.

**Definition of done.**
- `make audit` reads only `data/raw`, writes `data/clean/` and a report (`docs/AUDIT.md` with
  generated numbers) in a few minutes.
- Scored against truth, per issue type: precision and recall ≥ 0.95 for truncated codes,
  duplicate rows, future dates and missing values; ≥ 0.80 for unit mismatches, extra-zero typos
  and duplicate customers; stockout-suspect flags reported with precision/recall.
- `tests/test_guards.py` still passes (audit code never touches the truth).

## Step 3 — Forecasting tournament

**Goal.** Probabilistic demand forecasts per SKU × warehouse, chosen by an honest tournament.

**Scope.** `stockpilot.forecast` on `data/clean`: segment series with `stockpilot.patterns`
(ADI/CV²); handle censored history (stockout-flagged periods); candidate models from simple
baselines (naive, seasonal naive, moving average) through exponential smoothing / Theta and
intermittent-demand methods (Croston, SBA, TSB) to a global gradient-boosting model, all
installable from PyPI and run offline; quantile or distribution forecasts. Rolling-origin
backtests on history; final scoring on the hidden horizon against true (uncensored) demand from
`data/truth` via `stockpilot.scoring` only.

**Definition of done.**
- `make forecast` produces weekly forecasts with prediction intervals for every active
  SKU × warehouse into `data/forecasts/`.
- Tournament report (`docs/FORECAST.md`, generated numbers): accuracy (MASE, WAPE, bias) and
  probabilistic quality (pinball loss, interval coverage) by demand pattern; the chosen model per
  segment beats seasonal naive on scaled pinball loss or the report explains why not.
- Hidden-horizon 80% interval coverage within ±5 percentage points of nominal overall.

## Step 4 — Inventory optimisation & simulation

**Goal.** Turn forecast uncertainty and supply variability into stocking policies and show their
effect in THB.

**Scope.** `stockpilot.inventory`: lead-time distributions estimated from purchase-order history
(not from truth); safety stock, reorder point and order-up-to levels per SKU × warehouse from
forecast distributions and lead-time variability; service targets by value class or by cost
(holding cost rate, ordering cost, lost margin); MOQ and box rounding. A simulator replays the
current policy and the proposed policy on the hidden horizon using true demand and the actual
open-PO arrivals from `data/truth` (scoring only), starting from the as-of stock.

**Definition of done.**
- `make optimize` writes policies to `data/policies/`; `make simulate` writes results to
  `data/simulation/`.
- Report (`docs/INVENTORY.md`, generated numbers): fill rate, lost sales, average inventory value,
  holding cost, ordering cost and margin in THB for current vs proposed policy, by segment and
  total; a trade-off curve of cost vs service.
- Simulator tests prove unit conservation (receipts − sales = change in stock) and correct
  lead-time handling.

## Step 5 — MCP agent layer

**Goal.** Let AI agents query StockPilot through the Model Context Protocol.

**Scope.** `stockpilot.mcp`: an MCP server over stdio that runs offline and exposes tools such as
SKU search and profile, demand history, forecast with intervals, policy recommendation, what-if
simulation for a service level, and data quality summary. It reads derived artefacts
(`data/clean`, `data/forecasts`, `data/policies`, `data/simulation`) — never `data/truth`.
Every answer states that the data is synthetic.

**Definition of done.**
- `make mcp` starts the server; `docs/MCP.md` documents every tool with input/output schema and
  an example exchange.
- Integration tests call each tool through an MCP client and check results and error handling.

## Step 6 — Static dashboard on GitHub Pages

**Goal.** A public, static view of the pipeline's results.

**Scope.** A static site (no server) generated from pipeline artefacts: data quality summary,
demand-pattern mix, forecast vs actual with intervals, policy comparison in THB, per-SKU drill
down. A "synthetic data" banner on every page. A GitHub Actions workflow builds it from a fresh
seeded run and deploys it to GitHub Pages.

**Definition of done.**
- `make dashboard` builds the site into `site/`; the Pages workflow deploys it from `main`.
- Every number on the site comes from the run artefacts of that build; the banner is present on
  every page; the README links to the deployed URL.
- Basic accessibility checks (contrast, alt text, keyboard navigation) pass.

## Step 7 — Hardening, independent review, release v1.0

**Goal.** Make the project trustworthy and release it.

**Scope.** Clean-clone reproducibility of the whole pipeline; type checking and coverage
thresholds; dependency and secret review; an independent review of code and docs by a fresh
reviewer, with every finding resolved or documented; documentation polish.

**Definition of done.**
- From a clean clone, `make install && make release` runs every step end to end and all checks
  pass; generated doc blocks are unchanged.
- Independent review findings resolved or recorded with a rationale.
- `CHANGELOG.md` complete; tag `v1.0.0` and GitHub release notes published (English).
