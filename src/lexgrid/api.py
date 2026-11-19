"""REST API. Same contract as the MCP server; scope always comes from the API key, never from the request.

Run: `LEXGRID_API_KEYS="dev-fr:FR;dev-all:EU,FR,DE" uv run lexgrid serve`
"""


from datetime import date
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from lexgrid.answer import AskService
from lexgrid.retrieval.base import Filters, Hit, Mode
from lexgrid.retrieval.service import RetrievalService
from lexgrid.runtime import entitlements
from lexgrid.store import LineageStore


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    k: int = Field(default=10, ge=1, le=20)
    mode: Mode = "hybrid_rrf"
    jurisdictions: list[str] | None = None
    as_of: date | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    jurisdictions: list[str] | None = None
    as_of: date | None = None


def hit_json(h: Hit) -> dict[str, Any]:
    return {
        "citation_id": h.citation_id,
        "chunk_id": h.chunk_id,
        "article_key": h.article_key,
        "jurisdiction": h.jurisdiction,
        "language": h.language,
        "path": h.chunk_path,
        "score": round(h.score, 6),
        "valid_from": h.valid_from.isoformat() if h.valid_from else None,
        "valid_to": h.valid_to.isoformat() if h.valid_to else None,
        "text": h.text,
    }


def resolve_scope(requested: list[str] | None, entitled: tuple[str, ...]) -> tuple[str, ...]:
    """Narrowing is allowed; widening is refused (403), never silently dropped."""
    if not requested:
        return entitled
    req = tuple(dict.fromkeys(j.upper() for j in requested))
    outside = [j for j in req if j not in entitled]
    if outside:
        raise HTTPException(status_code=403, detail=f"not entitled to: {', '.join(outside)}")
    return req


def create_app(
    retrieval: RetrievalService, ask: AskService, store: LineageStore, keys: dict[str, tuple[str, ...]]
) -> FastAPI:
    app = FastAPI(title="lexgrid-lab", version="0.3.0", description="Legal retrieval lab. Not legal advice.")

    def scope_of(x_api_key: Annotated[str | None, Header()] = None) -> tuple[str, ...]:
        scope = entitlements(keys, x_api_key)
        if scope is None:
            raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")
        return scope

    Scope = Annotated[tuple[str, ...], Depends(scope_of)]

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/search")
    def search(req: SearchRequest, entitled: Scope) -> dict[str, Any]:
        scope = resolve_scope(req.jurisdictions, entitled)
        res = retrieval.search(req.query, Filters(scope, as_of=req.as_of), k=req.k, mode=req.mode)
        return {
            "mode": res.mode,
            "scope": list(scope),
            "hits": [hit_json(h) for h in res.hits],
            "timings_ms": {k: round(v, 1) for k, v in res.timings_ms.items()},
        }

    @app.post("/ask")
    def ask_route(req: AskRequest, entitled: Scope) -> dict[str, Any]:
        scope = resolve_scope(req.jurisdictions, entitled)
        r = ask.ask(req.question, scope, as_of=req.as_of)
        return {
            "abstained": r.abstained,
            "reason": r.reason,
            "answer": [{"text": line.text, "citation_id": line.citation_id} for line in r.lines],
            "sources": [
                {"citation_id": i.citation_id, "chunk_id": i.chunk_id, "jurisdiction": i.jurisdiction}
                for i in (r.context.items if r.context else [])
            ],
            "top_score": r.top_score,
            "answerer": ask.answerer.name,
            "disclaimer": r.disclaimer,
        }

    @app.get("/lineage/{chunk_id}")
    def lineage(chunk_id: str, entitled: Scope) -> dict[str, Any]:
        row = store.lineage(chunk_id)
        if row is None or row["jurisdiction"] not in entitled:
            raise HTTPException(status_code=404, detail="chunk not found")  # 404, not 403: no existence leak
        return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}

    return app
