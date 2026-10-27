"""Render documentation blocks from a run's manifest and keep them in sync.

Docs contain blocks delimited by ``<!-- generated:NAME:start -->`` and
``<!-- generated:NAME:end -->``; only the text between the markers is ever rewritten, so every
number in the docs comes from a real, reproducible run.
"""

from __future__ import annotations

from pathlib import Path

from stockpilot.synth.config import PATTERNS
from stockpilot.synth.export import SCHEMAS, TABLE_DESCRIPTIONS

TYPE_NAMES = {"double": "float64", "date32[day]": "date32"}


def _pct(share: float) -> str:
    return f"{share * 100:.1f}%"


def _n(value: int) -> str:
    return f"{value:,}"


def render_stats(manifest: dict) -> str:
    s, dates = manifest["stats"], manifest["dates"]
    v, p, svc, life = s["volume"], s["patterns"], s["service"], s["lifecycle"]
    issues, events = s["issues"], s["events"]
    lines = [
        f"_Rendered by `make docs-stats` from `data/manifest.json` (preset `{manifest['preset']}`,"
        f" seed {manifest['seed']}, stockpilot {manifest['version']}). Every number describes"
        " synthetic data._",
        "",
        "**Volume**",
        "",
        "| Item | Value |",
        "|---|---:|",
        f"| Materials (SKUs) | {_n(v['materials'])} |",
        f"| Customers (unique / accounts incl. duplicates) | {_n(v['customers'])} /"
        f" {_n(v['customer_accounts_raw'])} |",
        f"| Suppliers | {_n(v['suppliers'])} |",
        f"| Warehouses (plants) | {_n(v['plants'])} |",
        f"| History | {dates['history_start']} to {dates['history_end']}"
        f" ({_n(v['history_days'])} days, {_n(v['working_days'])} working days) |",
        f"| Hidden horizon (truth only) | to {dates['horizon_end']} |",
        f"| Raw sales rows / clean invoice items | {_n(v['sales_rows_raw'])} /"
        f" {_n(v['sales_records'])} |",
        f"| Purchase-order items (open at extraction) | {_n(v['purchase_order_items'])}"
        f" ({_n(v['open_purchase_order_items'])}) |",
        f"| Promotions (history / planned in horizon) | {_n(v['promotions_history'])} /"
        f" {_n(v['promotions_horizon'])} |",
        f"| Launches / discontinuations / launches replacing a predecessor |"
        f" {_n(life['launched'])} / {_n(life['discontinued'])} / {_n(life['with_predecessor'])} |",
        "",
        "**Demand patterns** (share of SKUs; weekly ADI/CV² over each SKU's active window)",
        "",
        "| Pattern | Configured target | Measured on true demand | Measured on observed sales |",
        "|---|---:|---:|---:|",
    ]
    for pattern in PATTERNS:
        lines.append(
            f"| {pattern} | {_pct(p['target'][pattern])} | {_pct(p['true_demand'][pattern])} |"
            f" {_pct(p['observed_sales'][pattern])} |"
        )
    lines += [
        "",
        f"Assigned and measured pattern agree for {_pct(p['agreement'])} of SKUs on true demand;"
        f" {_n(p['insufficient_history'])} SKUs have too little history to classify.",
        "",
        "**Service of the company's current replenishment policy** (history)",
        "",
        "| Measure | Value |",
        "|---|---:|",
        f"| Unit fill rate | {_pct(svc['fill_rate'])} |",
        f"| Lost units | {_n(svc['lost_units'])} |",
        f"| Demand days with a stockout | {_pct(svc['stockout_share_of_demand_days'])} |",
        "",
        "**Injected data-quality problems**",
        "",
        "| Problem | Labels (rows or records) | Corrupted ERP records |",
        "|---|---:|---:|",
    ]
    for kind, count in issues["labels"].items():
        records = issues["corrupted_records"].get(kind)
        lines.append(f"| `{kind}` | {_n(count)} | {_n(records) if records is not None else '-'} |")
    lines += [
        "",
        f"Export files with stripped leading zeros: {issues['truncated_files']};"
        f" re-run export files: {issues['rerun_files']}.",
        "",
        "**Structural events** (truth only)",
        "",
        "| Event | Count |",
        "|---|---:|",
    ]
    for kind, count in events["by_type"].items():
        lines.append(f"| `{kind}` | {_n(count)} |")
    if events["key_account_loss_date"]:
        lines += [
            "",
            f"The lost key account stops buying on {events['key_account_loss_date']}; it placed"
            f" {_pct(events['key_account_demand_share'])} of company demand in the year before.",
        ]
    return "\n".join(lines)


def render_dictionary() -> str:
    parts = []
    for name, schema in SCHEMAS.items():
        parts += [f"### `{name}`", "", TABLE_DESCRIPTIONS[name], ""]
        parts += ["| Column | Type | Description |", "|---|---|---|"]
        for field in schema:
            kind = TYPE_NAMES.get(str(field.type), str(field.type))
            parts.append(f"| `{field.name}` | {kind} | {field.metadata[b'description'].decode()} |")
        parts.append("")
    return "\n".join(parts).rstrip("\n")


def render_readme_summary(manifest: dict) -> str:
    v, dates = manifest["stats"]["volume"], manifest["dates"]
    return (
        f"The default synthetic dataset (seed {manifest['seed']}) covers {dates['history_start']}"
        f" to {dates['history_end']}: {_n(v['materials'])} SKUs, {_n(v['customers'])} customers,"
        f" {_n(v['suppliers'])} suppliers and {_n(v['plants'])} warehouses, with"
        f" {_n(v['sales_rows_raw'])} raw sales rows and {_n(v['purchase_order_items'])}"
        " purchase-order items. Details and limitations: [docs/DATA.md](docs/DATA.md)."
    )


BLOCKS = {
    "data-stats": render_stats,
    "data-dictionary": lambda manifest: render_dictionary(),
    "readme-summary": render_readme_summary,
}


def _markers(name: str) -> tuple[str, str]:
    return f"<!-- generated:{name}:start -->", f"<!-- generated:{name}:end -->"


def sync_block(path: Path, name: str, text: str, check: bool) -> bool:
    """Put ``text`` between the markers of block ``name``; return whether the file differs."""
    start, end = _markers(name)
    content = path.read_text(encoding="utf-8")
    i, j = content.find(start), content.find(end)
    if i < 0 or j < i:
        raise ValueError(f"{path}: markers for generated block {name!r} not found")
    updated = content[: i + len(start)] + "\n" + text.strip("\n") + "\n" + content[j:]
    changed = updated != content
    if changed and not check:
        path.write_text(updated, encoding="utf-8")
    return changed


def sync_docs(manifest: dict, docs: list[Path], check: bool) -> list[str]:
    """Sync every known block found in ``docs``; return ``path:block`` entries that changed."""
    changed = []
    for path in docs:
        content = path.read_text(encoding="utf-8")
        present = [name for name in BLOCKS if _markers(name)[0] in content]
        if not present:
            raise ValueError(f"{path}: no generated blocks found")
        for name in present:
            if sync_block(path, name, BLOCKS[name](manifest), check):
                changed.append(f"{path}:{name}")
    return changed
