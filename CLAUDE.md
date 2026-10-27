# CLAUDE.md — StockPilot working agreement

Read this file, `docs/ROADMAP.md` and `TASKS.md` before doing anything else in a session.
Sessions start with no memory of earlier sessions: the repository is the only hand-over.

## What StockPilot is

An open-source pipeline that takes a distribution company's raw data all the way to
replenishment decisions:

```
synthetic ERP exports ─► data quality audit ─► demand forecasts with uncertainty
    ─► safety stock / reorder points ─► outcomes simulated in Thai baht (THB)
    ─► MCP server for AI agents ─► static dashboard on GitHub Pages
```

It is built and demonstrated **only on synthetic data** from `stockpilot.synth`, which simulates
a fictional mid-sized Thai distributor. The work is split into 7 steps, one per session
(`docs/ROADMAP.md`); progress is tracked in `TASKS.md`.

## Hard constraints (every step, no exceptions)

1. **Synthetic data only.** Never use or reference any real company's data, names or figures.
   Names are composed at random from generic words or syllables. Do not add lists of real names,
   not even as a blocklist. Everything that shows data (README, docs, dashboard, MCP answers) says
   the data is synthetic; every Parquet file carries the schema metadata `stockpilot.synthetic=true`.
2. **Every result number is reproducible.** Numbers in README, docs and the dashboard come from a
   real run that the same seed reproduces. They live only inside generated blocks
   (`<!-- generated:NAME:start -->` … `<!-- generated:NAME:end -->`) rendered from run artefacts
   such as `data/manifest.json`; never type them by hand. Configured inputs (targets, rates) are
   labelled as configuration, not results. CI regenerates the data and fails if a block drifts.
3. **English only on GitHub.** Code, comments, docs, this file, `TASKS.md`, commit messages,
   branch names, PR titles and descriptions, CHANGELOG, tags, release notes and dashboard text are
   English. The only exception is synthetic data that deliberately contains Thai names for
   Thai/English matching tests; that Thai text lives only in
   `src/stockpilot/synth/resources/th_words.json` (enforced by `tests/test_guards.py`).
   Tool-call gotcha: unicode escape sequences typed into tool inputs are decoded into real
   characters, so write escapes with a doubled backslash when a file must keep them as text.
4. **Offline.** The shell reaches only the package registry (PyPI) and GitHub. Package code never
   uses the network at runtime; only `uv sync` / `uv lock` download packages.
5. **Ground truth is for scoring only.** `data/truth/` may be read by `stockpilot.synth` and by
   scoring code (`stockpilot.scoring`, from Step 2) — never by audit, forecasting, optimisation,
   MCP or dashboard code. `tests/test_guards.py` enforces this.
6. **Deterministic.** Every random draw comes from `stockpilot.synth.rng.stream(seed, name)`;
   default seed 42. Same seed ⇒ byte-identical Parquet files across runs, Python 3.11–3.13 and
   CPU instruction sets (see *Determinism rules*).

## Commands

| Command | What it does |
|---|---|
| `make install` | Create `.venv` from `uv.lock` (runtime + dev tools) |
| `make test` | Run pytest (tests build their own small datasets in temp dirs) |
| `make lint` | `ruff check` + `ruff format --check` |
| `make format` | Apply ruff formatting and safe fixes |
| `make ci` | Lint + test, as CI does |
| `make help` | List every target, including placeholders for later steps |

Steps add their own targets (`make data`, `make audit`, `make forecast`, …); a target that a later
step will implement prints "not implemented yet" and exits 1. Use `uv run --locked <cmd>` for
anything else. After changing dependencies run `uv lock` and commit `uv.lock`.

## Data contract

- `data/` is gitignored and fully regenerable. **Regenerating it is not "deleting data".**
- `data/raw/` — what the synthetic company's ERP exports contain, including deliberate data
  quality problems. The only input for audit, forecasting and optimisation.
- `data/truth/` — ground truth: true demand before stockout censoring, labels for every injected
  issue, hidden-horizon demand, event logs. Scoring only (constraint 5).
- `data/manifest.json` — deterministic description of a run (seed, config, row counts, hashes,
  measured statistics); the source for generated doc blocks. `data/run_info.json` holds
  environment details and timings and is never compared.
- Later steps write derived artefacts to new directories under `data/` (e.g. `data/clean/`,
  `data/forecasts/`) and document them in `docs/DATA.md` or their own doc.

## Working rules

- Keep working on your own whenever the next step does not need the owner.
- Stop and ask only when genuinely blocked, or before: force-pushing, deleting anything that
  cannot be regenerated, or changing anything outside this repository.
- Follow the roadmap step you are on; if a later step needs an earlier decision revisited, record
  it in `TASKS.md` (Open decisions) instead of silently diverging.
- Prefer small, test-first changes; every new behaviour gets a test that failed before the change.
- Work on a branch; commit with conventional-commit messages (`feat:`, `fix:`, `docs:`, `chore:`,
  `ci:`, `test:`); open a PR into `main` at the end of the step.

## Session protocol

1. **Start:** read this file, `docs/ROADMAP.md`, `TASKS.md`; run `make install` and `make test`.
2. **Work:** tick `TASKS.md` items as they are finished; keep docs in sync with behaviour.
3. **Finish:** `make lint` and `make test` green (plus the step's own targets); `TASKS.md`
   updated (checklist and session log); commit and push; open the PR.
4. **Final message to the owner:** written **in Thai**, with exactly three headings meaning
   (a) "waiting on the owner" — decisions or actions only the owner can take,
   (b) "what changed" — what this session delivered, and
   (c) "findings / could not verify" — surprises, risks and anything not verified.

## Determinism rules

- No stdlib `random`, no `datetime.now()/today()`, no legacy `np.random.*` (ruff enforces this).
- Sort with `kind="stable"` (or `np.lexsort` / multi-key sorts): numpy's default sort orders ties
  differently on AVX-512, AVX2 and baseline CPUs.
- Round floats when they are created (THB to 2 decimals, coordinates to 6, parameters to 9):
  `np.exp/log/power` differ in the last bit between CPU paths.
- Never depend on `set`/`dict` iteration order of strings or on `hash()`.
- One version of each dependency is locked for every Python (`[tool.uv] fork-strategy = "fewest"`).
- `tests/test_determinism.py` re-runs the generator with other CPU dispatch paths and hash seeds.

## pandas 3 / Parquet gotchas

- Copy-on-write: `Series.to_numpy()` can be read-only — use `to_numpy(copy=True)` before editing;
  no chained assignment.
- `posting_date` and other dates are Parquet `date32`. Buddhist-era typos (year + 543, e.g. 2568)
  overflow `datetime64[ns]`; convert with an explicit unit (`"s"`/`"us"`) or keep `datetime.date`.
- Material codes are 18-character strings with leading zeros — never cast them to numbers.

## Repository map

```
src/stockpilot/          package (src layout)
  cli.py                 `stockpilot` command line
  paths.py               data/raw and data/truth locations
  synth/                 synthetic data generator (Step 1)
tests/                   pytest suite (never reads ./data)
docs/ROADMAP.md          the 7 steps and their definition of done
docs/DATA.md             what the synthetic data simulates, schemas, limitations
TASKS.md                 checklist + session log, updated every session
```
