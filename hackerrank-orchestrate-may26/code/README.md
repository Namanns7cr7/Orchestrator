# Support-Ticket Resolution Agent — Evidence-Graph Architecture

An auditable, multi-agent agent that resolves real support tickets for **Claude**,
**HackerRank**, and **Visa** by grounding every answer in a retrieved
knowledge base. It reads `support_tickets/support_tickets.csv` and writes
`support_tickets/output.csv` plus a full per-ticket reasoning trace.

This is the support-ticket realization of the **Evidence-Graph multi-agent
design** in `../files/` (originally written for claim adjudication). The mapping:

| Design doc concept            | Here                                              |
| ----------------------------- | ------------------------------------------------- |
| `ClaimFact` (what's claimed)  | `TicketFact` — normalized ticket + intent         |
| `VisualFact` (image evidence) | `EvidencePassage` — retrieved KB passage          |
| `AuthenticityFlag`            | `PolicyFlag` — scope/safety/routing signals       |
| Evidence Coverage Score (ECS) | `Coverage` — retrieval-strength level             |
| Rule-based Decision Engine    | `ResolutionEngine` — status/request_type (rules)  |
| Final-Judge justification     | `justification` — cited evidence + rule that fired|

**Key principle carried over:** retrieved evidence + deterministic rules decide
the label; the LLM only *phrases* the answer. The same ticket always produces
the same `status`/`request_type` — verified reproducible across runs.

## Quickstart

```bash
# from the repo root (hackerrank-orchestrate-may26/)
python code/main.py                              # -> support_tickets/output.csv
python code/evaluate.py                           # accuracy vs labeled sample set
python -m unittest discover -s code/tests -v      # full test suite (30 tests)
```

No dependencies are required to run offline. To enable Claude-written responses:

```bash
cp .env.example .env                # then put your key in it, OR:
export ANTHROPIC_API_KEY=sk-ant-... # macOS/Linux
setx ANTHROPIC_API_KEY sk-ant-...   # Windows (new shell)
python code/main.py
```

When no key is set, responses are produced by a deterministic **extractive
summarizer** over the top KB passages, so the pipeline always runs.

## Pipeline (6 agents)

```
TicketUnderstanding -> Retrieval -> Policy -> EvidenceMatching -> Resolution -> Response
   (TicketFact)      (Passages)  (Flags)    (Coverage)        (label, det.)  (text)
```

1. **TicketUnderstandingAgent** — normalizes the ticket, detects language.
2. **RetrievalAgent** — BM25 search (light-stemmed, length-normalized) over
   `data/{company}/`, top-k passages.
3. **PolicyAgent** — flags out-of-scope, pleasantries, outages, prompt-injection,
   security reports, financial/identity actions (never answers the ticket).
4. **EvidenceMatchingAgent** — rule-based coverage level (`sufficient`/`weak`/`none`).
5. **ResolutionEngine** — deterministic priority rules R1–R7 pick
   `status ∈ {Replied, Escalated}` and `request_type ∈ {product_issue, bug, invalid}`.
6. **ResponseAgent** — Claude (temperature=0) or extractive fallback, grounded in
   the cited passages; never reveals internal rules / retrieved docs / logic.

### Decision rules (ResolutionEngine — first match wins)

| Rule | Trigger                                   | request_type    | status    |
| ---- | ----------------------------------------- | --------------- | --------- |
| R1   | message is only thanks/greeting           | `invalid`       | Replied   |
| R2   | out-of-scope / malicious / off-topic      | `invalid`       | Replied   |
| R3   | outage / core feature down                | `bug`           | Escalated |
| R4   | security vulnerability disclosure         | `product_issue` | Escalated |
| R5   | financial transaction / identity / fraud  | `product_issue` | Escalated |
| R6   | answerable from KB (sufficient/weak)      | `product_issue` | Replied   |
| R7   | no usable evidence                        | `product_issue` | Escalated |

Prompt-injection is neutralized first: internals are never disclosed, but a
genuine support need wrapped in an injection is still answered (R6).

## Output

`support_tickets/output.csv` columns:
`issue, subject, company, response, product_area, status, request_type, justification`

Every `justification` cites the **rule that fired** and the **KB doc ids** used —
the auditable reasoning trace. Full Evidence Graphs (all agent outputs per ticket)
are written as JSON to `support_tickets/agent_outputs/` (the `agent_outputs`
audit table from `DATABASE_SCHEMA.md`).

## Evaluation

`evaluate.py` scores `status` and `request_type` against the ground-truth
columns in `sample_support_tickets.csv` and prints a confusion matrix
(Decision Accuracy from `EVALUATION_AND_EXPERIMENTS.md`). Current labeled-set
result: **100% status, 100% request_type** (10 labeled tickets).

### Tests

`code/tests/test_agent.py` is a 30-test `unittest` suite (no external deps):
retrieval determinism + relevance, every policy flag, all decision rules
(R1–R7), prompt-injection neutralization, determinism, failure isolation,
output schema, a **no-hardcoding guard** (asserts the decision code contains no
dataset ids), and an end-to-end accuracy gate (≥ 80% on the labeled set).

```bash
python -m unittest discover -s code/tests -v
```

## Retrieval

BM25 (Okapi, `k1=1.5`, `b=0.75`) over light-stemmed unigrams with a title
boost, scores normalized to `0..1` (fraction of the per-query ideal) so the
coverage thresholds are comparable across tickets. Chosen over plain TF-IDF
cosine because it handles term saturation and document length far better on
short keyword queries. Pure standard library — deterministic and dependency-free.

## Design choices

- **Deterministic by construction.** TF-IDF retrieval + rule engine; LLM at
  `temperature=0` and only for phrasing. Same input → same labels.
- **No hardcoded answers.** No ticket id / company string is special-cased to
  force a decision; everything flows through retrieval + rules.
- **Failure isolation.** Any per-ticket exception still emits a row
  (`Escalated`/`bug`, `needs_manual_review=true`) — the batch never crashes.
- **Dependency-light.** Pure standard library for retrieval; the `anthropic`
  SDK is imported lazily only when a key is present.

## Files

| File                 | Role                                              |
| -------------------- | ------------------------------------------------- |
| `main.py`            | entry point — batch run → `output.csv` + traces   |
| `pipeline.py`        | the 6 agents + Evidence Graph orchestration       |
| `knowledge_base.py`  | KB loading + deterministic TF-IDF retrieval       |
| `schemas.py`         | Evidence-Graph node/edge dataclasses              |
| `llm.py`             | optional Claude client (temperature=0)            |
| `config.py`          | paths + tunable thresholds                        |
| `evaluate.py`        | accuracy harness vs labeled sample set            |
