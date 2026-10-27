"""Master data of the fictional distributor: warehouses, suppliers, materials and customers.

Observable tables mirror an ERP master-data export as of the extraction date. The generator's
per-entity parameters (demand pattern, true lead-time behaviour, customer activity) live in
separate *profile* tables that belong to the ground truth.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from stockpilot.synth import names
from stockpilot.synth.calendar import Calendar
from stockpilot.synth.catalog import CATEGORIES, CATEGORY_GIVEN_PATTERN
from stockpilot.synth.config import PATTERNS, SynthConfig
from stockpilot.synth.geo import REGION_PLANT, WAREHOUSES, provinces
from stockpilot.synth.rng import stream

CUSTOMER_TYPES = ("MT", "WHOLESALE", "RETAIL", "HORECA", "INSTITUTION")
CUSTOMER_TYPE_SHARE = (0.04, 0.16, 0.55, 0.15, 0.10)
CUSTOMER_TYPE_SIZE = (20.0, 6.0, 1.0, 1.5, 1.2)  # median purchasing size relative to retail
ENGLISH_NAME_SHARE = (0.7, 0.1, 0.05, 0.6, 0.1)  # share of records typed in English, by type
CUSTOMER_SIZE_SIGMA = 1.0  # lognormal spread of purchasing size within a customer type
KEY_ACCOUNT_TYPES = ("MT", "WHOLESALE")
NEW_CUSTOMER_SHARE, CHURN_SHARE = 0.10, 0.06
MAJOR_LOSS_AT = 0.70  # the lost key account stops buying at this fraction of the history

IMPORT_COUNTRIES = ("CN", "VN", "MY", "JP", "ID")
IMPORT_COUNTRY_SHARE = (0.45, 0.20, 0.15, 0.10, 0.10)

# Demand-pattern parameters (calibrated so the measured ADI/CV^2 class matches the assigned one).
LINES_PER_WEEK = {
    "smooth": ("log", 8.0, 40.0),
    "erratic": ("log", 8.0, 30.0),
    "intermittent": ("lin", 0.06, 0.50),
    "lumpy": ("lin", 0.06, 0.50),
}
SIZE_SIGMA = {
    "smooth": (0.25, 0.50),
    "erratic": (0.50, 0.80),
    "intermittent": (0.05, 0.30),
    "lumpy": (0.95, 1.30),
}
SEASON_KAPPA = {
    "smooth": (0.3, 1.0),
    "erratic": (0.3, 1.2),
    "intermittent": (0.0, 1.0),
    "lumpy": (0.0, 1.0),
}
ERRATIC_GAMMA_SHAPE = (1.0, 1.6)
PROMO_ELIGIBLE_SHARE = 0.7

NEW_SKU_SHARE, DISCONTINUED_SHARE, SUCCESSOR_SHARE = 0.12, 0.08, 0.5
NEW_SKU_MIN_HISTORY_DAYS = 182  # launches leave at least 26 weeks of history
FIRST_MASTER_DATE = date(2010, 1, 1)
FIRST_CUSTOMER_DATE = date(2008, 1, 1)
FIRST_CUSTOMER_NUMBER, CUSTOMER_NUMBERS = 100_000, 900_000  # account numbers 100000-999999


@dataclass(frozen=True)
class Master:
    warehouses: pd.DataFrame
    suppliers: pd.DataFrame
    materials: pd.DataFrame
    customers: pd.DataFrame
    sku_profile: pd.DataFrame  # truth
    customer_profile: pd.DataFrame  # truth
    supplier_lead_time: pd.DataFrame  # truth
    disruptions: pd.DataFrame  # truth


def allocate(n: int, shares: tuple[float, ...] | list[float]) -> np.ndarray:
    """Split ``n`` items into integer counts proportional to ``shares`` (largest remainder)."""
    raw = np.asarray(shares, dtype=float) * n / float(np.sum(shares))
    counts = np.floor(raw).astype(int)
    remainder_order = np.argsort(-(raw - counts), kind="stable")
    counts[remainder_order[: n - counts.sum()]] += 1
    return counts


def build_master(cfg: SynthConfig, cal: Calendar) -> Master:
    suppliers, lead_time, disruptions, supplier_categories = _suppliers(cfg, cal)
    materials, sku_profile = _materials(cfg, suppliers, supplier_categories)
    customers, customer_profile = _customers(cfg)
    warehouses = pd.DataFrame(
        [(w.plant, w.name, w.province, w.lat, w.lon) for w in WAREHOUSES],
        columns=["plant", "name", "province", "latitude", "longitude"],
    )
    return Master(
        warehouses=warehouses,
        suppliers=suppliers,
        materials=materials,
        customers=customers,
        sku_profile=sku_profile,
        customer_profile=customer_profile,
        supplier_lead_time=lead_time,
        disruptions=disruptions,
    )


def _history_days(cfg: SynthConfig) -> int:
    return (cfg.history_end - cfg.start).days + 1


def _category_weights(cfg: SynthConfig) -> np.ndarray:
    mix = dict(cfg.pattern_mix)
    weights = sum(mix[p] * np.asarray(CATEGORY_GIVEN_PATTERN[p]) for p in PATTERNS)
    return weights / weights.sum()


def _suppliers(cfg: SynthConfig, cal: Calendar):
    rng = stream(cfg.seed, "suppliers")
    n, n_cat = cfg.n_suppliers, len(CATEGORIES)
    categories: list[set[int]] = [set() for _ in range(n)]
    for c in range(n_cat):  # every category gets at least one supplier
        categories[c % n].add(c)
    for i in range(n_cat, n):  # the rest follow the expected SKU mix
        categories[i].add(int(rng.choice(n_cat, p=_category_weights(cfg))))

    rows, truth = [], []
    labels = 1 + rng.permutation(n)  # numbered, so a name can never be a real company's
    ids = 300001 + rng.permutation(n)
    for i in range(n):
        primary = CATEGORIES[min(categories[i])]
        imported = bool(rng.random() < primary.import_share)
        if imported:
            country = str(IMPORT_COUNTRIES[rng.choice(5, p=IMPORT_COUNTRY_SHARE)])
            lead_time = int(rng.integers(21, 50))
            cycle = 14 if rng.random() < 0.6 else 28
            order_cost = round(float(rng.uniform(5000, 25000)), -2)
            bias = rng.uniform(1.00, 1.25)
        else:
            country, lead_time, cycle = "TH", int(rng.integers(3, 11)), 7
            order_cost = round(float(rng.uniform(300, 1500)), -1)
            bias = rng.uniform(0.95, 1.15)
        supplier_id = f"{ids[i]:010d}"
        rows.append(
            (
                supplier_id,
                names.supplier_name(rng, f"Supplier {labels[i]:03d}", country),
                country,
                lead_time,
                cycle,
                int(rng.integers(0, 5)),
                order_cost,
            )
        )
        truth.append((supplier_id, round(float(bias), 6), round(float(rng.uniform(0.10, 0.35)), 6)))

    suppliers = pd.DataFrame(
        rows,
        columns=[
            "supplier_id",
            "supplier_name",
            "country",
            "planned_lead_time_days",
            "order_cycle_days",
            "order_weekday",
            "fixed_order_cost_thb",
        ],
    )
    lead_time = pd.DataFrame(truth, columns=["supplier_id", "lead_time_bias", "lead_time_sigma"])
    disruptions = _disruptions(cfg, cal, suppliers["supplier_id"].tolist(), rng)
    order = np.argsort(suppliers["supplier_id"].to_numpy(), kind="stable")
    supplier_categories = [categories[i] for i in order]
    return (
        suppliers.iloc[order].reset_index(drop=True),
        lead_time.iloc[order].reset_index(drop=True),
        disruptions,
        supplier_categories,
    )


def _disruptions(cfg: SynthConfig, cal: Calendar, supplier_ids: list[str], rng) -> pd.DataFrame:
    """Supply disruption episodes: orders placed inside one take much longer to arrive."""
    rows = []
    mean_episodes = 0.6 * cfg.history_years / 5
    for supplier_id in supplier_ids:
        taken: list[tuple[int, int]] = []
        for _ in range(min(2, int(rng.poisson(mean_episodes)))):
            start = int(rng.integers(cal.history_start, cal.history_end - 14))
            end = start + int(rng.integers(14, 57)) - 1
            if any(start <= b and a <= end for a, b in taken):
                continue
            taken.append((start, end))
            rows.append(
                (
                    supplier_id,
                    cal.dates[start].item(),
                    cal.dates[min(end, cal.history_end)].item(),
                    round(float(rng.uniform(1.5, 3.0)), 3),
                )
            )
    return pd.DataFrame(rows, columns=["supplier_id", "start_date", "end_date", "lead_time_factor"])


def _materials(cfg: SynthConfig, suppliers: pd.DataFrame, supplier_categories: list[set[int]]):
    rng = stream(cfg.seed, "materials")
    n = cfg.n_skus
    mix = dict(cfg.pattern_mix)
    pattern = np.repeat(np.array(PATTERNS), allocate(n, [mix[p] for p in PATTERNS]))
    pattern = pattern[rng.permutation(n)]
    category = np.empty(n, dtype=int)
    for p in PATTERNS:
        idx = np.flatnonzero(pattern == p)
        category[idx] = rng.choice(len(CATEGORIES), size=idx.size, p=CATEGORY_GIVEN_PATTERN[p])

    codes = np.empty(n, dtype=object)
    for c, cat in enumerate(CATEGORIES):
        idx = np.flatnonzero(category == c)
        numbers = cat.material_prefix * 1_000_000 + rng.choice(1_000_000, idx.size, replace=False)
        codes[idx] = [f"{int(x):018d}" for x in numbers]

    brands = [f"Brand {k:03d}" for k in range(1, max(8, n // 12) + 1)]  # never a real brand
    suppliers_of = {c: [i for i, cats in enumerate(supplier_categories) if c in cats] for c in
                    range(len(CATEGORIES))}  # fmt: skip
    supplier_ids = suppliers["supplier_id"].to_numpy()

    lifecycle, launch, discontinued, ramp, decline = _lifecycle(cfg, pattern, rng)
    predecessor = _successors(cfg, category, pattern, lifecycle, launch, discontinued, rng)

    rows, profile, bands = [], [], []
    for i in range(n):
        cat = CATEGORIES[category[i]]
        p = str(pattern[i])
        product, price_lo, price_hi, boxes = cat.products[rng.integers(len(cat.products))]
        units = int(rng.choice(boxes))
        sales_unit = "BOX" if units >= 6 else "PC"
        price = math.exp(rng.uniform(math.log(price_lo), math.log(price_hi)))
        price = round(round(price * 4) / 4, 2)
        cost = round(price * float(rng.uniform(0.62, 0.85)), 2)
        kind, lo, hi = LINES_PER_WEEK[p]
        lines = (
            math.exp(rng.uniform(math.log(lo), math.log(hi)))
            if kind == "log"
            else rng.uniform(lo, hi)
        )
        sigma = float(rng.uniform(*SIZE_SIGMA[p]))
        fast = p in ("smooth", "erratic")
        top = (4.0 if fast else 3.0) if sales_unit == "BOX" else (6.0 if fast else 4.0)
        median_qty = float(rng.uniform(1.0, top))
        base_per_line = median_qty * math.exp(sigma**2 / 2) * (units if sales_unit == "BOX" else 1)
        moq_boxes = max(1, math.ceil(float(rng.uniform(0.3, 1.5)) * lines * base_per_line / units))
        promo = fast and cat.promotable and bool(rng.random() < PROMO_ELIGIBLE_SHARE)
        brand = brands[rng.integers(len(brands))]
        bands.append((price_lo, price_hi))
        rows.append(
            {
                "material_code": codes[i],
                "description": f"{brand} {product}",
                "category": cat.code,
                "brand": brand,
                "sales_unit": sales_unit,
                "units_per_box": units,
                "list_price_thb": price,
                "standard_cost_thb": cost,
                "moq": moq_boxes * units,
                "supplier_id": supplier_ids[rng.choice(suppliers_of[category[i]])],
                "launch_date": launch[i],
                "discontinued_date": discontinued[i],
                "predecessor_material_code": codes[predecessor[i]] if predecessor[i] >= 0 else None,
            }
        )
        profile.append(
            {
                "material_code": codes[i],
                "pattern": p,
                "category": cat.code,
                "lifecycle": lifecycle[i],
                "lines_per_week": round(float(lines), 6),
                "size_sigma": round(sigma, 6),
                "median_order_qty": round(median_qty, 6),
                "gamma_shape": (
                    round(float(rng.uniform(*ERRATIC_GAMMA_SHAPE)), 6) if p == "erratic" else np.nan
                ),
                "season_kappa": round(float(rng.uniform(*SEASON_KAPPA[p])), 6),
                "trend_per_year": round(float(np.clip(rng.normal(0.02, 0.06), -0.15, 0.20)), 6),
                "promo_eligible": promo,
                "promo_elasticity": round(float(rng.uniform(1.5, 3.5)), 6) if promo else np.nan,
                "price_growth_per_year": round(float(rng.uniform(0.01, 0.04)), 6),
                "ramp_weeks": ramp[i],
                "decline_weeks": decline[i],
            }
        )

    # A successor is the next version of its predecessor's product: same product line, pack,
    # supplier and demand parameters (its customer base is inherited in demand.py).
    for j in np.flatnonzero(predecessor >= 0):
        i = predecessor[j]
        old, new = rows[i], rows[j]
        for key in ("brand", "sales_unit", "units_per_box", "moq", "supplier_id"):
            new[key] = old[key]
        new["description"] = f"{old['description']} V2"
        price = min(bands[i][1], old["list_price_thb"] * float(rng.uniform(1.0, 1.1)))
        new["list_price_thb"] = round(round(price * 4) / 4, 2)
        new["standard_cost_thb"] = round(new["list_price_thb"] * float(rng.uniform(0.62, 0.85)), 2)
        for key in (
            "lines_per_week",
            "size_sigma",
            "median_order_qty",
            "gamma_shape",
            "season_kappa",
        ):
            profile[j][key] = profile[i][key]

    materials = pd.DataFrame(rows)
    materials.insert(4, "base_unit", "PC")
    materials.insert(
        materials.columns.get_loc("launch_date") + 1,
        "status",
        np.where(materials["discontinued_date"].isna(), "ACTIVE", "DISCONTINUED"),
    )
    sku_profile = pd.DataFrame(profile)
    order = np.argsort(codes.astype(str), kind="stable")
    return (
        materials.iloc[order].reset_index(drop=True),
        sku_profile.iloc[order].reset_index(drop=True),
    )


def _lifecycle(cfg: SynthConfig, pattern: np.ndarray, rng):
    """Mature, newly launched (smooth/erratic only) and discontinued SKUs with their dates."""
    n, days = len(pattern), _history_days(cfg)
    fast = np.flatnonzero(np.isin(pattern, ("smooth", "erratic")))
    new = rng.choice(fast, size=min(fast.size, round(NEW_SKU_SHARE * n)), replace=False)
    rest = np.setdiff1d(np.arange(n), new)
    disc = rng.choice(rest, size=min(rest.size, round(DISCONTINUED_SHARE * n)), replace=False)

    lifecycle = np.full(n, "mature", dtype=object)
    lifecycle[new], lifecycle[disc] = "new", "discontinued"
    launch = np.empty(n, dtype=object)
    discontinued = np.full(n, None, dtype=object)
    ramp = np.full(n, np.nan)
    decline = np.full(n, np.nan)
    span = (cfg.start - timedelta(days=cfg.warmup_days) - FIRST_MASTER_DATE).days  # before data
    for i in range(n):
        if lifecycle[i] == "new":
            offset = int(rng.integers(60, days - NEW_SKU_MIN_HISTORY_DAYS + 1))
            launch[i] = cfg.start + timedelta(days=offset)
            ramp[i] = int(rng.integers(2, 7))
        else:
            launch[i] = FIRST_MASTER_DATE + timedelta(days=int(rng.integers(0, span)))
        if lifecycle[i] == "discontinued":
            offset = int(rng.integers(int(0.4 * days), days - 60 + 1))
            discontinued[i] = cfg.start + timedelta(days=offset)
            decline[i] = int(rng.integers(8, 27))
    return lifecycle, launch, discontinued, ramp, decline


def _successors(cfg, category, pattern, lifecycle, launch, discontinued, rng) -> np.ndarray:
    """Pair discontinued SKUs with a new SKU of the same category and demand pattern.

    With probability SUCCESSOR_SHARE a discontinued SKU gets a successor, provided a free launch
    of the same category and pattern exists and its launch can move to just before the
    discontinuation. Returns the predecessor's row for every SKU (-1 if none).
    """
    predecessor = np.full(len(category), -1, dtype=np.int64)
    latest_launch = cfg.history_end - timedelta(days=NEW_SKU_MIN_HISTORY_DAYS)
    earliest_launch = cfg.start + timedelta(days=60)
    free_new = [i for i in range(len(category)) if lifecycle[i] == "new"]
    retired = np.flatnonzero(lifecycle == "discontinued")
    for i in retired[rng.permutation(retired.size)]:
        if rng.random() >= SUCCESSOR_SHARE:
            continue
        new_launch = discontinued[i] - timedelta(days=int(rng.integers(0, 31)))
        match = [j for j in free_new if category[j] == category[i] and pattern[j] == pattern[i]]
        if not match or not earliest_launch <= new_launch <= latest_launch:
            continue
        j = match[0]
        free_new.remove(j)
        launch[j] = new_launch
        predecessor[j] = i
    return predecessor


def _customers(cfg: SynthConfig):
    rng = stream(cfg.seed, "customers")
    n, days = cfg.n_customers, _history_days(cfg)
    ctype_idx = np.repeat(np.arange(len(CUSTOMER_TYPES)), allocate(n, CUSTOMER_TYPE_SHARE))
    ctype_idx = ctype_idx[rng.permutation(n)]
    spread = rng.lognormal(0.0, CUSTOMER_SIZE_SIGMA, size=n)
    size = np.round(spread * np.asarray(CUSTOMER_TYPE_SIZE)[ctype_idx], 6)

    provs = provinces()
    weights = np.array([p.weight for p in provs])
    prov_idx = rng.choice(len(provs), size=n, p=weights / weights.sum())
    jitter = np.clip(rng.normal(0.0, 0.05, size=(n, 2)), -0.15, 0.15)
    lat = np.round([provs[k].lat for k in prov_idx] + jitter[:, 0], 6)
    lon = np.round([provs[k].lon for k in prov_idx] + jitter[:, 1], 6)

    used: set[str] = set()
    customer_names, parts, langs = [], [], []
    for t in ctype_idx:
        lang = "en" if rng.random() < ENGLISH_NAME_SHARE[t] else "th"
        while True:
            name, part = names.customer_name(rng, CUSTOMER_TYPES[t], lang)
            if name not in used:
                break
        used.add(name)
        customer_names.append(name)
        parts.append(part)
        langs.append(lang)

    is_new = np.zeros(n, dtype=bool)
    is_new[rng.choice(n, size=round(NEW_CUSTOMER_SHARE * n), replace=False)] = True
    created = np.empty(n, dtype=object)
    history_span = (cfg.start - FIRST_CUSTOMER_DATE).days
    for i in range(n):
        if is_new[i]:
            created[i] = cfg.start + timedelta(days=int(rng.integers(30, days - 90 + 1)))
        else:
            created[i] = FIRST_CUSTOMER_DATE + timedelta(days=int(rng.integers(0, history_span)))

    active_to = np.full(n, None, dtype=object)
    major = np.zeros(n, dtype=bool)
    key_accounts = np.isin(np.asarray(CUSTOMER_TYPES)[ctype_idx], KEY_ACCOUNT_TYPES) & ~is_new
    by_size = np.argsort(-size, kind="stable")
    candidates = [int(i) for i in by_size if key_accounts[i]][:5]
    lost = candidates[int(rng.integers(len(candidates)))]
    major[lost] = True
    loss_offset = round(MAJOR_LOSS_AT * days) + int(rng.integers(-30, 31))
    active_to[lost] = cfg.start + timedelta(days=loss_offset)
    pool = np.flatnonzero(~is_new & ~major)
    churned = rng.choice(pool, size=min(pool.size, round(CHURN_SHARE * n)), replace=False)
    for i in churned:
        active_to[i] = cfg.start + timedelta(days=int(rng.integers(180, days - 30 + 1)))

    block_before = cfg.extraction_date - timedelta(days=90)
    blocked = np.array([d is not None and d <= block_before for d in active_to])
    # Sparse random account numbers: neither creation order nor duplicates can be read from them.
    ids = np.array(
        [
            f"{FIRST_CUSTOMER_NUMBER + int(k):010d}"
            for k in rng.choice(CUSTOMER_NUMBERS, n, replace=False)
        ]
    )
    customers = pd.DataFrame(
        {
            "customer_id": ids,
            "customer_name": customer_names,
            "customer_type": np.asarray(CUSTOMER_TYPES)[ctype_idx],
            "province": [provs[k].name for k in prov_idx],
            "latitude": lat,
            "longitude": lon,
            "delivering_plant": [REGION_PLANT[provs[k].region] for k in prov_idx],
            "created_date": created,
            "blocked": blocked,
        }
    )
    profile = pd.DataFrame(
        {
            "customer_id": ids,
            "customer_type": np.asarray(CUSTOMER_TYPES)[ctype_idx],
            "size_weight": size,
            "active_from": created,
            "active_to": active_to,
            "new_customer": is_new,
            "churned": np.isin(np.arange(n), churned),
            "major_loss": major,
            "name_lang": langs,
            "name_words": [f"{p.words[0]},{p.words[1]}" for p in parts],
            "name_form": [p.form for p in parts],
        }
    )
    order = np.argsort(ids, kind="stable")
    return customers.iloc[order].reset_index(drop=True), profile.iloc[order].reset_index(drop=True)
