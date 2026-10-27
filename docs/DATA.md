# Synthetic data

> **Everything in this dataset is synthetic.** It is produced by `stockpilot.synth` for a
> fictional company. No real company's data, names or figures are used or referenced. Customer
> names are composed at random from generic Thai words (any resemblance to a real business is
> coincidental); brands and suppliers are numbered labels such as "Brand 017" and
> "Supplier 031 Co., Ltd." so they can never coincide with a real company. Every Parquet file
> carries the schema metadata `stockpilot.synthetic=true`, and `data/manifest.json` says so too.

`make data` writes the dataset to `data/` (gitignored, regenerated within a few minutes):

- `data/raw/` — what the company's ERP exports would contain, **including deliberate data
  quality problems**. This is the only input for auditing, forecasting and optimisation.
- `data/truth/` — ground truth for **scoring only** (see [Ground truth](#ground-truth-and-how-to-use-it)).
- `data/manifest.json` — seed, configuration, row counts, SHA-256 of every file and the measured
  statistics below; `data/run_info.json` — environment and timing (never compared).

All numbers in this document's prose are **configuration** (targets, rates and parameter
ranges). Measured results appear only in the generated blocks, rendered from the manifest of a
real run; CI regenerates the data and fails if a block drifts.

## The fictional company

A mid-sized Thai distributor of consumer and household goods. Configured size of the `default`
preset: 2,000 SKUs, 600 customers, 60 suppliers and 3 distribution centres (plants), five years
of daily history from 2021-01-01 to 2025-12-31. The ERP exports were pulled on 2026-01-01; true
demand continues for a hidden horizon to 2026-06-30 that exists only in the truth. The `small`
(240 SKUs, 2 years) and `tiny` (60 SKUs, 1 year) presets exist for tests and experiments.

| Plant | Distribution centre | Serves |
|---|---|---|
| 1100 | Central DC (Bang Phli, Samut Prakan) | Bangkok, the Central, East and West regions and the North |
| 1200 | Northeast DC (Khon Kaen) | the Northeast |
| 1300 | South DC (Hat Yai, Songkhla) | the South |

Nine generic categories: beverages, snacks & confectionery, dry groceries, personal care, home
care, stationery & office, small appliances, hardware & tools, gifts & seasonal. Each has its own
yearly profile (for example a hot-season peak for beverages, a February–April peak for fans, a
back-to-school peak for stationery, a December peak for gift baskets) and product types with
plausible price bands and pack sizes.

Customers are modern-trade chains (MT), wholesalers, retailers, hotels/restaurants (HORECA) and
institutions, drawn from a configured list of 32 provinces, placed near the provincial capital and
served by the plant of their region. Account numbers are sparse random numbers, as after a system
migration, so neither creation order nor duplicate accounts can be read from them. Key accounts (MT and wholesale, a fifth of the customers) carry most of the volume.

## How the data is generated

### Calendar

The company works Monday to Saturday (Saturday is a half day) and closes on Sundays and on Thai
public holidays from the [`holidays`](https://pypi.org/project/holidays/) package (`TH`), which
computes the lunar holidays offline. Customers order more on the two working days before a block
of closed days and on the first day after it; beverages, snacks and gifts also get a
pre-Songkran surge.

### Demand: customer order lines

True demand is a set of order lines (customer, SKU, day, quantity). The expected number of lines
of a SKU on a day is

```
weekly base rate / 7  x  weekday factor x holiday effect      (closed days = 0)
                      x  category season ^ kappa               (normalised to mean 1)
                      x  exp(trend x years)                    (centred on the history)
                      x  promotion uplift / post-promotion dip
                      x  pre-Songkran surge                     (festive categories)
                      x  lifecycle factor                       (ramp-up, decline, zero outside)
                      x  share of the SKU's customer base still active
                      x  weekly gamma intensity                 (erratic SKUs only)
```

The number of lines is Poisson; each line's customer is drawn from the SKU's customer base
(weighted by customer size, among customers active that day) and its size is lognormal, in
boxes or pieces. Each SKU is assigned a demand pattern with these configured parameters:

| Pattern | Configured share of SKUs | Order lines per week | Line-size lognormal sigma | Extra |
|---|---:|---|---|---|
| smooth | 35% | log-uniform 8–40 | 0.25–0.50 | |
| erratic | 15% | log-uniform 8–30 | 0.50–0.80 | bursty weekly gamma intensity (shape 1.0–1.6) |
| intermittent | 30% | uniform 0.06–0.50 | 0.05–0.30 | one order unit per SKU |
| lumpy | 20% | uniform 0.06–0.50 | 0.95–1.30 | |

The pattern is **measured** like an analyst would: weekly totals over all plants, full ISO weeks
inside the SKU's active window (from the launch and discontinued dates in the material master),
ADI = weeks / weeks with demand, CV² = squared coefficient of variation of the non-zero weeks,
with the Syntetos–Boylan–Croston cut-offs ADI 1.32 and CV² 0.49 (`stockpilot.patterns`). SKUs
need at least 26 weeks and 4 non-zero weeks to be classified.

### Promotions

About 70% of fast-moving consumables take part in trade promotions (a configured rate of 2.5 a
year): 7–28 days at 5–30% off, lifting demand by `(1 - discount) ^ -elasticity` (capped at 3.5x)
and followed by a dip of up to 14 days as customers use up forward-bought stock. The promotion
calendar is observable — including the promotions already planned for the hidden horizon — while
the true uplift and dip are truth.

### Lifecycle and structural breaks

A configured 12% of SKUs (fast movers) launch during the history with a ramp-up; 8% are
discontinued after a decline. With a configured probability of one half, a discontinued SKU is
replaced by a successor of the same category and demand pattern — whenever such a launch can be
placed just before the discontinuation — so only some discontinued fast movers get one (the
realised count is in the statistics below). A successor is the next version of the same product
line (`… V2`, naming its predecessor in the master data): same pack, supplier, customer base and
demand parameters, but its demand is drawn afresh rather than copied from the predecessor. About 10% of customers are acquired and 6% stop buying during the
history, and one key account is lost for good — a structural break for every SKU it bought.

### Replenishment, stockouts and lead times

Stockouts are not painted on; they emerge from simulating the company's own (naive) policy for
every SKU and plant. On each supplier's order day (domestic weekly, imports every 2 or 4 weeks;
a review that falls on a closed day moves to the next working day) the planner orders up to

```
S = max(MOQ, avg x promo factor x (lead + review) + z x sd x sqrt(lead + review))
```

with `avg` and `sd` from the last 91 days of **sales** (refreshed monthly), a safety factor `z`
that differs from SKU to SKU, partial anticipation of planned promotions, MOQ and whole boxes.
The policy ignores lead-time variability and the fact that sales are censored. Actual lead times
vary per supplier (bias and lognormal noise), occasionally explode during supply disruptions,
add transit time to the regional plants and end on a working day. Demand that finds no stock is
lost. Purchase orders (order, planned and actual receipt dates; still-open orders without a
receipt) and month-end stock are observable.

### Invoices and prices

Shipped lines become invoice items; one billing document per customer and day, numbered in date
order and, within a day, in random entry order (`90…`), items 10, 20, 30. A line cut short by a stockout ships what is left and is
invoiced in pieces. Net values use that year's price list, the channel discount and any promotion
discount.

### Data-quality problems

| Problem (`issue_type`) | Where | Real-world cause | Labelled as |
|---|---|---|---|
| `truncated_material_code` | `raw/sales`, all rows of some monthly export files | Codes passed through a spreadsheet that turned them into numbers | one label per row |
| `duplicate_row` | `raw/sales` | Monthly exports that overlap at month boundaries; one month exported twice | one label per repeated row, pointing at the first copy |
| `extra_zero` | `raw/sales` | Quantity typed with one or two extra zeros (net value sometimes recomputed) | per row; `detail` gives factor and whether the value was scaled |
| `unit_mismatch` | `raw/sales` | Quantity in boxes recorded with the piece unit, or the reverse | per row |
| `missing_net_value` | `raw/sales` | Pricing missing at billing | per row |
| `future_date` | `raw/sales` | Buddhist-era year typed into a Gregorian field (year + 543), or a year typo | per row; `detail` = `buddhist_era` / `year_typo` |
| `missing_list_price` | `raw/materials` | Price never maintained in the master | per material |
| `duplicate_customer` | `raw/customers` (and their sales) | Same customer entered again in English instead of Thai (or the reverse) or with another romanisation; part of its later orders are booked on the new account | per duplicate account, pointing at the original |

Each ERP record carries at most one entry error (`extra_zero`, `unit_mismatch`,
`missing_net_value` or `future_date`; an extra-zero typo whose net value was recomputed changes
quantity and net value together), and the error is copied into every exported copy of that
record; export problems (overlaps, re-runs, stripped zeros) stack on top. Configured rates are in
`stockpilot.synth.config.IssueRates`; tests prove that the number of corrupted records follows
those rates, that independent re-detection finds exactly the labelled rows, and that no raw cell
differs from the clean truth without a label.

## Why it is realistic

- **ERP conventions.** 18-digit material numbers with leading zeros, 10-digit customer and
  supplier numbers, billing documents and purchase orders numbered like an SAP system, items in
  steps of 10, box/piece units of measure, MOQ in whole boxes, monthly export files.
- **Thai specifics.** The Thai public-holiday calendar (including lunar holidays and in-lieu
  days), Songkran stocking up, Buddhist-era dates, customer names typed in Thai or in one of
  several romanisations, regional distribution centres.
- **A demand mix that matches how practitioners classify.** The four Syntetos–Boylan–Croston
  patterns are assigned and then measured on the generated data with the same weekly ADI/CV²
  rules (see the statistics below).
- **Censored demand.** Sales are true demand capped by the stock a realistic but naive policy
  managed to hold, so stockouts cluster around promotions, volatile items and late suppliers.
  Censoring also changes what the data shows: stockouts cut big orders, so on observed sales
  some lumpy items look intermittent (compare the two measured columns below).
- **Business events.** Promotions with pantry-loading dips, launches with ramp-ups and
  predecessors, discontinuations, customer churn, a lost key account, supplier disruptions.

## Ground truth and how to use it

`data/truth/` exists to **score** later steps, never to feed them: audit, forecasting,
optimisation, MCP and dashboard code must not read it (`tests/test_guards.py` enforces this;
only `stockpilot.synth` and `stockpilot.scoring` may). Intended uses:

- Step 2 (audit): compare findings with `issues` (by `row_id` or `record_key`) and the cleaned
  data with `sales_clean`.
- Step 3 (forecasting): score forecasts against true demand in `demand_daily` — including the
  hidden horizon (`in_horizon = true`) — rather than against censored sales.
- Step 4 (inventory): replay policies on the hidden horizon with true demand, starting from the
  month-end stock of 2025-12-31 and the open purchase orders, whose actual arrival dates are in
  `open_po_receipts`.

Practical notes: `demand_daily` is sparse — it has a row for every SKU, plant and day with
demand or (in the history) a stockout; a missing row means zero demand. Dates are Parquet
`date32`; pandas reads them as `datetime.date` objects. The
Buddhist-era typos (years 2564–2568) do not fit pandas' default nanosecond timestamps — convert
with an explicit unit (for example `pd.to_datetime(..., unit="s")` on epoch seconds) or keep
`datetime.date`. Material codes are strings; never cast them to numbers.

## Generated statistics

<!-- generated:data-stats:start -->
_Rendered by `make docs-stats` from `data/manifest.json` (preset `default`, seed 42, stockpilot 0.1.0). Every number describes synthetic data._

**Volume**

| Item | Value |
|---|---:|
| Materials (SKUs) | 2,000 |
| Customers (unique / accounts incl. duplicates) | 600 / 624 |
| Suppliers | 60 |
| Warehouses (plants) | 3 |
| History | 2021-01-01 to 2025-12-31 (1,826 days, 1,442 working days) |
| Hidden horizon (truth only) | to 2026-06-30 |
| Raw sales rows / clean invoice items | 3,904,156 / 3,820,472 |
| Purchase-order items (open at extraction) | 352,336 (2,576) |
| Promotions (history / planned in horizon) | 4,414 / 683 |
| Launches / discontinuations / launches replacing a predecessor | 240 / 160 / 25 |

**Demand patterns** (share of SKUs; weekly ADI/CV² over each SKU's active window)

| Pattern | Configured target | Measured on true demand | Measured on observed sales |
|---|---:|---:|---:|
| smooth | 35.0% | 35.0% | 35.2% |
| erratic | 15.0% | 15.0% | 14.9% |
| intermittent | 30.0% | 30.0% | 36.4% |
| lumpy | 20.0% | 19.9% | 13.5% |

Assigned and measured pattern agree for 99.9% of SKUs on true demand; 3 SKUs have too little history to classify.

**Service of the company's current replenishment policy** (history)

| Measure | Value |
|---|---:|
| Unit fill rate | 96.5% |
| Lost units | 13,766,951 |
| Demand days with a stockout | 3.8% |

**Injected data-quality problems**

| Problem | Labels (rows or records) | Corrupted ERP records |
|---|---:|---:|
| `truncated_material_code` | 194,072 | - |
| `duplicate_row` | 83,684 | - |
| `extra_zero` | 3,908 | 3,820 |
| `unit_mismatch` | 7,622 | 7,466 |
| `missing_net_value` | 11,687 | 11,461 |
| `future_date` | 1,953 | 1,910 |
| `missing_list_price` | 40 | - |
| `duplicate_customer` | 24 | - |

Export files with stripped leading zeros: 3; re-run export files: 1.

**Structural events** (truth only)

| Event | Count |
|---|---:|
| `customer_churn` | 36 |
| `customer_gain` | 60 |
| `customer_loss` | 1 |
| `product_discontinuation` | 160 |
| `product_launch` | 240 |
| `supply_disruption` | 33 |

The lost key account stops buying on 2024-07-17; it placed 3.5% of company demand in the year before.
<!-- generated:data-stats:end -->

## Data dictionary

<!-- generated:data-dictionary:start -->
### `raw/materials`

Material master export (as of the extraction date).

| Column | Type | Description |
|---|---|---|
| `material_code` | string | 18-digit SAP-style material number with leading zeros |
| `description` | string | Brand and product description |
| `category` | string | Product category code (BEV, SNK, GRO, PER, HOM, STA, ELE, HWT, GFT) |
| `brand` | string | Invented brand name |
| `base_unit` | string | Base unit of measure (PC = piece) |
| `sales_unit` | string | Usual ordering unit (BOX or PC) |
| `units_per_box` | int32 | Pieces per box |
| `list_price_thb` | float64 | Current list price per piece in THB (null = missing) |
| `standard_cost_thb` | float64 | Standard cost per piece in THB |
| `moq` | int32 | Supplier minimum order quantity in pieces (whole boxes) |
| `supplier_id` | string | Supplier of the material |
| `launch_date` | date32 | Date the material was created / launched |
| `status` | string | ACTIVE or DISCONTINUED as of the extraction date |
| `discontinued_date` | date32 | Date sales stopped (null if active) |
| `predecessor_material_code` | string | Material this one replaces (null if none) |

### `raw/suppliers`

Supplier master export.

| Column | Type | Description |
|---|---|---|
| `supplier_id` | string | 10-digit supplier number |
| `supplier_name` | string | Invented supplier name |
| `country` | string | ISO country code of the supplier |
| `planned_lead_time_days` | int32 | Lead time the company plans with (days) |
| `order_cycle_days` | int32 | Days between regular order reviews (7, 14 or 28) |
| `order_weekday` | int32 | Review weekday, 0 = Monday |
| `fixed_order_cost_thb` | float64 | Estimated fixed cost per purchase order in THB |

### `raw/customers`

Customer master export, including duplicate accounts.

| Column | Type | Description |
|---|---|---|
| `customer_id` | string | 10-digit customer number |
| `customer_name` | string | Name as typed in the ERP (Thai or English) |
| `customer_type` | string | MT, WHOLESALE, RETAIL, HORECA or INSTITUTION |
| `province` | string | Province (English name) |
| `latitude` | float64 | Latitude (WGS84) |
| `longitude` | float64 | Longitude (WGS84) |
| `delivering_plant` | string | Plant that serves the customer |
| `created_date` | date32 | Date the account was created |
| `blocked` | bool | Account blocked for ordering as of the extraction date |

### `raw/warehouses`

Distribution centres (plants).

| Column | Type | Description |
|---|---|---|
| `plant` | string | Plant code |
| `name` | string | Distribution centre name |
| `province` | string | Province |
| `latitude` | float64 | Latitude (WGS84) |
| `longitude` | float64 | Longitude (WGS84) |

### `raw/calendar`

Company calendar for the history and the planning horizon.

| Column | Type | Description |
|---|---|---|
| `date` | date32 | Calendar day |
| `is_working_day` | bool | Company open (Monday-Saturday, not a public holiday) |
| `holiday_name` | string | Thai public holiday name from the holidays package (null if none) |

### `raw/promotions`

Promotion calendar as planned by the company (history and horizon).

| Column | Type | Description |
|---|---|---|
| `promo_id` | string | Promotion identifier |
| `material_code` | string | Promoted material |
| `start_date` | date32 | First promotion day |
| `end_date` | date32 | Last promotion day |
| `discount_pct` | int32 | Price discount in percent |

### `raw/sales`

Invoice items from monthly ERP exports, with data-quality problems.

| Column | Type | Description |
|---|---|---|
| `row_id` | int64 | Row number assigned when the export files were loaded |
| `source_file` | string | Monthly export file the row came from |
| `billing_doc` | string | 10-digit billing document number |
| `item` | int32 | Item number within the document (10, 20, ...) |
| `posting_date` | date32 | Posting date as recorded |
| `customer_id` | string | Customer account as recorded |
| `material_code` | string | Material number as exported |
| `plant` | string | Delivering plant |
| `quantity` | int64 | Invoiced quantity in the recorded unit |
| `unit` | string | Recorded unit (BOX or PC) |
| `net_value_thb` | float64 | Net invoice value in THB (null = missing) |

### `raw/purchase_orders`

Purchase-order items with order, planned and actual receipt dates.

| Column | Type | Description |
|---|---|---|
| `po_number` | string | 10-digit purchase order number |
| `po_item` | int32 | Item number within the order (10, 20, ...) |
| `supplier_id` | string | Supplier |
| `material_code` | string | Material |
| `plant` | string | Receiving plant |
| `order_date` | date32 | Order date |
| `planned_delivery_date` | date32 | Delivery date planned with the planned lead time |
| `receipt_date` | date32 | Goods receipt date (null = still open at extraction) |
| `quantity` | int64 | Ordered quantity in pieces |
| `unit` | string | Unit of the quantity (PC) |

### `raw/stock_month_end`

On-hand stock per SKU and plant at each month end.

| Column | Type | Description |
|---|---|---|
| `snapshot_date` | date32 | Month-end date |
| `material_code` | string | Material |
| `plant` | string | Plant |
| `on_hand_qty` | int64 | Unrestricted stock in pieces at the end of the day |

### `truth/issues`

One label per injected data-quality problem (row or master record).

| Column | Type | Description |
|---|---|---|
| `issue_id` | int64 | Label number |
| `issue_type` | string | Problem type (see docs/DATA.md) |
| `table_name` | string | Affected raw table: sales, materials or customers |
| `row_id` | int64 | Affected raw sales row (null for master-data problems) |
| `record_key` | string | billing_doc/item, material_code or customer_id |
| `related_row_id` | int64 | For duplicate rows: the first copy's row_id |
| `related_key` | string | For duplicate customers: the original customer_id |
| `column_name` | string | Column that holds the wrong value |
| `observed_value` | string | Value as found in the raw table |
| `true_value` | string | Correct value |
| `detail` | string | Sub-type, e.g. buddhist_era, factor=10;net_value=kept, th_to_en |

### `truth/sales_clean`

Every ERP invoice item once, with correct values.

| Column | Type | Description |
|---|---|---|
| `row_id` | int64 | First raw sales row holding this record |
| `billing_doc` | string | Billing document |
| `item` | int32 | Item number |
| `posting_date` | date32 | Correct posting date |
| `customer_id` | string | Original (deduplicated) customer |
| `material_code` | string | 18-digit material number |
| `plant` | string | Delivering plant |
| `quantity` | int64 | Correct quantity |
| `unit` | string | Correct unit |
| `net_value_thb` | float64 | Correct net value in THB |

### `truth/demand_daily`

True demand vs. sales per SKU, plant and day (history and horizon).

| Column | Type | Description |
|---|---|---|
| `date` | date32 | Day |
| `material_code` | string | Material |
| `plant` | string | Plant |
| `demand_qty` | int64 | True demand in pieces (orders placed) |
| `sales_qty` | int64 | Pieces shipped (null in the horizon) |
| `lost_qty` | int64 | Demand lost to stockouts (null in the horizon) |
| `stockout` | bool | Demand not fully met or stock empty at day end (null in the horizon) |
| `in_horizon` | bool | Day lies in the hidden horizon after the extraction date |

### `truth/sku_profile`

Generator parameters per SKU (demand pattern, lifecycle, effects).

| Column | Type | Description |
|---|---|---|
| `material_code` | string | Material |
| `pattern` | string | Assigned demand pattern (smooth, erratic, intermittent, lumpy) |
| `category` | string | Category code |
| `lifecycle` | string | mature, new or discontinued |
| `lines_per_week` | float64 | Base rate of order lines per week |
| `size_sigma` | float64 | Lognormal sigma of the order-line size |
| `median_order_qty` | float64 | Median order-line size in the sales unit |
| `gamma_shape` | float64 | Shape of the weekly gamma intensity (erratic only) |
| `season_kappa` | float64 | Exponent applied to the category's seasonal profile |
| `trend_per_year` | float64 | Log-linear trend per year |
| `promo_eligible` | bool | Takes part in promotions |
| `promo_elasticity` | float64 | Uplift = (1 - discount) ^ -elasticity |
| `price_growth_per_year` | float64 | Yearly list-price increase |
| `ramp_weeks` | float64 | Launch ramp-up length in weeks (new only) |
| `decline_weeks` | float64 | Decline length before discontinuation (discontinued only) |

### `truth/customer_profile`

Customer activity windows and purchasing size.

| Column | Type | Description |
|---|---|---|
| `customer_id` | string | Customer |
| `customer_type` | string | Customer type |
| `size_weight` | float64 | Relative purchasing size |
| `active_from` | date32 | First day the customer can order |
| `active_to` | date32 | Last day the customer orders (null = still active) |
| `new_customer` | bool | Acquired during the history |
| `churned` | bool | Stopped buying during the history |
| `major_loss` | bool | The key account whose loss is a structural break |
| `name_lang` | string | Language of the original name (th or en) |
| `name_words` | string | Indices of the two vocabulary words in the name |
| `name_form` | int32 | Index of the business form in the vocabulary |

### `truth/supplier_lead_time`

True lead-time behaviour per supplier.

| Column | Type | Description |
|---|---|---|
| `supplier_id` | string | Supplier |
| `lead_time_bias` | float64 | Mean actual / planned lead time |
| `lead_time_sigma` | float64 | Lognormal sigma of the lead-time noise |

### `truth/supplier_disruptions`

Periods in which a supplier's lead times were inflated.

| Column | Type | Description |
|---|---|---|
| `supplier_id` | string | Supplier |
| `start_date` | date32 | First day of the disruption |
| `end_date` | date32 | Last day of the disruption |
| `lead_time_factor` | float64 | Lead times of orders placed in the period are multiplied by |

### `truth/events`

Structural events: customer losses and gains, disruptions, launches.

| Column | Type | Description |
|---|---|---|
| `event_id` | int64 | Event number |
| `event_type` | string | customer_loss, customer_gain, supply_disruption, launch, ... |
| `entity_id` | string | customer_id, supplier_id or material_code |
| `start_date` | date32 | Date the event takes effect |
| `end_date` | date32 | Last day of a temporary event (null otherwise) |
| `magnitude` | float64 | Share of company demand, or the lead-time factor |
| `description` | string | Plain-language description |

### `truth/promotion_effects`

True uplift and post-promotion dip of every promotion.

| Column | Type | Description |
|---|---|---|
| `promo_id` | string | Promotion |
| `material_code` | string | Material |
| `start_date` | date32 | First promotion day |
| `end_date` | date32 | Last promotion day |
| `dip_end_date` | date32 | Last day of the post-promotion dip |
| `discount_pct` | float64 | Price discount in percent |
| `uplift` | float64 | Demand multiplier during the promotion |
| `dip_factor` | float64 | Demand multiplier during the dip |

### `truth/inventory_policy`

Service factor of the company's replenishment rule per series.

| Column | Type | Description |
|---|---|---|
| `material_code` | string | Material |
| `plant` | string | Plant |
| `service_factor` | float64 | Safety factor z of the company's order-up-to rule |

### `truth/open_po_receipts`

Actual receipt dates of purchase orders open at extraction.

| Column | Type | Description |
|---|---|---|
| `po_number` | string | Purchase order |
| `po_item` | int32 | Item |
| `actual_receipt_date` | date32 | Date the goods actually arrive |
<!-- generated:data-dictionary:end -->

## Limitations

- One currency (THB) and one price list per year; no customer-specific contracts beyond channel
  discounts; no returns, credit notes or rebates.
- No cross-SKU effects: no cannibalisation, halo or substitution (beyond successor SKUs), and no
  price elasticity outside promotions.
- No weather, macro-economic or pandemic effects; real events of 2021–2026 are not modelled.
- A simplified, single replenishment rule; no transfers between plants, no capacity limits, no
  backorders (unmet demand is lost), full deliveries from suppliers.
- Customers are served only by their regional plant; the stockout of one plant never shifts
  demand to another.
- Customer names come from a small word list, so unrelated customers can share words; brands and
  suppliers are numbered labels rather than names; coordinates are approximate city centres with
  small jitter.
- Data-quality problems are limited to the types above; purchase orders, stock snapshots and
  promotions are clean.

## Reproducing and changing the data

```bash
make data                                   # default preset, seed 42, then validation
make data SEED=7                            # another seed
uv run stockpilot synth --preset small --out data-small
uv run stockpilot synth --skus 500 --customers 200 --years 3 --out data-custom
make validate-data                          # re-check data/ against manifest and targets
make docs-stats                             # re-render the blocks above from data/manifest.json
```

The same seed gives byte-identical files across runs, Python 3.11–3.13 and CPU instruction sets:
every random draw comes from a named stream (`stockpilot.synth.rng.stream`), all sorts are
stable, floats are rounded when created, and `uv.lock` pins one version of each dependency.
`tests/test_determinism.py` re-runs the generator on numpy's baseline CPU path with a different
hash seed and compares file hashes.
