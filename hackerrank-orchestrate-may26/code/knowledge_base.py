"""
knowledge_base.py — loads the data/ help-doc corpus and provides deterministic
TF-IDF retrieval. This is the "evidence source" of the system: retrieved
passages are the support-ticket analog of the Vision Agent's VisualFacts.

Pure standard library (no numpy / external vector DB) so the build is
dependency-free, reproducible, and runs anywhere — a hackathon-appropriate
choice per TRD.md §4 ("SQLite or plain files ... no hosted DB needed").
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config import KB_NAMESPACES

# Lightweight English stopword list — enough to stop common words dominating
# TF-IDF without pulling in nltk.
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "for", "to", "of", "in",
    "on", "at", "by", "is", "are", "was", "were", "be", "been", "being", "do",
    "does", "did", "have", "has", "had", "i", "you", "we", "they", "it", "this",
    "that", "these", "those", "my", "your", "our", "their", "me", "us", "with",
    "as", "from", "how", "can", "please", "would", "could", "should", "will",
    "what", "when", "where", "which", "who", "why", "not", "no", "yes", "im",
    "am", "so", "there", "any", "out", "up", "about", "into", "than", "too",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumerics, drop stopwords and 1-char tokens."""
    return [
        t for t in _TOKEN_RE.findall(text.lower())
        if len(t) > 1 and t not in _STOPWORDS
    ]


def _parse_frontmatter_title(text: str) -> str | None:
    """Extract `title:` from YAML frontmatter, if present."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    fm = text[3:end]
    m = re.search(r'^title:\s*"?(.+?)"?\s*$', fm, re.MULTILINE)
    return m.group(1).strip() if m else None


def _parse_source_url(text: str) -> str:
    m = re.search(r'^source_url:\s*"?(.+?)"?\s*$', text[:600], re.MULTILINE)
    return m.group(1).strip() if m else ""


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text


@dataclass
class Document:
    doc_id: str          # path relative to data/ (stable id)
    namespace: str       # claude | hackerrank | visa
    title: str
    url: str
    body: str
    tokens: Counter      # term frequencies (body + title-weighted)


class KnowledgeBase:
    """In-memory TF-IDF index over the help-doc corpus."""

    def __init__(self) -> None:
        self.docs: list[Document] = []
        self.doc_freq: Counter = Counter()       # token -> #docs containing it
        self._idf: dict[str, float] = {}
        self._by_namespace: dict[str, list[int]] = defaultdict(list)
        self._loaded = False

    # ----------------------------------------------------------------- load #
    def load(self) -> "KnowledgeBase":
        if self._loaded:
            return self
        for namespace, root in KB_NAMESPACES.items():
            if not root.exists():
                continue
            for path in sorted(root.rglob("*.md")):
                raw = path.read_text(encoding="utf-8", errors="ignore")
                title = (
                    _parse_frontmatter_title(raw)
                    or _first_heading(raw)
                    or _slug_title(path)
                )
                body = _strip_frontmatter(raw)
                # Title terms count extra — they're the strongest topic signal.
                tf = Counter(tokenize(body) + tokenize(title) * 3)
                if not tf:
                    continue
                idx = len(self.docs)
                self.docs.append(
                    Document(
                        doc_id=str(path.relative_to(KB_NAMESPACES[namespace].parent.parent)),
                        namespace=namespace,
                        title=title,
                        url=_parse_source_url(raw),
                        body=body.strip(),
                        tokens=tf,
                    )
                )
                self._by_namespace[namespace].append(idx)
                for term in tf:
                    self.doc_freq[term] += 1

        n = max(1, len(self.docs))
        self._idf = {
            term: math.log((n + 1) / (df + 1)) + 1.0
            for term, df in self.doc_freq.items()
        }
        self._loaded = True
        return self

    # ------------------------------------------------------------- retrieve #
    def _doc_vector_norm(self, doc: Document) -> float:
        return math.sqrt(
            sum((tf * self._idf.get(t, 0.0)) ** 2 for t, tf in doc.tokens.items())
        ) or 1.0

    @lru_cache(maxsize=2048)
    def _norm_cached(self, idx: int) -> float:
        return self._doc_vector_norm(self.docs[idx])

    def search(
        self, query: str, namespace: str | None = None, top_k: int = 5
    ) -> list[tuple[Document, float]]:
        """Return up to `top_k` (Document, cosine_score) pairs, score in 0..1.

        If `namespace` is given and known, search only that namespace; otherwise
        search the whole corpus. Deterministic: ties broken by doc_id.
        """
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        q_tf = Counter(q_tokens)
        q_weights = {t: tf * self._idf.get(t, 0.0) for t, tf in q_tf.items()}
        q_norm = math.sqrt(sum(w * w for w in q_weights.values())) or 1.0

        candidate_idxs = (
            self._by_namespace.get(namespace)
            if namespace in self._by_namespace
            else range(len(self.docs))
        )

        scored: list[tuple[float, str, int]] = []
        for idx in candidate_idxs:
            doc = self.docs[idx]
            dot = 0.0
            for t, qw in q_weights.items():
                tf = doc.tokens.get(t)
                if tf:
                    dot += qw * tf * self._idf.get(t, 0.0)
            if dot <= 0:
                continue
            cos = dot / (q_norm * self._norm_cached(idx))
            scored.append((cos, doc.doc_id, idx))

        # sort by score desc, then doc_id asc for stable/deterministic ordering
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [(self.docs[idx], score) for score, _, idx in scored[:top_k]]


def _first_heading(text: str) -> str | None:
    m = re.search(r"^#\s+(.+)$", _strip_frontmatter(text), re.MULTILINE)
    return m.group(1).strip() if m else None


def _slug_title(path: Path) -> str:
    name = path.stem
    name = re.sub(r"^\d+-", "", name)          # drop leading article-id
    return name.replace("-", " ").strip().capitalize()


def best_snippet(doc: Document, query: str, max_chars: int = 320) -> str:
    """Pick the most query-relevant paragraph of a doc for grounding/citation."""
    q = set(tokenize(query))
    paragraphs = [
        p.strip() for p in re.split(r"\n\s*\n", doc.body)
        if p.strip() and not p.strip().startswith(("#", "_", "-", "|"))
    ]
    if not paragraphs:
        paragraphs = [doc.body[:max_chars]]
    best, best_overlap = paragraphs[0], -1
    for p in paragraphs:
        overlap = len(q & set(tokenize(p)))
        if overlap > best_overlap:
            best, best_overlap = p, overlap
    snippet = re.sub(r"\s+", " ", best).strip()
    return snippet[:max_chars]
