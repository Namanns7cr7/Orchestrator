# Technical Requirements Document (TRD)

## 1. Architecture Summary
**Evidence Graph–Based Multi-Agent System.** Specialized agents each extract one type of fact (claim, vision, authenticity, risk), all facts are written as nodes into a shared **Evidence Graph**, a deterministic Matching Engine scores coverage against an Evidence Requirement checklist, and a Decision Engine applies fixed rules (not a free-form LLM judgment) to produce the final label. See `SYSTEM_DESIGN.md` for the graph schema.

Why not a single end-to-end LLM call? A single call can't be audited per-fact, conflates "the photo doesn't show damage" with "the user has a bad history," and can't be selectively ablated for evaluation. The multi-agent + graph design solves all three.

## 2. Inputs (formats)

### `claims.csv`
```
claim_id, user_id, object_type, claimed_part, claimed_damage, conversation, image_ids
CLM-1042, U-201, car, rear_bumper, "dent;paint_scrape", "Someone backed into my rear bumper...", "IMG-1042-1;IMG-1042-2"
```

### `user_history.csv`
```
user_id, prior_claims_count, prior_claims_same_object_type, prior_claims_same_part, account_age_days, prior_fraud_flags
U-201, 1, 0, 0, 1095, 0
```

### `images/`
Local folder, filenames matching `image_ids` referenced in `claims.csv` (e.g. `IMG-1042-1.jpg`).

## 3. Core Agents
| # | Agent | Responsibility |
|---|---|---|
| 1 | Claim Understanding Agent | Parses conversation + structured claim fields into a normalized `ClaimFact`. |
| 2 | Evidence Requirement Agent | Generates the evidence checklist (critical vs. supporting items) for this object/damage combination. |
| 3 | Vision Analysis Agent | Per image: detects object, part, damage type, severity, confidence. |
| 4 | Authenticity Agent | Per image: flags blur, crop, duplication, metadata/manipulation signals. |
| 5 | Risk Agent | Converts `user_history.csv` row into weighted risk facts. |
| 6 | Evidence Matching Agent | Matches `VisualFact`s against the checklist, computes Evidence Coverage Score (ECS), detects contradictions. |
| 7 | Final Judge Agent | Applies the fixed decision rules (Section 6 of `SYSTEM_DESIGN.md`) and writes the justification text. |

Full I/O contracts for each agent are in `AGENT_ARCHITECTURE.md`.

## 4. Tech Stack (hackathon-appropriate)
- **Orchestration:** Python script or lightweight agent framework (sequential pipeline; no need for a complex multi-agent framework given fixed agent order — see `SYSTEM_DESIGN.md` flow).
- **Vision + reasoning model:** A single multimodal LLM (e.g. Claude) used for the Vision Analysis Agent, Claim Understanding Agent, and Final Judge Agent, called separately per role with role-specific system prompts and strict JSON-schema output.
- **Authenticity checks:** A mix of deterministic CV checks (blur via Laplacian variance, perceptual-hash duplicate detection) plus an LLM pass for manipulation cues — deterministic checks run first since they're cheap and exact.
- **Storage:** SQLite (or plain CSV/JSON files) — see `DATABASE_SCHEMA.md`. No need for a hosted DB for a hackathon submission.
- **Output:** `output.csv` + per-claim JSON logs.

## 5. Constraints and How We Satisfy Them
| Constraint | What it means | How v1 satisfies it |
|---|---|---|
| **No hardcoded labels** | The system must not special-case specific claim_ids, user_ids, or damage strings to force a decision. | All decision logic operates on the structured facts in the Evidence Graph, never on raw IDs or literal string matches against the dataset. Code review checklist item before submission. |
| **Deterministic outputs** | Same input → same output, every run. | (a) All LLM calls use `temperature=0` and a fixed seed where the API supports it. (b) All agent outputs are validated against a strict JSON schema; malformed output triggers one retry with the same prompt, not a randomized re-ask. (c) The Decision Engine itself is pure rule-based code (no LLM call) — see `SYSTEM_DESIGN.md` Section 6 — so the same Evidence Graph always yields the same decision. |
| **Dataset agnostic** | The pipeline must work on car/laptop/package claims without per-dataset code branches beyond the Evidence Requirement checklist templates. | Object-specific knowledge lives only in the Evidence Requirement Agent's checklist templates (data, not code). All other agents operate on generic fact types (`ClaimFact`, `VisualFact`, etc.) regardless of object_type. |

## 6. Non-Functional Requirements
- **Latency:** ≤ 30s per claim end-to-end (acceptable for a batch adjudication tool, not real-time chat).
- **Auditability:** Every agent's raw output is persisted (`agent_outputs` table) — a reviewer must be able to reconstruct the full reasoning chain for any decision after the fact.
- **Failure isolation:** If one agent fails on a claim (e.g. image unreadable), the pipeline must still emit a row in `output.csv` with decision `INSUFFICIENT_EVIDENCE` and a justification noting the failure, rather than crashing the batch.
- **Idempotency:** Re-running the pipeline on the same `claims.csv` must overwrite (not duplicate) prior results for the same claim_id.

## 7. Open Technical Risks
- Vision model confidence on subtle damage (hairline cracks, minor dents) is unverified pre-build — flagged for the failure analysis in `EVALUATION_AND_EXPERIMENTS.md`.
- "Deterministic" LLM calls are deterministic *in practice*, not guaranteed by the API — we treat any rare drift as a known limitation, not a blocker.
