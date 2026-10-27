"""Synthetic data generator for a fictional Thai distributor (all data is synthetic).

``generate(cfg)`` runs the whole simulation in memory and returns every table;
``write(result, out_dir)`` stores them as Parquet under ``raw/`` (what the company's ERP would
export) and ``truth/`` (ground truth for scoring only) and writes ``manifest.json``.
"""

from __future__ import annotations

import json
import platform
import shutil
import sys
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from stockpilot import __version__
from stockpilot.synth.calendar import Calendar, build_calendar
from stockpilot.synth.config import SynthConfig
from stockpilot.synth.demand import Lines, build_rates, generate_lines
from stockpilot.synth.export import NOTICE, SCHEMAS, sha256, to_arrow, write_table
from stockpilot.synth.inventory import simulate
from stockpilot.synth.issues import inject
from stockpilot.synth.master import Master, build_master
from stockpilot.synth.promotions import build_promotions
from stockpilot.synth.sales import build_sales_clean

__all__ = ["SynthResult", "generate", "write"]


@dataclass(frozen=True)
class SynthResult:
    cfg: SynthConfig
    tables: dict[str, pd.DataFrame]  # keyed "raw/<name>" or "truth/<name>"


def generate(cfg: SynthConfig) -> SynthResult:
    cal = build_calendar(cfg)
    master = build_master(cfg, cal)
    promos = build_promotions(cfg, cal, master)
    lines = generate_lines(cfg, cal, master, build_rates(cfg, cal, master, promos))
    inv = simulate(cfg, cal, master, lines, promos.planning)
    injected = inject(cfg, cal, master, build_sales_clean(cfg, cal, master, lines, inv, promos))
    tables = {
        "raw/materials": injected.raw_materials,
        "raw/suppliers": master.suppliers,
        "raw/customers": injected.raw_customers,
        "raw/warehouses": master.warehouses,
        "raw/calendar": _calendar_table(cal),
        "raw/promotions": promos.table,
        "raw/sales": injected.raw_sales,
        "raw/purchase_orders": inv.purchase_orders,
        "raw/stock_month_end": inv.stock_month_end,
        "truth/issues": injected.issues,
        "truth/sales_clean": injected.sales_clean,
        "truth/demand_daily": inv.demand_daily,
        "truth/sku_profile": master.sku_profile,
        "truth/customer_profile": master.customer_profile,
        "truth/supplier_lead_time": master.supplier_lead_time,
        "truth/supplier_disruptions": master.disruptions,
        "truth/events": _events(cal, master, lines),
        "truth/promotion_effects": promos.truth.drop(columns="sku"),
        "truth/inventory_policy": inv.policy,
        "truth/open_po_receipts": inv.open_po_receipts,
    }
    return SynthResult(cfg=cfg, tables=tables)


def write(result: SynthResult, out_dir: str | Path) -> dict:
    """Write all tables, ``manifest.json`` and ``run_info.json``; return the manifest."""
    from stockpilot.synth.validate import dataset_stats  # validate imports this package

    out = Path(out_dir)
    _prepare(out)
    started = perf_counter()
    entries = {}
    for name, frame in result.tables.items():
        table = to_arrow(frame, SCHEMAS[name], name, result.cfg.seed)
        path = out / f"{name}.parquet"
        write_table(table, path)
        entries[name] = {"rows": table.num_rows, "sha256": sha256(path)}
    cfg = result.cfg
    manifest = {
        "synthetic": True,
        "notice": NOTICE,
        "generator": "stockpilot.synth",
        "version": __version__,
        "preset": cfg.preset,
        "seed": cfg.seed,
        "config": cfg.to_dict(),
        "dates": {
            "history_start": cfg.start.isoformat(),
            "history_end": cfg.history_end.isoformat(),
            "extraction_date": cfg.extraction_date.isoformat(),
            "horizon_end": cfg.horizon_end.isoformat(),
        },
        "tables": entries,
        "stats": dataset_stats(out, cfg),
    }
    manifest = json.loads(json.dumps(manifest))
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    (out / "manifest.json").write_text(text, encoding="utf-8")
    run_info = {
        "elapsed_seconds_writing": round(perf_counter() - started, 1),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {p: version(p) for p in ("numpy", "pandas", "pyarrow", "holidays")},
        "argv": sys.argv,
    }
    (out / "run_info.json").write_text(json.dumps(run_info, indent=2) + "\n", encoding="utf-8")
    return manifest


def _prepare(out: Path) -> None:
    """Create ``out`` or clear a previous StockPilot dataset in it; never touch anything else."""
    if out.exists() and any(out.iterdir()):
        if not (out / "manifest.json").is_file():
            raise FileExistsError(
                f"refusing to write into {out}: it is not empty and holds no StockPilot dataset"
            )
        for sub in ("raw", "truth"):
            shutil.rmtree(out / sub, ignore_errors=True)
        for name in ("manifest.json", "run_info.json"):
            (out / name).unlink(missing_ok=True)
    out.mkdir(parents=True, exist_ok=True)


def _calendar_table(cal: Calendar) -> pd.DataFrame:
    days = slice(cal.history_start, cal.n_days)
    names = cal.holiday_name[days]
    return pd.DataFrame(
        {
            "date": [d.item() for d in cal.dates[days]],
            "is_working_day": cal.is_working[days],
            "holiday_name": [n if n else None for n in names],
        }
    )


def _events(cal: Calendar, master: Master, lines: Lines) -> pd.DataFrame:
    """Structural events with their size as a share of company-wide demand."""
    n_cust = len(master.customers)
    per_customer = np.bincount(
        lines.customer.astype(np.int64) * cal.n_days + lines.day,
        lines.qty_base,
        n_cust * cal.n_days,
    ).reshape(n_cust, cal.n_days)
    total = per_customer.sum(axis=0)
    first = cal.dates[0]

    def share(customer: int, start: int, stop: int) -> float:
        lo, hi = max(0, start), min(cal.n_days, stop)
        whole = total[lo:hi].sum()
        return round(float(per_customer[customer, lo:hi].sum() / whole), 6) if whole else 0.0

    def day(d) -> int:
        return int((np.datetime64(d, "D") - first).astype(int))

    rows = []
    profile = master.customer_profile
    for i, row in profile.iterrows():
        if row["active_to"] is not None and not pd.isna(row["active_to"]):
            end = day(row["active_to"])
            kind = "customer_loss" if row["major_loss"] else "customer_churn"
            text = "Key account stops buying" if row["major_loss"] else "Customer stops buying"
            start = (np.datetime64(row["active_to"], "D") + 1).item()
            rows.append((kind, row["customer_id"], start, None, share(i, end - 364, end + 1), text))
        if row["new_customer"]:
            begin = day(row["active_from"])
            gained = share(i, begin, begin + 365)
            rows.append(("customer_gain", row["customer_id"], row["active_from"], None, gained,
                         "New customer starts buying"))  # fmt: skip
    for row in master.disruptions.itertuples(index=False):
        rows.append(("supply_disruption", row.supplier_id, row.start_date, row.end_date,
                     row.lead_time_factor, "Supplier lead times inflated"))  # fmt: skip
    materials = master.materials
    lifecycle = master.sku_profile["lifecycle"].to_numpy()
    for i, m in materials.iterrows():
        if lifecycle[i] == "new":
            text = "New product launched"
            if m["predecessor_material_code"] is not None and not pd.isna(
                m["predecessor_material_code"]
            ):
                text += f" to replace {m['predecessor_material_code']}"
            rows.append(("product_launch", m["material_code"], m["launch_date"], None, None, text))
        if m["status"] == "DISCONTINUED":
            rows.append(("product_discontinuation", m["material_code"], m["discontinued_date"],
                         None, None, "Product discontinued"))  # fmt: skip
    events = pd.DataFrame(
        rows,
        columns=["event_type", "entity_id", "start_date", "end_date", "magnitude", "description"],
    )
    events = events.sort_values(["start_date", "event_type", "entity_id"], kind="stable")
    events.insert(0, "event_id", np.arange(1, len(events) + 1, dtype=np.int64))
    return events.reset_index(drop=True)
