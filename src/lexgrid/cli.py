"""CLI: `lexgrid sources check | fixtures pin | ingest | lineage`."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

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


# ---------------------------------------------------------------- Day 2: embed / index / eval
VAR = ROOT / "var"
JURISDICTIONS = ("EU", "FR", "DE")


def _store(args: argparse.Namespace) -> LineageStore:
    VAR.mkdir(exist_ok=True)
    return LineageStore.from_url(args.db)


def _embedder(name: str, profile: str | None) -> Any:
    from lexgrid.embed import build_embedder

    return build_embedder(name, cache_dir=VAR, profile=profile)


def cmd_embed(args: argparse.Namespace) -> int:
    chunks = _store(args).live_chunks()
    emb = _embedder(args.model, args.aws_profile)
    start = time.perf_counter()
    mat = emb.embed([c["text"] for c in chunks], "passage")
    took = time.perf_counter() - start
    tokens = sum(c["token_count"] for c in chunks)
    print(
        json.dumps(
            {
                "model": emb.model_id,
                "chunks": len(chunks),
                "dim": int(mat.shape[1]),
                "cache_misses_embedded": getattr(emb, "misses", None),
                "seconds": round(took, 1),
                "est_tokens": tokens,
            }
        )
    )
    return 0


def _vectors(
    chunks: list[dict[str, Any]], models: list[str], profile: str | None
) -> tuple[dict[str, Any], dict[str, str]]:
    vecs: dict[str, Any] = {}
    ids: dict[str, str] = {}
    for m in models:
        emb = _embedder(m, profile)
        vecs[emb.name] = emb.embed([c["text"] for c in chunks], "passage")
        ids[emb.name] = emb.model_id
    return vecs, ids


def cmd_index_build(args: argparse.Namespace) -> int:
    from lexgrid.retrieval.opensearch import IndexManager, make_client

    store = _store(args)
    mgr = IndexManager(make_client(args.opensearch), store)
    jurs = JURISDICTIONS if args.jurisdiction == "all" else (args.jurisdiction,)
    for j in jurs:
        chunks = store.live_chunks(j)
        vecs, ids = _vectors(chunks, args.models.split(","), args.aws_profile)
        index = mgr.build(j, chunks, vecs, ids)
        print(f"built {index} ({len(chunks)} chunks)")
        if args.promote:
            old = mgr.promote(j, index)
            print(f"promoted {index} (previous: {old})")
    return 0


def cmd_index_promote(args: argparse.Namespace) -> int:
    from lexgrid.retrieval.opensearch import IndexManager, make_client

    old = IndexManager(make_client(args.opensearch), _store(args)).promote(args.jurisdiction, args.index)
    print(f"promoted {args.index} (previous: {old})")
    return 0


def cmd_index_rollback(args: argparse.Namespace) -> int:
    from lexgrid.retrieval.opensearch import IndexManager, make_client

    target = IndexManager(make_client(args.opensearch), _store(args)).rollback(args.jurisdiction)
    print(f"rolled back {args.jurisdiction} to {target}")
    return 0


def cmd_index_status(args: argparse.Namespace) -> int:
    store = _store(args)
    for j in JURISDICTIONS:
        for r in store.index_runs(j):
            print(
                f"{j} {r['status']:<11} {r['index_name']} "
                f"chunks={r['n_chunks']} models={r['embedding_model']}"
            )
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from lexgrid.evals.runner import (
        findings_row,
        load_golden,
        markdown_table,
        run_mode,
        summarize,
        write_results,
    )
    from lexgrid.retrieval.base import MODES, Mode
    from lexgrid.retrieval.rerank import build_reranker
    from lexgrid.retrieval.service import RetrievalService

    queries = load_golden(Path(args.golden))
    emb = _embedder(args.embedder, args.aws_profile)
    modes: list[Mode] = [m for m in MODES if m in args.modes.split(",")] if args.modes else list(MODES)
    reranker = build_reranker(args.reranker) if "hybrid_rrf_rerank" in modes else None
    backend: Any
    if args.backend == "memory":
        from lexgrid.retrieval.memory import MemoryBackend

        chunks = _store(args).live_chunks()
        backend = MemoryBackend(
            chunks, {f"vec_{emb.name}": emb.embed([c["text"] for c in chunks], "passage")}
        )
    else:
        from lexgrid.retrieval.opensearch import OpenSearchBackend, make_client

        backend = OpenSearchBackend(make_client(args.opensearch))
    service = RetrievalService(backend, emb, reranker, candidates=args.candidates, rerank_top=args.rerank_top)
    if args.warmup:
        for m in modes:  # load models / JIT once so latency numbers are steady-state
            run_mode(service, queries[:2], m)
    results = [run_mode(service, queries, m) for m in modes]
    summary = summarize(results, queries, baseline="bm25" if "bm25" in modes else None)
    run_id = args.run_id or f"EVAL-{time.strftime('%Y%m%d-%H%M%S')}"
    config = {
        "backend": args.backend,
        "embedder": emb.model_id,
        "reranker": getattr(reranker, "model_id", getattr(reranker, "name", None)),
        "modes": modes,
        "candidates": args.candidates,
        "rerank_top": args.rerank_top,
        "golden": args.golden,
    }
    path = write_results(ROOT / "evals" / "results", run_id, config, results, summary)
    print(markdown_table(summary))
    for name, comp in summary.get("comparisons", {}).items():
        pb = comp["ndcg@10_paired_bootstrap"]
        mc = comp["hit@5_mcnemar"]
        print(
            f"{name}: dNDCG@10={pb['diff']:+.3f} [{pb['ci_low']:+.2f}, {pb['ci_high']:+.2f}] "
            f"p={pb['p']:.3f}; "
            f"hit@5 McNemar n01={mc['n01']} n10={mc['n10']} p={mc['p']:.3f}"
        )
    print(f"results: {path.relative_to(ROOT)}")
    if args.record:
        cfg = f"{args.backend}, {emb.model_id}, rerank={config['reranker']}, golden v1"
        row = findings_row(run_id, cfg, summary, args.record)
        with (ROOT / "evals" / "FINDINGS.md").open("a", encoding="utf-8") as fh:
            fh.write(row)
        print("FINDINGS row appended")
    return 0


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

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--db", default=DEFAULT_DB)
        sp.add_argument("--aws-profile", default=os.environ.get("AWS_PROFILE"))
        sp.add_argument("--opensearch", default=os.environ.get("OPENSEARCH_URL", "http://localhost:9200"))

    em = sub.add_parser("embed", help="embed all live chunks into the cache (titan = paid, explicit)")
    em.add_argument("--model", required=True, choices=["hash", "e5", "bge-m3", "titan"])
    common(em)
    em.set_defaults(func=cmd_embed)

    ix = sub.add_parser("index").add_subparsers(dest="sub", required=True)
    b = ix.add_parser("build")
    b.add_argument("--jurisdiction", default="all", choices=["all", *JURISDICTIONS])
    b.add_argument("--models", default="e5")
    b.add_argument("--promote", action="store_true")
    common(b)
    b.set_defaults(func=cmd_index_build)
    pr = ix.add_parser("promote")
    pr.add_argument("--jurisdiction", required=True, choices=JURISDICTIONS)
    pr.add_argument("--index", required=True)
    common(pr)
    pr.set_defaults(func=cmd_index_promote)
    rb = ix.add_parser("rollback")
    rb.add_argument("--jurisdiction", required=True, choices=JURISDICTIONS)
    common(rb)
    rb.set_defaults(func=cmd_index_rollback)
    st = ix.add_parser("status")
    common(st)
    st.set_defaults(func=cmd_index_status)

    ev = sub.add_parser("eval")
    ev.add_argument("--backend", default="opensearch", choices=["memory", "opensearch"])
    ev.add_argument("--embedder", default="e5", choices=["hash", "e5", "bge-m3", "titan"])
    ev.add_argument("--reranker", default="bge-m3", choices=["overlap", "bge-m3", "mminilm"])
    ev.add_argument("--modes", default="")
    ev.add_argument("--golden", default=str(ROOT / "evals" / "golden" / "golden_v1.yaml"))
    ev.add_argument("--candidates", type=int, default=50)
    ev.add_argument("--rerank-top", type=int, default=30)
    ev.add_argument("--run-id")
    ev.add_argument("--warmup", action="store_true")
    ev.add_argument("--record", metavar="CONCLUSION", help="append a FINDINGS row with this conclusion")
    common(ev)
    ev.set_defaults(func=cmd_eval)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
