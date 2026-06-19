# Multi-Domain Support Triage Agent — Submission

A terminal-based, deterministic, multi-agent support-triage system for the
**HackerRank Orchestrate** challenge. It reads `support_tickets/support_tickets.csv`,
grounds every answer in the provided corpus under `data/` (HackerRank, Claude,
Visa), and writes `support_tickets/output.csv` with the five required columns:
`status, product_area, response, justification, request_type`.

> Full technical write-up: **[code/README.md](code/README.md)**.
> Original challenge instructions are preserved in **[STARTER_README.md](STARTER_README.md)**
> (including the chat-transcript / `log.txt` logging location).

## Quickstart

```bash
# Python 3.10+. No install needed to run — pure standard library.
python code/main.py                              # -> support_tickets/output.csv
python code/evaluate.py                           # accuracy vs labeled sample set
python -m unittest discover -s code/tests -v      # 33-test suite
```

Optional — grounded LLM-written responses (otherwise a deterministic extractive
summary of the retrieved passages is used, so it always runs offline):

```bash
cp .env.example .env        # add your key, or export it:
export ANTHROPIC_API_KEY=sk-ant-...
python code/main.py
```

Secrets are read from env vars only — no keys in code.

## Approach (one screen)

A **multi-agent pipeline** writes typed facts into a shared structure; a
**deterministic, rule-based engine** makes the routing decision; the LLM (if
present) only *phrases* the reply. This separation is what makes the system
auditable and reproducible.

```
TicketUnderstanding -> Retrieval -> Policy -> EvidenceMatching -> Resolution -> Response
   (TicketFact)      (BM25 evidence) (safety) (coverage)        (rules R1-R7)  (grounded text)
```

- **Retrieval (grounding):** Okapi **BM25** over the `data/` corpus, light
  stemming, length-normalized scores. Answers come from the corpus, not model
  memory.
- **Routing / escalation:** explicit, ordered rules decide
  `status ∈ {replied, escalated}` and
  `request_type ∈ {product_issue, feature_request, bug, invalid}`:
  pleasantries and off-topic/malicious → `invalid`; outages → `bug`/escalated;
  security disclosures, financial/identity actions → escalated; feature asks →
  `feature_request`; answerable tickets → grounded `replied`; no evidence →
  escalated.
- **Safety:** prompt-injection is neutralized (internal rules/docs/logic are
  never revealed) while a genuine request wrapped in an injection is still
  answered. No hallucinated policies — uncertain/high-risk tickets escalate.
- **Determinism:** BM25 + rules + `temperature=0`; identical output across runs.

## How this maps to the evaluation criteria

| Criterion | Where |
| --- | --- |
| **Agent design** — separation of concerns, justified technique | `code/pipeline.py` (6 agents), `code/knowledge_base.py` (BM25) |
| **Use of the corpus** — grounded answers | retrieval over `data/`; every `justification` cites the doc ids used |
| **Escalation logic** — high-risk/sensitive/out-of-scope | `ResolutionEngine` rules R1–R7 in `code/pipeline.py` |
| **Determinism & reproducibility** | pure-stdlib BM25, rule engine, `temperature=0`; verified identical across runs |
| **Engineering hygiene** | typed modules, env-var secrets, **33-test** suite incl. a no-hardcoding guard |
| **Output CSV** | `support_tickets/output.csv` (5 required columns) |
| **Auditability** | full per-ticket reasoning trace JSON in `support_tickets/agent_outputs/` |

## Repository layout

```
code/                 # the solution (entry point: main.py)
  pipeline.py         #   6 agents + rule-based Resolution Engine
  knowledge_base.py   #   BM25 retrieval over data/
  schemas.py, llm.py, config.py, evaluate.py
  tests/test_agent.py #   33 tests
data/                 # provided corpus: claude/ hackerrank/ visa/
support_tickets/      # input CSVs + output.csv (+ agent_outputs/ traces)
```

Results: **100% status / 100% request_type** on the labeled `sample_support_tickets.csv`.
