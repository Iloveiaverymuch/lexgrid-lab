"""/ask: retrieve → abstain or assemble context → cited answer.

Generation uses an `Answerer`. The lab ships an extractive answerer (no LLM): it quotes the sentences of the
retrieved articles that best match the question, each with its citation id. A Bedrock answerer plugs into the
same interface once the account allows Bedrock (ADR-001, backlog #8). Never legal advice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from lexgrid.embed import tokens
from lexgrid.normalize import split_sentences
from lexgrid.retrieval.base import Filters, Mode
from lexgrid.retrieval.context import ContextPack, assemble
from lexgrid.retrieval.service import RetrievalService

DISCLAIMER = (
    "Information retrieved from public legal texts for research purposes. This is not legal advice; "
    "have it reviewed by a qualified legal professional."
)


@dataclass(frozen=True)
class AnswerLine:
    text: str
    citation_id: str


@dataclass
class AskResult:
    abstained: bool
    reason: str | None
    lines: list[AnswerLine]
    context: ContextPack | None
    top_score: float | None
    disclaimer: str = DISCLAIMER
    timings_ms: dict[str, float] = field(default_factory=dict)


class Answerer(Protocol):
    name: str

    def answer(self, question: str, context: ContextPack) -> list[AnswerLine]: ...


class ExtractiveAnswerer:
    name = "extractive"

    def __init__(self, max_lines: int = 4) -> None:
        self.max_lines = max_lines

    def answer(self, question: str, context: ContextPack) -> list[AnswerLine]:
        q = set(tokens(question))
        scored: list[tuple[float, int, AnswerLine]] = []
        for rank, item in enumerate(context.items):
            body = item.text.split("\n", 1)[-1]  # drop the "act > path > Article" header line
            best = max(
                split_sentences(body) or [body],
                key=lambda s: len(q & set(tokens(s))) / (len(set(tokens(s))) ** 0.5 or 1),
            )
            overlap = len(q & set(tokens(best)))
            scored.append((overlap - 0.5 * rank, rank, AnswerLine(best.strip(), item.citation_id)))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [line for _, _, line in scored[: self.max_lines]]


class AskService:
    def __init__(
        self,
        retrieval: RetrievalService,
        answerer: Answerer,
        *,
        mode: Mode = "hybrid_rrf_rerank",
        abstain_threshold: float | None = 0.15,
        k: int = 8,
        budget_tokens: int = 1500,
    ) -> None:
        self.retrieval = retrieval
        self.answerer = answerer
        self.mode = mode
        self.threshold = abstain_threshold
        self.k = k
        self.budget = budget_tokens

    def ask(self, question: str, jurisdictions: tuple[str, ...], as_of: date | None = None) -> AskResult:
        res = self.retrieval.search(question, Filters(jurisdictions, as_of=as_of), k=self.k, mode=self.mode)
        if not res.hits:
            return AskResult(
                True, "no source found in the entitled jurisdictions", [], None, None, timings_ms=res.timings_ms
            )
        top = res.hits[0].score
        # The threshold is calibrated on reranker scores only (evals/abstain sweep).
        if self.mode == "hybrid_rrf_rerank" and self.threshold is not None and top < self.threshold:
            reason = f"top reranked score {top:.3f} below threshold {self.threshold}: insufficient evidence"
            return AskResult(True, reason, [], None, top, timings_ms=res.timings_ms)
        pack = assemble(res.hits, budget_tokens=self.budget)
        return AskResult(False, None, self.answerer.answer(question, pack), pack, top, timings_ms=res.timings_ms)
