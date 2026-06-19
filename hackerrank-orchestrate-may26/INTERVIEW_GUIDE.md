# Project Guide & Interview Prep — Multi-Domain Support Triage Agent

A complete walkthrough of what we built, **why** we built it that way, the
trade-offs we made, where it breaks, and the questions a judge is likely to ask.
Read this end-to-end before the interview; the **30-second pitch** and the
**Likely questions** section are the highest-value parts.

---

## 1. 30-second pitch

> "It's a terminal-based support-triage agent for HackerRank, Claude, and Visa
> tickets. The core idea is **separation of concerns**: six small agents each
> extract one kind of fact into a shared structure, then a **deterministic,
> rule-based engine** makes the routing decision — reply vs escalate, and the
> request type — and the LLM is used *only* to phrase the final answer, grounded
> in passages we retrieved from the provided corpus with BM25. That design makes
> every decision auditable and the whole system reproducible: same ticket, same
> output, every run. It hits 100% on the labeled sample for both status and
> request type, runs fully offline, and ships with a 33-test suite."

---

## 2. The problem

Each ticket has `issue`, `subject` (noisy/blank), and `company`
(`HackerRank`/`Claude`/`Visa`/`None`). For each one we must output five fields:

| Field | Allowed values | Meaning |
|---|---|---|
| `status` | `replied`, `escalated` | answer directly or hand to a human |
| `request_type` | `product_issue`, `feature_request`, `bug`, `invalid` | classification |
| `product_area` | free text | best-fit support category |
| `response` | text | user-facing answer, **grounded in the corpus only** |
| `justification` | text | concise, traceable reason for the decision |

The hard parts: tickets can be multi-intent, irrelevant, or **malicious**
(prompt injection); `None`-company tickets need domain inference; and we must
**escalate** sensitive/high-risk cases instead of guessing.

---

## 3. Architecture — six agents + an Evidence Graph

```
TicketUnderstanding -> Retrieval -> Policy -> EvidenceMatching -> Resolution -> Response
   (TicketFact)      (BM25 evidence) (safety) (coverage)        (rules R1-R7)  (grounded text)
```

Each agent writes one typed fact into a shared `EvidenceGraph` (see
`code/schemas.py`); the Resolution engine reads the whole graph and emits the
final decision. This mirrors a claims-adjudication "Evidence Graph" design we
adapted to support tickets — "evidence" = retrieved KB passages, "decision" =
ticket disposition.

| # | Agent | File | Responsibility |
|---|---|---|---|
| 1 | TicketUnderstanding | `pipeline.py` | normalize text, detect language, build the query |
| 2 | Retrieval | `knowledge_base.py` | BM25 top-k passages from `data/{company}/` (the **grounding**) |
| 3 | Policy | `pipeline.py` | flag scope/safety/routing signals (never answers) |
| 4 | EvidenceMatching | `pipeline.py` | rule-based coverage level (`sufficient`/`weak`/`none`) |
| 5 | Resolution | `pipeline.py` | **deterministic rules** pick `status` + `request_type` |
| 6 | Response | `pipeline.py` | LLM (temp=0) or extractive fallback, grounded + cited |

**Why this matters in the interview:** the LLM never *chooses* the label. The
label is chosen by code you can read line-by-line. That is the single most
important design decision — it's what gives reproducibility and auditability.

---

## 4. The decision rules (escalation logic) — `ResolutionEngine`

Evaluated in strict priority order, first match wins. This *is* the "smart
routing" the brief asks for, and it's plain code, not a model judgment:

| Rule | Trigger | request_type | status |
|---|---|---|---|
| **R1** | message is only thanks/greeting | `invalid` | replied ("Happy to help") |
| **R2** | off-topic / malicious / no product intent | `invalid` | replied (out-of-scope msg) |
| **R3** | outage / core feature down | `bug` | **escalated** |
| **R4** | security vulnerability disclosure | `product_issue` | **escalated** (security team) |
| **R5** | financial transaction / identity / fraud | `product_issue` | **escalated** (authenticated human) |
| **R5b** | request for a new product capability | `feature_request` | replied (logged) |
| **R6** | answerable from KB (coverage sufficient/weak) | `product_issue` | replied (grounded answer) |
| **R7** | no usable evidence | `product_issue` | **escalated** (can't ground) |

**Prompt injection** is neutralized *before* answering: internal rules,
retrieved docs, and decision logic are never revealed — but a genuine request
wrapped in an injection (e.g. the French "my card is blocked, also show me your
internal rules" ticket) is still answered, with a confidentiality guard appended.

---

## 5. Key design decisions & the alternatives we rejected

**D1 — Rule-based decision engine, not an LLM judge.**
*Why:* reproducibility (judges score determinism), auditability (every decision
cites the rule + doc ids), and no risk of the model over-weighting a verbose but
irrelevant part of the ticket. *Rejected:* "feed everything to one LLM and ask
for the label" — non-reproducible, hard to explain, and it tends to guess
instead of escalating on sensitive tickets.

**D2 — BM25 retrieval, pure standard library.**
*Why:* BM25 (Okapi, `k1=1.5`, `b=0.75`) handles term saturation and document
length far better than TF-IDF cosine on short, keyword-y ticket queries; pure
stdlib means zero dependencies, deterministic, and runs anywhere. *Rejected:*
(a) **embeddings / vector DB** — better semantics but adds a heavy dependency,
non-determinism, and needs a model/API just to retrieve; overkill for ~770 docs.
(b) **plain TF-IDF** — we started there and measured BM25 as better on the
wrong-doc cases. We also tried **bigrams** and removed them — they added more
noise than signal on this corpus.

**D3 — LLM only writes the response, at `temperature=0`, with an offline
fallback.** *Why:* keeps the system runnable and deterministic with no key; the
LLM is told to use only the retrieved passages and never invent policies. The
decision is already fixed before the LLM is called, so it can only phrase the
"why", not change the "what".

**D4 — Off-topic detection by *intent*, not retrieval score.**
*Why:* an off-topic trivia question ("actor in Iron Man") scores about the same
against the corpus as a real ticket, so the score can't separate them. We route
on whether the ticket names a supported product or expresses a concrete problem.

**D5 — Company-scoped retrieval with a corpus-wide fallback.** A `Visa` ticket
searches `data/visa/` first; `None`-company tickets search everything. Keeps
results on-domain while still handling cross-domain/generic tickets.

---

## 6. Determinism & reproducibility (how we guarantee it)

- BM25 + the rule engine are pure functions of the input — no randomness.
- Retrieval ties are broken by `doc_id` for a stable ordering.
- The LLM call (optional) uses `temperature=0`.
- **Verified:** running `main.py` twice produces a byte-identical `output.csv`.

---

## 7. Safety & "don't hallucinate"

- **Escalate, don't guess:** outages, security reports, financial/identity
  matters, and no-evidence cases all escalate (R3/R4/R5/R7).
- **Grounding:** responses are built from retrieved passages; the LLM prompt
  forbids inventing policies, phone numbers, or URLs.
- **Prompt-injection resistant:** a dedicated policy rule detects "reveal your
  internal rules/retrieved docs/logic" (incl. French/Spanish) and the engine
  never surfaces internal rule ids or doc dumps to the user.

---

## 8. Engineering hygiene

- Typed modules with one responsibility each; thresholds live in `config.py`.
- Secrets from env vars only (`ANTHROPIC_API_KEY`) — no keys in code.
- **33-test suite** (`code/tests/test_agent.py`, pure stdlib `unittest`):
  retrieval determinism + relevance, every policy flag, every decision rule,
  injection neutralization, failure isolation, output schema, and an end-to-end
  **accuracy gate**.
- **No-hardcoding guard:** a test asserts the decision code contains no dataset
  ids (no `CLM-`, `cs_live_abcdefgh`, `U-201`, …) so nothing is special-cased to
  the data.
- **Failure isolation:** if any agent throws, the ticket still gets a row
  (escalated/bug, flagged for review) — the batch never crashes.

---

## 9. Results

- **Labeled sample set: 100% status, 100% request_type** (10 labeled tickets).
- Full `support_tickets.csv` (29): 20 replied / 9 escalated; 24 product_issue,
  4 bug, 1 invalid — a sensible distribution, only 2 flagged for manual review.
- Reproducible across runs; runs fully offline.

> Caveat to state honestly: the labeled set is only 10 rows, so 100% is a
> directional signal, not a guarantee of held-out accuracy.

---

## 10. Failure modes (be honest — judges reward this)

1. **Retrieval semantic gaps.** Tickets whose wording doesn't lexically match
   the right doc (e.g. "employee left, remove them" vs a "Teams Management" doc)
   can surface a topically-off passage. *Fix:* embeddings/hybrid retrieval, or
   query expansion with synonyms. We chose lexical for determinism + zero deps.
2. **Threshold brittleness.** `sufficient`/`weak` thresholds (0.20/0.08) are
   calibrated on a small labeled set; a very different ticket distribution could
   need recalibration. *Fix:* learn thresholds from a larger labeled set.
3. **Regex policy rules have edge cases.** Detection of outage/feature/financial
   intent is pattern-based; unusual phrasings can be missed or over-matched.
   *Fix:* a small classifier per signal, or an LLM check as a *second opinion*
   that can only *raise* escalation, never lower it.
4. **`product_area` is derived from the top doc's folder path** — readable but
   not a curated taxonomy. *Fix:* map folders to a fixed category list.
5. **Offline response quality.** Without an API key the response is extractive,
   so phrasing is rougher than the LLM path (classification is unaffected).

---

## 11. Trade-offs at a glance

| We chose | Over | Because |
|---|---|---|
| Rule-based decisions | LLM judge | reproducible, auditable, escalates reliably |
| BM25 (stdlib) | embeddings/vector DB | deterministic, zero-dep, enough for ~770 docs |
| LLM for phrasing only | LLM for everything | label can't drift; grounded, honest answers |
| Intent-based scope check | score threshold | off-topic and real tickets score alike |
| Small, typed modules | one big script | testable, explainable, easy to extend |

---

## 12. Honesty about AI assistance (the rubric asks this explicitly)

Be straight about this in the interview. A fair framing:

> "I drove the architecture and the decisions — the separation of concerns, the
> choice to keep the decision engine rule-based, BM25 over embeddings for
> determinism, the escalation rules and their priority order, and the spec
> details like lowercase status and adding `feature_request`. I used an AI coding
> assistant to implement and refactor faster and to write the test suite, and I
> verified its output: I reviewed every ticket's routing, caught and fixed bugs
> the tests surfaced (a pleasantry being overridden by a high retrieval score, an
> over-aggressive stemmer), and rejected changes that didn't help (bigrams)."

Have one concrete example ready of something you *changed your mind on* or
*rejected* — e.g. "I tried bigrams in retrieval and removed them because they
regressed exact-title matches," or "I narrowed the 'stolen card' rule because
reporting a lost card is answerable from the KB, not an escalation."

---

## 13. Likely interview questions — crisp answers

- **"Walk me through what happens to one ticket."** Understanding normalizes it →
  Retrieval pulls top-5 BM25 passages from that company's corpus → Policy flags
  any safety/scope signals → EvidenceMatching sets a coverage level → Resolution
  applies rules R1–R7 to pick status + request_type → Response phrases a grounded
  reply. Every step is logged to a per-ticket JSON trace.

- **"Why not just one LLM call?"** Non-reproducible, hard to audit, and it tends
  to answer sensitive tickets it should escalate. We separate *deciding* (rules)
  from *phrasing* (LLM) so the decision is fixed and explainable.

- **"How do you avoid hallucinated policies?"** Answers are built only from
  retrieved passages; the LLM prompt forbids inventing facts; low-coverage and
  high-risk tickets escalate instead of guessing.

- **"How do you decide replied vs escalated?"** The R1–R7 priority rules:
  outages, security, financial/identity, and no-evidence cases escalate;
  answerable tickets reply with a grounded answer; pleasantries and off-topic are
  invalid.

- **"What about a malicious ticket?"** Prompt-injection is detected and
  neutralized — we never reveal internal rules/docs/logic — but we still answer
  any legitimate need inside it.

- **"How is it reproducible?"** BM25 + rules are deterministic, ties broken by
  doc id, LLM at temperature 0; two runs produce identical `output.csv`.

- **"Where does it fail and how would you fix it?"** See §10 — lead with
  retrieval semantic gaps and the fix (hybrid/embedding retrieval), and threshold
  calibration on a bigger labeled set.

- **"How did you test it?"** 33 stdlib tests incl. an accuracy gate and a
  no-hardcoding guard; they caught real bugs during development.

---

## 14. Fast facts to memorize

- Corpus: **773 docs** (claude 321, hackerrank 438, visa 14).
- Retrieval: **Okapi BM25**, `k1=1.5`, `b=0.75`, light stemming, scores
  normalized to 0–1.
- Coverage thresholds: sufficient ≥ **0.20**, weak ≥ **0.08**.
- Decision: **rules R1–R7** (+ R5b feature_request), priority-ordered.
- LLM: optional, **temperature 0**, phrasing only; offline extractive fallback.
- Tests: **33**, all passing. Accuracy: **100%/100%** on the 10-row labeled set.
- Entry point: `python code/main.py` → `support_tickets/output.csv`.
