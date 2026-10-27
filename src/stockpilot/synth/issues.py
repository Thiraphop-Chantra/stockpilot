"""Deliberate data-quality problems and their ground-truth labels.

Problems are injected in the order they arise in a real company:

1. master data: materials without a list price; customers entered a second time under another
   spelling (Thai vs English, or another romanisation), after which part of their orders is
   booked on the duplicate account;
2. ERP entry errors on single invoice items (at most one per item): quantities typed with
   extra zeros, a box/piece unit label that does not match the quantity, a missing net value,
   a posting date in the future (Buddhist-era year or a year typo);
3. export artefacts: monthly export files that overlap at month boundaries, one month exported
   twice, and a few files whose material codes lost their leading zeros in a spreadsheet.

Every affected raw row (or master record) gets one label in ``issues``; duplicate copies inherit
the entry errors of the record they copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from stockpilot.synth import names
from stockpilot.synth.calendar import Calendar
from stockpilot.synth.config import IssueRates, SynthConfig
from stockpilot.synth.master import Master
from stockpilot.synth.rng import stream

ENTRY_ERROR_TYPES = ("extra_zero", "unit_mismatch", "missing_net_value", "future_date")
ISSUE_TYPES = (
    "truncated_material_code",
    "duplicate_row",
    *ENTRY_ERROR_TYPES,
    "missing_list_price",
    "duplicate_customer",
)
ISSUE_COLUMNS = [
    "issue_type",
    "table_name",
    "row_id",
    "record_key",
    "related_row_id",
    "related_key",
    "column_name",
    "observed_value",
    "true_value",
    "detail",
]
EXTRA_ZERO_TENFOLD_SHARE = 0.9  # otherwise a hundredfold
EXTRA_ZERO_VALUE_SCALED_SHARE = 0.5  # the system recomputed the net value from the typo
BUDDHIST_ERA_OFFSET, BUDDHIST_ERA_SHARE = 543, 0.7
DUPLICATE_SHARE_OF_ORDERS = (0.3, 0.7)


@dataclass(frozen=True)
class Injected:
    raw_sales: pd.DataFrame
    raw_materials: pd.DataFrame
    raw_customers: pd.DataFrame
    sales_clean: pd.DataFrame  # truth: one row per ERP record, pointing at its first raw copy
    issues: pd.DataFrame  # truth
    expected_counts: dict[str, int]


def _count(rate: float, eligible: int) -> int:
    return max(1, round(rate * eligible))


def inject(cfg: SynthConfig, cal: Calendar, master: Master, sales: pd.DataFrame) -> Injected:
    rates = cfg.issues
    rng = stream(cfg.seed, "issues")
    raw_materials, price_labels = _missing_list_prices(master, rates, rng)
    raw_customers, duplicates, customer_labels = _duplicate_customers(cfg, cal, master, rates, rng)

    erp = sales.copy()
    erp["customer_id"] = _book_on_duplicates(erp, duplicates, rng)
    errors = _entry_errors(cfg, master, erp, rates, rng)

    raw, record_of_row, files = _exports(erp, sales["posting_date"], rates, rng)
    first_row = _first_rows(record_of_row)
    clean = sales.copy()
    clean.insert(0, "row_id", first_row.astype(np.int64))

    keys = (erp["billing_doc"] + "/" + erp["item"].astype(str)).to_numpy()
    row_labels = [
        _truncation_labels(raw, files, keys, record_of_row),
        _duplicate_labels(record_of_row, first_row, keys),
        _entry_error_labels(errors, record_of_row, keys),
    ]
    issues = pd.concat([*row_labels, price_labels, customer_labels], ignore_index=True)
    issues["type_order"] = issues["issue_type"].map({t: k for k, t in enumerate(ISSUE_TYPES)})
    issues = issues.sort_values(["type_order", "row_id", "record_key"], kind="stable")
    issues = issues.drop(columns="type_order").reset_index(drop=True)
    issues.insert(0, "issue_id", np.arange(1, len(issues) + 1, dtype=np.int64))
    for column in ("row_id", "related_row_id"):
        issues[column] = issues[column].astype("Int64")

    expected = {kind: int((errors["issue_type"] == kind).sum()) for kind in ENTRY_ERROR_TYPES}
    expected["missing_list_price"] = len(price_labels)
    expected["duplicate_customer"] = len(customer_labels)
    expected["truncated_files"] = len(files["truncated"])
    expected["rerun_files"] = len(files["rerun"])
    expected["overlapping_month_boundaries"] = len(files["overlaps"])
    return Injected(
        raw_sales=raw,
        raw_materials=raw_materials,
        raw_customers=raw_customers,
        sales_clean=clean,
        issues=issues,
        expected_counts=expected,
    )


def _missing_list_prices(master: Master, rates: IssueRates, rng):
    materials = master.materials.copy()
    k = _count(rates.missing_list_price, len(materials))
    chosen = np.sort(rng.choice(len(materials), size=k, replace=False))
    true_price = materials.loc[chosen, "list_price_thb"].to_numpy()
    materials.loc[chosen, "list_price_thb"] = np.nan
    labels = pd.DataFrame(
        {
            "issue_type": "missing_list_price",
            "table_name": "materials",
            "record_key": materials.loc[chosen, "material_code"].to_numpy(),
            "column_name": "list_price_thb",
            "true_value": [f"{p:.2f}" for p in true_price],
        }
    )
    return materials, labels.reindex(columns=ISSUE_COLUMNS)


def _duplicate_customers(cfg: SynthConfig, cal: Calendar, master: Master, rates: IssueRates, rng):
    customers, profile = master.customers, master.customer_profile
    latest_original = cfg.history_end - timedelta(days=365)
    pool = np.flatnonzero(
        (customers["created_date"] <= latest_original).to_numpy()
        & profile["active_to"].isna().to_numpy()
    )
    k = min(pool.size, _count(rates.duplicate_customer, len(customers)))
    chosen = np.sort(rng.choice(pool, size=k, replace=False))
    next_id = int(customers["customer_id"].astype(int).max()) + 1
    days = (cfg.history_end - cfg.start).days
    rows, labels, duplicates = [], [], []
    for j, i in enumerate(chosen):
        original = customers.iloc[i]
        words = tuple(int(w) for w in profile.at[i, "name_words"].split(","))
        parts = names.NameParts(original["customer_type"], words, int(profile.at[i, "name_form"]))
        name, kind = names.variant_name(rng, parts, profile.at[i, "name_lang"])
        earliest = max(30, (original["created_date"] - cfg.start).days + 30)
        created = cfg.start + timedelta(days=int(rng.integers(earliest, days - 120 + 1)))
        dup_id = f"{next_id + j:010d}"
        row = original.copy()
        row["customer_id"], row["customer_name"], row["created_date"] = dup_id, name, created
        row["latitude"] = round(float(original["latitude"] + rng.normal(0.0, 0.002)), 6)
        row["longitude"] = round(float(original["longitude"] + rng.normal(0.0, 0.002)), 6)
        row["blocked"] = False
        rows.append(row)
        share = float(rng.uniform(*DUPLICATE_SHARE_OF_ORDERS))
        duplicates.append((original["customer_id"], dup_id, created, share))
        labels.append(
            {
                "issue_type": "duplicate_customer",
                "table_name": "customers",
                "record_key": dup_id,
                "related_key": original["customer_id"],
                "column_name": "customer_id",
                "observed_value": name,
                "true_value": original["customer_name"],
                "detail": kind,
            }
        )
    raw = pd.concat([customers, pd.DataFrame(rows)], ignore_index=True)
    raw = raw.sort_values("customer_id", kind="stable").reset_index(drop=True)
    return raw, duplicates, pd.DataFrame(labels).reindex(columns=ISSUE_COLUMNS)


def _book_on_duplicates(erp: pd.DataFrame, duplicates, rng) -> np.ndarray:
    """Whole billing documents of a duplicated customer are booked on the duplicate account."""
    customer = erp["customer_id"].to_numpy(copy=True)
    for original, dup_id, created, share in duplicates:
        mask = (customer == original) & (erp["posting_date"] >= pd.Timestamp(created)).to_numpy()
        docs = np.unique(erp.loc[mask, "billing_doc"].to_numpy())
        moved = docs[rng.random(docs.size) < share]
        customer[mask & erp["billing_doc"].isin(moved).to_numpy()] = dup_id
    return customer


def _entry_errors(cfg: SynthConfig, master: Master, erp: pd.DataFrame, rates: IssueRates, rng):
    """Corrupt single ERP records in place; return one row per corrupted record."""
    n = len(erp)
    units = erp["material_code"].map(master.materials.set_index("material_code")["units_per_box"])
    eligible = {
        "extra_zero": np.ones(n, dtype=bool),
        "unit_mismatch": (units > 1).to_numpy(),
        "missing_net_value": np.ones(n, dtype=bool),
        "future_date": np.ones(n, dtype=bool),
    }
    order = rng.permutation(n)
    taken = np.zeros(n, dtype=bool)
    chosen = {}
    for kind in ENTRY_ERROR_TYPES:
        k = _count(getattr(rates, kind), int(eligible[kind].sum()))
        pick = order[eligible[kind][order] & ~taken[order]][:k]
        taken[pick] = True
        chosen[kind] = np.sort(pick)

    quantity = erp["quantity"].to_numpy(copy=True)
    unit = erp["unit"].to_numpy(copy=True)
    value = erp["net_value_thb"].to_numpy(copy=True)
    posting = erp["posting_date"].to_numpy(copy=True)
    parts = []

    idx = chosen["extra_zero"]
    factor = np.where(rng.random(idx.size) < EXTRA_ZERO_TENFOLD_SHARE, 10, 100)
    scaled = rng.random(idx.size) < EXTRA_ZERO_VALUE_SCALED_SHARE
    parts.append(_error_rows("extra_zero", idx, "quantity", quantity[idx] * factor, quantity[idx],
                             [f"factor={f};net_value={'scaled' if s else 'kept'}"
                              for f, s in zip(factor, scaled, strict=True)]))  # fmt: skip
    quantity[idx] *= factor
    value[idx] = np.where(scaled, np.round(value[idx] * factor, 2), value[idx])

    idx = chosen["unit_mismatch"]
    flipped = np.where(unit[idx] == "BOX", "PC", "BOX")
    parts.append(_error_rows("unit_mismatch", idx, "unit", flipped, unit[idx], None))
    unit[idx] = flipped

    idx = chosen["missing_net_value"]
    parts.append(_error_rows("missing_net_value", idx, "net_value_thb", None,
                             [f"{v:.2f}" for v in value[idx]], None))  # fmt: skip
    value[idx] = np.nan

    idx = chosen["future_date"]
    true_dates = [pd.Timestamp(d).date() for d in posting[idx]]
    latest_typo = cfg.extraction_date - timedelta(days=365)  # +1 year must land after extraction
    new_dates, kinds = [], []
    for d, draw in zip(true_dates, rng.random(idx.size), strict=True):
        if draw < BUDDHIST_ERA_SHARE or d <= latest_typo:
            new_dates.append(_shift_year(d, BUDDHIST_ERA_OFFSET))
            kinds.append("buddhist_era")
        else:
            new_dates.append(_shift_year(d, 1))
            kinds.append("year_typo")
    parts.append(_error_rows("future_date", idx, "posting_date", [d.isoformat() for d in new_dates],
                             [d.isoformat() for d in true_dates], kinds))  # fmt: skip
    posting[idx] = np.array(new_dates, dtype="datetime64[s]")

    erp["quantity"], erp["unit"], erp["net_value_thb"] = quantity, unit, value
    erp["posting_date"] = posting.astype("datetime64[s]")
    return pd.concat(parts, ignore_index=True)


def _error_rows(kind, idx, column, observed, true, detail) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "record": idx,
            "issue_type": kind,
            "column_name": column,
            "observed_value": None if observed is None else [str(v) for v in observed],
            "true_value": [str(v) for v in true],
            "detail": detail,
        }
    )


def _shift_year(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February in a non-leap target year
        return d.replace(year=d.year + years, day=28)


def _exports(erp: pd.DataFrame, true_dates: pd.Series, rates: IssueRates, rng):
    """Split ERP records into monthly export files with overlaps, a re-run and stripped codes."""
    period = true_dates.dt.year.to_numpy() * 12 + true_dates.dt.month.to_numpy() - 1
    day_of_month = true_dates.dt.day.to_numpy()
    months = np.unique(period)
    members = {m: np.flatnonzero(period == m) for m in months}
    files: list[tuple[str, np.ndarray]] = []
    overlaps = []
    reruns = set(rng.choice(months.size, size=min(rates.rerun_months, months.size), replace=False))
    for k, m in enumerate(months):
        rows = members[m]
        if k + 1 < months.size and rng.random() < rates.month_overlap_prob:
            spill = int(rng.integers(1, 4))
            nxt = members[months[k + 1]]
            rows = np.concatenate([rows, nxt[day_of_month[nxt] <= spill]])
            overlaps.append((int(m), spill))
        name = f"SALES_EXPORT_{m // 12}_{m % 12 + 1:02d}"
        files.append((name, rows))
        if k in reruns:
            files.append((f"{name}_RERUN", rows))
    regular = [k for k, (name, _) in enumerate(files) if not name.endswith("_RERUN")]
    n_truncated = min(len(regular), _count(rates.truncated_file_share, len(regular)))
    truncated = {files[k][0] for k in rng.choice(regular, size=n_truncated, replace=False)}

    record_of_row = np.concatenate([rows for _, rows in files])
    source = np.concatenate([np.full(rows.size, name, dtype=object) for name, rows in files])
    raw = erp.iloc[record_of_row].reset_index(drop=True)
    raw.insert(0, "source_file", source)
    raw.insert(0, "row_id", np.arange(len(raw), dtype=np.int64))
    hit = raw["source_file"].isin(truncated)
    raw.loc[hit, "material_code"] = raw.loc[hit, "material_code"].str.lstrip("0")
    reruns_named = sorted(name for name, _ in files if name.endswith("_RERUN"))
    info = {"truncated": sorted(truncated), "rerun": reruns_named, "overlaps": overlaps}
    return raw, record_of_row, info


def _first_rows(record_of_row: np.ndarray) -> np.ndarray:
    """Row id of the first raw copy of every ERP record (records are 0..n-1)."""
    _, first = np.unique(record_of_row, return_index=True)
    return first


def _truncation_labels(raw, files, keys, record_of_row) -> pd.DataFrame:
    hit = raw["source_file"].isin(files["truncated"]).to_numpy()
    rows = np.flatnonzero(hit)
    return pd.DataFrame(
        {
            "issue_type": "truncated_material_code",
            "table_name": "sales",
            "row_id": rows,
            "record_key": keys[record_of_row[rows]],
            "column_name": "material_code",
            "observed_value": raw["material_code"].to_numpy()[rows],
            "true_value": [f"{int(c):018d}" for c in raw["material_code"].to_numpy()[rows]],
            "detail": raw["source_file"].to_numpy()[rows],
        }
    ).reindex(columns=ISSUE_COLUMNS)


def _duplicate_labels(record_of_row, first_row, keys) -> pd.DataFrame:
    rows = np.flatnonzero(first_row[record_of_row] != np.arange(record_of_row.size))
    return pd.DataFrame(
        {
            "issue_type": "duplicate_row",
            "table_name": "sales",
            "row_id": rows,
            "record_key": keys[record_of_row[rows]],
            "related_row_id": first_row[record_of_row[rows]],
        }
    ).reindex(columns=ISSUE_COLUMNS)


def _entry_error_labels(errors: pd.DataFrame, record_of_row, keys) -> pd.DataFrame:
    """One label per raw row whose ERP record carries an entry error (copies included)."""
    by_record = errors.set_index("record")
    rows = np.flatnonzero(np.isin(record_of_row, by_record.index.to_numpy()))
    records = record_of_row[rows]
    out = by_record.loc[records].reset_index(drop=True)
    out["table_name"] = "sales"
    out["row_id"] = rows
    out["record_key"] = keys[records]
    return out.reindex(columns=ISSUE_COLUMNS)
