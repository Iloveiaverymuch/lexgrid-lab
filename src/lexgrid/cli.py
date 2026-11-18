"""CLI: `lexgrid sources check | fixtures pin | ingest | lineage`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from lexgrid.parsers import PARSERS
from lexgrid.pipeline import ingest
from lexgrid.registry import check_fixtures, load_registry, pin_fixture
from lexgrid.store import LineageStore

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "data" / "sources.yaml"
FIXTURES = ROOT / "data" / "fixtures"
DEFAULT_DB = os.environ.get("LEXGRID_DB", f"sqlite:///{ROOT / 'var' / 'lexgrid.db'}")


def _sources() -> list:  # type: ignore[type-arg]
    return load_registry(REGISTRY, set(PARSERS))


def cmd_sources_check(args: argparse.Namespace) -> int:
    sources = _sources()
    errors = check_fixtures(sources, FIXTURES, require_files=args.require_fixtures)
    for e in errors:
        print(f"ERROR {e}")
    print(f"{len(sources)} sources, {len(errors)} problems")
    return 1 if errors else 0


def cmd_fixtures_pin(args: argparse.Namespace) -> int:
    source = next((s for s in _sources() if s.id == args.source), None)
    if source is None:
        print(f"unknown source {args.source}")
        return 2
    entry = pin_fixture(
        source=source, fixtures_root=FIXTURES, file=Path(args.file), language=args.lang, url=args.url
    )
    print(json.dumps(entry.model_dump(mode="json"), indent=2))
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    store = None
    if not args.dry_run:
        (ROOT / "var").mkdir(exist_ok=True)
        store = LineageStore.from_url(args.db)
    reports = ingest(_sources(), FIXTURES, store, dry_run=args.dry_run)
    print(json.dumps([asdict(r) for r in reports], indent=2))
    if store is not None:
        print(json.dumps(store.counts()))
    return 0


def cmd_lineage(args: argparse.Namespace) -> int:
    row = LineageStore.from_url(args.db).lineage(args.chunk_id)
    print(json.dumps(row, indent=2, default=str) if row else "not found")
    return 0 if row else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="lexgrid")
    sub = p.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("sources").add_subparsers(dest="sub", required=True).add_parser("check")
    sc.add_argument("--require-fixtures", action="store_true")
    sc.set_defaults(func=cmd_sources_check)

    fp = sub.add_parser("fixtures").add_subparsers(dest="sub", required=True).add_parser("pin")
    fp.add_argument("--source", required=True)
    fp.add_argument("--lang", required=True)
    fp.add_argument("--file", required=True)
    fp.add_argument("--url")
    fp.set_defaults(func=cmd_fixtures_pin)

    ig = sub.add_parser("ingest")
    ig.add_argument("--db", default=DEFAULT_DB)
    ig.add_argument("--dry-run", action="store_true")
    ig.set_defaults(func=cmd_ingest)

    ln = sub.add_parser("lineage")
    ln.add_argument("chunk_id")
    ln.add_argument("--db", default=DEFAULT_DB)
    ln.set_defaults(func=cmd_lineage)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
