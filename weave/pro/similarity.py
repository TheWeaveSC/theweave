"""TF-IDF k-nearest-neighbour over vault notes — pure stdlib.

Used by the conflict resolver to find existing notes similar to a candidate
new note. ChromaDB / Ollama embeddings would be the production substitute;
this avoids any service dependency for the sandbox.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from ..vault import Note, Vault


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'_-]+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "at", "is", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "for", "with", "as", "by", "this", "that", "these", "those", "it",
    "its", "from", "but", "not", "no", "yes", "if", "so", "we", "you", "he",
    "she", "they", "them", "his", "her", "their", "our", "us", "i", "my",
}


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS and len(t) >= 3]


@dataclass
class Match:
    note: Note
    score: float


class TFIDFIndex:
    """Tiny corpus-level TF-IDF index over markdown notes."""

    def __init__(self, vault: Vault):
        self.vault = vault
        self.notes: list[Note] = []
        self._tf: list[Counter] = []
        self._df: Counter = Counter()
        self._n: int = 0
        self._idf: dict[str, float] = {}
        self._vectors: list[dict[str, float]] = []

    def build(self) -> "TFIDFIndex":
        self.notes = list(self.vault.iter_notes())
        self._n = len(self.notes)
        self._tf = []
        self._df = Counter()
        for n in self.notes:
            toks = _tokenize(n.content + " " + n.name)
            tf = Counter(toks)
            self._tf.append(tf)
            for term in set(toks):
                self._df[term] += 1
        # IDF with smoothing
        self._idf = {
            term: math.log((self._n + 1) / (df + 1)) + 1.0
            for term, df in self._df.items()
        }
        self._vectors = [self._vectorize(tf) for tf in self._tf]
        return self

    def _vectorize(self, tf: Counter) -> dict[str, float]:
        vec: dict[str, float] = {}
        for term, count in tf.items():
            if term in self._idf:
                vec[term] = (1 + math.log(count)) * self._idf[term]
        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {k: v / norm for k, v in vec.items()}

    def _vectorize_text(self, text: str) -> dict[str, float]:
        toks = _tokenize(text)
        return self._vectorize(Counter(toks))

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        # both are L2-normalised; cosine = dot product
        if len(a) > len(b):
            a, b = b, a
        return sum(v * b.get(k, 0.0) for k, v in a.items())

    def query(self, text: str, top_k: int = 5, exclude: set[str] | None = None) -> list[Match]:
        if self._n == 0:
            self.build()
        exclude = exclude or set()
        qvec = self._vectorize_text(text)
        ranked: list[tuple[float, int]] = []
        for i, doc in enumerate(self._vectors):
            if self.notes[i].rel_path in exclude:
                continue
            score = self._cosine(qvec, doc)
            ranked.append((score, i))
        ranked.sort(reverse=True)
        return [Match(self.notes[i], score) for score, i in ranked[:top_k] if score > 0]
