"""
knowledge_base.py — loads the data/ help-doc corpus and provides deterministic
BM25 retrieval. Retrieved passages are the "evidence" of the system (the
support-ticket analog of the Vision Agent's VisualFacts in the design docs).

Retrieval is BM25 (Okapi) over light-stemmed unigrams + bigrams, with a title
boost. BM25 handles term saturation and document-length normalization far
better than plain TF-IDF cosine for short keyword queries like support tickets.
Scores are normalized to 0..1 (fraction of the per-query ideal) so the coverage
thresholds in config.py are comparable across tickets.

Pure standard library (no numpy / vector DB): dependency-free, deterministic,
and reproducible — a hackathon-appropriate choice per TRD.md §4.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from config import KB_NAMESPACES

# BM25 hyperparameters (Okapi defaults).
_BM25_K1 = 1.5
_BM25_B = 0.75
_TITLE_BOOST = 3          # title tokens are repeated this many times in the doc

# Lightweight English stopword list — enough to stop common words dominating
# retrieval without pulling in nltk.
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "for", "to", "of", "in",
    "on", "at", "by", "is", "are", "was", "were", "be", "been", "being", "do",
    "does", "did", "have", "has", "had", "i", "you", "we", "they", "it", "this",
    "that", "these", "those", "my", "your", "our", "their", "me", "us", "with",
    "as", "from", "how", "can", "please", "would", "could", "should", "will",
    "what", "when", "where", "which", "who", "why", "not", "no", "yes", "im",
    "am", "so", "there", "any", "out", "up", "about", "into", "than", "too",
    "i'm", "i've", "we've", "want", "need", "get", "got", "use", "using", "help",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _stem(tok: str) -> str:
    """Light, consistent suffix stripping so morphological variants align:
    'submissions'->'submission', 'interviewers'->'interviewer', and crucially
    'remove'/'removing'->'remov', 'challenge'/'challenges'->'challeng'.
    Not a full Porter stemmer — conservative, but consistent between the base
    form and its inflections (which is what matters for matching)."""
    if len(tok) <= 3:
        return tok
    if tok.endswith("ings"):
        tok = tok[:-4]
    elif tok.endswith("ing") and len(tok) > 5:
        tok = tok[:-3]
    elif tok.endswith("ies") and len(tok) > 4:
        tok = tok[:-3] + "y"
    else:
        for suf in ("es", "ed", "s"):
            if tok.endswith(suf) and len(tok) - len(suf) >= 3 and not tok.endswith("ss"):
                tok = tok[: -len(suf)]
                break
    # Collapse a trailing silent 'e' so base/gerund forms converge
    # (remove -> remov, manage/managing -> manag).
    if len(tok) > 4 and tok.endswith("e"):
        tok = tok[:-1]
    return tok


def tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumerics, drop stopwords/1-char, light-stem."""
    return [
        _stem(t) for t in _TOKEN_RE.findall(text.lower())
        if len(t) > 1 and t not in _STOPWORDS
    ]


def terms(tokens: list[str]) -> list[str]:
    """Indexable terms. Currently light-stemmed unigrams; bigrams were tried and
    removed (they added more noise than signal on this short-query corpus)."""
    return list(tokens)


# --------------------------------------------------------------------- parse #
def _fm_field(text: str, name: str) -> str | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    m = re.search(rf'^{name}:\s*"?(.+?)"?\s*$', text[3:end], re.MULTILINE)
    return m.group(1).strip() if m else None


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text


def _first_heading(text: str) -> str | None:
    m = re.search(r"^#\s+(.+)$", _strip_frontmatter(text), re.MULTILINE)
    return m.group(1).strip() if m else None


def _slug_title(path: Path) -> str:
    name = re.sub(r"^\d+-", "", path.stem)
    return name.replace("-", " ").strip().capitalize()


@dataclass
class Document:
    doc_id: str
    namespace: str
    title: str
    url: str
    body: str
    tf: Counter = field(default_factory=Counter)   # term -> frequency
    length: int = 0                                 # total terms (for BM25)


class KnowledgeBase:
    """In-memory BM25 index over the help-doc corpus."""

    def __init__(self) -> None:
        self.docs: list[Document] = []
        self.doc_freq: Counter = Counter()
        self._idf: dict[str, float] = {}
        self._avgdl: float = 0.0
        self._by_namespace: dict[str, list[int]] = defaultdict(list)
        self._loaded = False

    # ----------------------------------------------------------------- load #
    def load(self) -> "KnowledgeBase":
        if self._loaded:
            return self
        for namespace, root in KB_NAMESPACES.items():
            if not root.exists():
                continue
            corpus_root = root.parent  # data/
            for path in sorted(root.rglob("*.md")):
                try:
                    raw = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue  # e.g. Windows long-path; skip gracefully
                title = _fm_field(raw, "title") or _first_heading(raw) or _slug_title(path)
                body = _strip_frontmatter(raw)
                toks = tokenize(body) + tokenize(title) * _TITLE_BOOST
                tf = Counter(terms(toks))
                if not tf:
                    continue
                idx = len(self.docs)
                self.docs.append(Document(
                    doc_id=str(path.relative_to(corpus_root)),
                    namespace=namespace,
                    title=title,
                    url=_fm_field(raw, "source_url") or "",
                    body=body.strip(),
                    tf=tf,
                    length=sum(tf.values()),
                ))
                self._by_namespace[namespace].append(idx)
                for term in tf:
                    self.doc_freq[term] += 1

        n = max(1, len(self.docs))
        # BM25 idf (always positive form).
        self._idf = {
            term: math.log(1 + (n - df + 0.5) / (df + 0.5))
            for term, df in self.doc_freq.items()
        }
        self._avgdl = (sum(d.length for d in self.docs) / n) or 1.0
        self._loaded = True
        return self

    # ------------------------------------------------------------- retrieve #
    def search(
        self, query: str, namespace: str | None = None, top_k: int = 5
    ) -> list[tuple[Document, float]]:
        """Return up to `top_k` (Document, score) pairs, score normalized to
        0..1. If `namespace` is known, restrict to it; else search the corpus.
        Deterministic: ties broken by doc_id."""
        q_terms = list(dict.fromkeys(terms(tokenize(query))))  # distinct, ordered
        q_terms = [t for t in q_terms if t in self._idf]
        if not q_terms:
            return []
        # Per-query ideal (tf->inf, len->0) used to normalize into 0..1.
        ideal = sum(self._idf[t] * (_BM25_K1 + 1) for t in q_terms) or 1.0

        candidates = (
            self._by_namespace.get(namespace)
            if namespace in self._by_namespace
            else range(len(self.docs))
        )

        scored: list[tuple[float, str, int]] = []
        for idx in candidates:
            doc = self.docs[idx]
            s = 0.0
            denom_len = _BM25_K1 * (1 - _BM25_B + _BM25_B * doc.length / self._avgdl)
            for t in q_terms:
                f = doc.tf.get(t)
                if f:
                    s += self._idf[t] * (f * (_BM25_K1 + 1)) / (f + denom_len)
            if s > 0:
                scored.append((s / ideal, doc.doc_id, idx))

        scored.sort(key=lambda x: (-x[0], x[1]))
        return [(self.docs[idx], round(score, 4)) for score, _, idx in scored[:top_k]]


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
    return re.sub(r"\s+", " ", best).strip()[:max_chars]
