"""Embedding providers for the cortex dense index (W2).

OllamaEmbedder is THE production path (LD #3: nomic-embed-text, 768d,
verified deterministic on the reference machine). FakeEmbedder is the offline test dial —
deterministic sha-seeded vectors so I1 rebuild tests run with no Ollama and
no network. Both are pure functions of their input text.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request

import numpy as np

from .cortex import EMBED_DIMS, EMBED_MODEL


class EmbedderError(RuntimeError):
    """Embedding backend unreachable/failed — degrade loudly, never silently."""


class OllamaEmbedder:
    name = EMBED_MODEL

    def __init__(self, model: str = EMBED_MODEL,
                 url: str = "http://localhost:11434", timeout: int = 120):
        self.model = model
        self.url = url.rstrip("/")
        self.timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        body = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.url}/api/embed", body, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.load(resp)
        except OSError as e:
            raise EmbedderError(
                f"Ollama embed failed ({self.url}, model {self.model}): {e}. "
                "Is Ollama running? `ollama pull nomic-embed-text`") from e
        embs = data.get("embeddings")
        if not embs or len(embs) != len(texts):
            raise EmbedderError(f"Ollama returned {len(embs or [])} embeddings "
                                f"for {len(texts)} inputs")
        return embs


class FakeEmbedder:
    """Deterministic offline embedder for tests. sha256-seeded MT19937 —
    stable across runs, machines, and numpy versions. No semantics; unit
    tests assert MECHANICS, the real A/B uses Ollama."""

    name = "fake-sha"

    def __init__(self, dims: int = EMBED_DIMS):
        self.dims = dims
        self.calls = 0  # incremental-rebuild tests count embed invocations

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            self.calls += 1
            seed = int.from_bytes(hashlib.sha256(t.encode("utf-8")).digest()[:4], "big")
            v = np.random.RandomState(seed).standard_normal(self.dims)
            v /= np.linalg.norm(v)
            out.append([float(x) for x in v])
        return out


def default_embedder():
    return OllamaEmbedder()


__all__ = ["OllamaEmbedder", "FakeEmbedder", "EmbedderError", "default_embedder"]
