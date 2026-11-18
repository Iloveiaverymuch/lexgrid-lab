"""Embedders behind one interface + a persistent cache (never pay twice for the same text).

- HashEmbedder: deterministic bag-of-words hashing. Offline tests and CI only; not a quality baseline.
- SentenceTransformerEmbedder: local multilingual model (default intfloat/multilingual-e5-base).
- BedrockTitanEmbedder: Amazon Titan Text Embeddings V2 on Bedrock (live, explicit opt-in).
Heavy dependencies are imported lazily so the offline gate never needs torch or boto3.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import unicodedata
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal, Protocol

import numpy as np
import numpy.typing as npt

Kind = Literal["query", "passage"]
Matrix = npt.NDArray[np.float32]


class Embedder(Protocol):
    name: str  # stable id used in index field names and caches, e.g. "e5", "titan"
    model_id: str
    dim: int

    def embed(self, texts: Sequence[str], kind: Kind) -> Matrix: ...


def _l2(m: Matrix) -> Matrix:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (m / norms).astype(np.float32)


_TOKEN = re.compile(r"\w+", re.UNICODE)


def fold(text: str) -> str:
    """Lowercase + strip accents: 'Rétractation' -> 'retractation'."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(fold(text))


class HashEmbedder:
    name = "hash"
    model_id = "hash-bow-v1"

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, texts: Sequence[str], kind: Kind) -> Matrix:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for tok in tokens(t):
                h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "little")
                out[i, h % self.dim] += 1.0
        return _l2(out)


class SentenceTransformerEmbedder:
    """E5-family models need 'query: ' / 'passage: ' prefixes; we add them here, once."""

    def __init__(
        self, model_id: str = "intfloat/multilingual-e5-base", name: str = "e5", batch_size: int = 32
    ):
        from sentence_transformers import SentenceTransformer  # lazy: heavy

        self.name = name
        self.model_id = model_id
        self._model = SentenceTransformer(model_id)
        get_dim = (
            getattr(self._model, "get_embedding_dimension", None)
            or self._model.get_sentence_embedding_dimension
        )
        self.dim = int(get_dim() or 0)
        self._batch = batch_size
        self._e5 = "e5" in model_id.lower()

    def embed(self, texts: Sequence[str], kind: Kind) -> Matrix:
        prefixed = [f"{kind}: {t}" for t in texts] if self._e5 else list(texts)
        vecs = self._model.encode(
            prefixed, batch_size=self._batch, normalize_embeddings=True, show_progress_bar=len(texts) > 200
        )
        return np.asarray(vecs, dtype=np.float32)


class BedrockTitanEmbedder:
    def __init__(
        self,
        *,
        region: str = "eu-central-1",
        profile: str | None = None,
        model_id: str = "amazon.titan-embed-text-v2:0",
        dim: int = 1024,
        max_workers: int = 4,
    ) -> None:
        import boto3  # lazy
        from botocore.config import Config

        session = boto3.Session(profile_name=profile, region_name=region)
        self._client: Any = session.client(
            "bedrock-runtime", config=Config(retries={"mode": "adaptive", "max_attempts": 8})
        )
        self.name = "titan"
        self.model_id = model_id
        self.dim = dim
        self._workers = max_workers

    def _one(self, text: str) -> list[float]:
        body = json.dumps({"inputText": text, "dimensions": self.dim, "normalize": True})
        resp = self._client.invoke_model(modelId=self.model_id, body=body, contentType="application/json")
        payload = json.loads(resp["body"].read())
        return list(payload["embedding"])

    def embed(self, texts: Sequence[str], kind: Kind) -> Matrix:
        # Titan V2 has no query/passage distinction; one request per text.
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            vecs = list(pool.map(self._one, texts))
        return np.asarray(vecs, dtype=np.float32)


class EmbeddingCache:
    """SQLite cache keyed by (model_id, kind, sha256(text)). One connection, guarded by its own lock."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS emb (model TEXT, kind TEXT, sha TEXT, dim INT, vec BLOB,"
            " PRIMARY KEY (model, kind, sha))"
        )

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @staticmethod
    def _sha(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def get_many(self, model: str, kind: Kind, texts: Sequence[str]) -> dict[str, Matrix]:
        shas = [self._sha(t) for t in texts]
        found: dict[str, Matrix] = {}
        with self._lock:
            for i in range(0, len(shas), 500):
                chunk = shas[i : i + 500]
                q = ",".join("?" * len(chunk))
                rows = self._db.execute(
                    f"SELECT sha, vec FROM emb WHERE model=? AND kind=? AND sha IN ({q})",
                    [model, kind, *chunk],
                ).fetchall()
                for sha, blob in rows:
                    found[sha] = np.frombuffer(blob, dtype=np.float32)
        return found

    def put_many(self, model: str, kind: Kind, texts: Sequence[str], vecs: Matrix) -> None:
        rows = [
            (model, kind, self._sha(t), int(v.shape[0]), v.astype(np.float32).tobytes())
            for t, v in zip(texts, vecs, strict=True)
        ]
        with self._lock:
            self._db.executemany("INSERT OR IGNORE INTO emb VALUES (?,?,?,?,?)", rows)
            self._db.commit()


class CachedEmbedder:
    """Wraps any Embedder; only cache misses reach the model (and the bill)."""

    def __init__(self, inner: Embedder, cache: EmbeddingCache) -> None:
        self.inner = inner
        self.cache = cache
        self.name = inner.name
        self.model_id = inner.model_id
        self.dim = inner.dim
        self.misses = 0

    def embed(self, texts: Sequence[str], kind: Kind) -> Matrix:
        hits = self.cache.get_many(self.model_id, kind, texts)
        shas = [EmbeddingCache._sha(t) for t in texts]
        missing = [t for t, s in zip(texts, shas, strict=True) if s not in hits]
        if missing:
            unique = list(dict.fromkeys(missing))
            vecs = self.inner.embed(unique, kind)
            self.cache.put_many(self.model_id, kind, unique, vecs)
            self.misses += len(unique)
            hits.update({EmbeddingCache._sha(t): v for t, v in zip(unique, vecs, strict=True)})
        return (
            np.stack([hits[s] for s in shas]).astype(np.float32)
            if texts
            else np.zeros((0, self.dim), np.float32)
        )


def build_embedder(name: str, *, cache_dir: Path | None = None, profile: str | None = None) -> Embedder:
    inner: Embedder
    if name == "hash":
        inner = HashEmbedder()
    elif name == "e5":
        inner = SentenceTransformerEmbedder()
    elif name == "bge-m3":
        inner = SentenceTransformerEmbedder("BAAI/bge-m3", name="bgem3", batch_size=16)
    elif name == "titan":
        inner = BedrockTitanEmbedder(profile=profile)
    else:
        raise ValueError(f"unknown embedder {name!r} (hash | e5 | bge-m3 | titan)")
    if cache_dir is None:
        return inner
    return CachedEmbedder(inner, EmbeddingCache(cache_dir / "embeddings.sqlite"))
