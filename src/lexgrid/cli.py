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
    entry = pin_fixture(source=source, fixtures_root=FIXTURES, file=Path(args.file), language=args.lang, url=args.url)
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
            print(f"{j} {r['status']:<11} {r['index_name']} chunks={r['n_chunks']} models={r['embedding_model']}")
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
        backend = MemoryBackend(chunks, {f"vec_{emb.name}": emb.embed([c["text"] for c in chunks], "passage")})
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


# ---------------------------------------------------------------- Day 3: gate / abstention / serving
def cmd_index_release(args: argparse.Namespace) -> int:
    from lexgrid.evals.runner import load_golden
    from lexgrid.gate import release
    from lexgrid.retrieval.opensearch import make_client
    from lexgrid.retrieval.rerank import build_reranker

    embedders = [_embedder(m, args.aws_profile) for m in args.models.split(",")]
    gate_emb = next((e for e in embedders if e.name == args.gate_embedder.replace("-", "")), None)
    if gate_emb is None:
        print(f"--gate-embedder {args.gate_embedder} must be one of --models")
        return 2
    reranker = build_reranker(args.reranker) if args.gate_mode == "hybrid_rrf_rerank" else None
    decision, built = release(
        client=make_client(args.opensearch),
        store=_store(args),
        jurisdictions=JURISDICTIONS,
        embedders=embedders,
        gate_embedder=gate_emb,
        golden=load_golden(Path(args.golden)),
        mode=args.gate_mode,
        reranker=reranker,
        tolerance=args.tolerance,
        drop_fraction=args.drop_fraction,
    )
    print(json.dumps({"built": built, "promoted": decision.promote, "reason": decision.reason}, indent=2))
    if decision.diff is not None:
        print(f"paired diff {decision.diff:+.3f} [{decision.ci_low:+.3f}, {decision.ci_high:+.3f}]")
    return 0 if decision.promote else 3


def cmd_abstain_sweep(args: argparse.Namespace) -> int:
    from lexgrid.evals.abstain import choose, sweep
    from lexgrid.evals.runner import load_golden

    run = json.loads(Path(args.results).read_text(encoding="utf-8"))
    pq = run["per_query"][args.mode]
    no_answer = {q.id for q in load_golden(Path(args.golden)) if q.type == "no_answer"}
    missing = no_answer - set(pq["top_score"])
    if missing:
        print(f"results file lacks no-answer queries {sorted(missing)}: rerun the eval with the current golden set")
        return 2
    hit1 = {q: m["hit@1"] for q, m in pq["metrics"].items()}
    thresholds = [round(x * 0.01, 2) for x in range(0, 61)]
    rows = sweep(pq["top_score"], no_answer, hit1, thresholds)
    print("| t | no-answer abstained | answerable answered | answered hit@1 |\n|---|---|---|---|")
    for r in rows[::5]:
        print(
            f"| {r.threshold:.2f} | {r.no_answer_abstain:.2f} | {r.answerable_answered:.2f} | {r.answered_hit1:.2f} |"
        )
    best = choose(rows)
    n_na, n_ans = len(no_answer), len(pq["top_score"]) - len(no_answer)
    print(
        f"chosen t={best.threshold:.2f}: abstains on {best.no_answer_abstain:.0%} of {n_na} no-answer, "
        f"answers {best.answerable_answered:.0%} of {n_ans} answerable, hit@1 when answering {best.answered_hit1:.0%}"
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from lexgrid.api import create_app
    from lexgrid.runtime import Settings, build_runtime

    settings = Settings.from_env()
    if not settings.api_keys:
        print("set LEXGRID_API_KEYS, e.g. 'dev-fr:FR;dev-all:EU,FR,DE'")
        return 2
    rt = build_runtime(settings)
    app = create_app(rt.retrieval, rt.ask, rt.store, settings.api_keys, results_dir=ROOT / "evals" / "results")
    print(f"UI: http://{args.host}:{args.port}/")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from lexgrid.mcp_server import LegalTools, create_mcp
    from lexgrid.runtime import Settings, build_runtime, entitlements

    settings = Settings.from_env()
    scope = entitlements(settings.api_keys, os.environ.get("LEXGRID_MCP_KEY"))
    if scope is None:
        print("set LEXGRID_MCP_KEY to a key listed in LEXGRID_API_KEYS", file=sys.stderr)
        return 2
    rt = build_runtime(settings)
    create_mcp(LegalTools(rt.retrieval, rt.store, scope)).run("stdio")
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
    b.add_argument("--models", default="bge-m3,e5")
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

    rl = ix.add_parser("release", help="build candidates, gate on the golden set, promote all or reject")
    rl.add_argument("--models", default="bge-m3,e5")
    rl.add_argument("--gate-embedder", default="bge-m3")
    rl.add_argument("--gate-mode", default="hybrid_rrf", choices=["bm25", "dense", "hybrid_rrf", "hybrid_rrf_rerank"])
    rl.add_argument("--reranker", default="bge-m3", choices=["overlap", "bge-m3", "mminilm"])
    rl.add_argument("--tolerance", type=float, default=0.02)
    rl.add_argument("--drop-fraction", type=float, default=0.0, help="fault injection: build from a random subset")
    rl.add_argument("--golden", default=str(ROOT / "evals" / "golden" / "golden_v1.yaml"))
    common(rl)
    rl.set_defaults(func=cmd_index_release)

    sw = sub.add_parser("abstain-sweep", help="choose the /ask no-answer threshold from an eval results file")
    sw.add_argument("--results", required=True)
    sw.add_argument("--mode", default="hybrid_rrf_rerank")
    sw.add_argument("--golden", default=str(ROOT / "evals" / "golden" / "golden_v1.yaml"))
    sw.set_defaults(func=cmd_abstain_sweep)

    sv = sub.add_parser("serve", help="REST API (/search, /ask, /lineage)")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(func=cmd_serve)

    mc = sub.add_parser("mcp", help="MCP server over stdio")
    mc.set_defaults(func=cmd_mcp)

    ev = sub.add_parser("eval")
    ev.add_argument("--backend", default="opensearch", choices=["memory", "opensearch"])
    ev.add_argument("--embedder", default="bge-m3", choices=["hash", "e5", "bge-m3", "titan"])
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
