"""Command-line entry point: ``stockpilot <command>``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from stockpilot import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stockpilot",
        description="StockPilot: raw distributor data to replenishment decisions (synthetic data).",
    )
    parser.add_argument("--version", action="version", version=f"stockpilot {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="<command>")

    synth = commands.add_parser("synth", help="generate the synthetic dataset")
    synth.add_argument("--preset", default="default", choices=["default", "small", "tiny"])
    synth.add_argument("--seed", type=int, help="random seed (default: 42)")
    synth.add_argument("--out", default="data", help="output directory (default: data)")
    synth.add_argument("--skus", type=int, help="override the number of SKUs")
    synth.add_argument("--customers", type=int, help="override the number of customers")
    synth.add_argument("--suppliers", type=int, help="override the number of suppliers")
    synth.add_argument("--years", type=int, help="override the number of history years")
    synth.set_defaults(handler=_synth)

    validate = commands.add_parser("validate", help="check a generated dataset")
    validate.add_argument("--data", default="data", help="dataset directory (default: data)")
    validate.set_defaults(handler=_validate)

    docs = commands.add_parser("docs-stats", help="render doc blocks from a dataset manifest")
    docs.add_argument("--data", default="data", help="dataset directory (default: data)")
    docs.add_argument(
        "--docs",
        nargs="+",
        default=["docs/DATA.md", "README.md"],
        help="documents with generated blocks (default: docs/DATA.md README.md)",
    )
    docs.add_argument("--check", action="store_true", help="fail if a block is out of date")
    docs.set_defaults(handler=_docs_stats)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code (argparse exits are turned into return codes)."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help, --version and usage errors
        return exc.code if isinstance(exc.code, int) else 0
    if args.command is None:
        parser.print_help()
        return 0
    return args.handler(args)


def _synth(args: argparse.Namespace) -> int:
    from stockpilot.synth import generate, write
    from stockpilot.synth.config import SynthConfig

    sizes = {
        "n_skus": args.skus,
        "n_customers": args.customers,
        "n_suppliers": args.suppliers,
        "history_years": args.years,
    }
    sizes = {k: v for k, v in sizes.items() if v is not None}
    cfg = SynthConfig.from_preset(args.preset)
    if args.seed is not None:
        cfg = replace(cfg, seed=args.seed)
    if sizes:
        cfg = replace(cfg, preset="custom", **sizes)
    print(f"Generating SYNTHETIC data (preset={cfg.preset}, seed={cfg.seed}) into {args.out}")
    started = perf_counter()
    try:
        manifest = write(generate(cfg), Path(args.out))
    except FileExistsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for name, entry in manifest["tables"].items():
        print(f"  {name:<28} {entry['rows']:>10,} rows")
    print(f"Done in {perf_counter() - started:.0f} s. All data is synthetic; see docs/DATA.md.")
    return 0


def _validate(args: argparse.Namespace) -> int:
    from stockpilot.synth.validate import validate_dataset

    report = validate_dataset(Path(args.data))
    for name, passed, detail in report.checks:
        mark = "PASS" if passed else "FAIL"
        print(f"[{mark}] {name}" + (f" ({detail})" if detail and not passed else ""))
    if report.stats:
        patterns, service = report.stats["patterns"], report.stats["service"]
        print(
            f"pattern mix on true demand: {patterns['true_demand']} (target {patterns['target']})"
        )
        print(f"pattern agreement: {patterns['agreement']}, fill rate: {service['fill_rate']}")
    print("Dataset is valid (synthetic data)." if report.ok else "Dataset is INVALID.")
    return 0 if report.ok else 1


def _docs_stats(args: argparse.Namespace) -> int:
    import json

    from stockpilot.synth.report import sync_docs

    manifest = json.loads((Path(args.data) / "manifest.json").read_text(encoding="utf-8"))
    changed = sync_docs(manifest, [Path(d) for d in args.docs], check=args.check)
    if args.check and changed:
        for entry in changed:
            print(f"out of date: {entry}", file=sys.stderr)
        print("Run `make docs-stats` after `make data` and commit the result.", file=sys.stderr)
        return 1
    print("Generated doc blocks are up to date." if not changed else f"Updated: {changed}")
    return 0
