# Product Requirements Document (PRD)
## Multi-Modal Evidence Adjudication Platform

## 1. Problem
Claims teams (insurance, warranty, shipping carriers) receive damage claims that include a photo, a short conversation/description, and a claimant history. Today, a human adjuster has to manually cross-check the photo against the claimed damage and the claimant's history, which is slow, inconsistent across adjusters, and hard to audit. We are building a system that performs this cross-check automatically and explains its reasoning.

## 2. Target User
- **Primary:** Claims operations teams who need a first-pass adjudication on high volume, low-to-medium value claims (e.g. a cracked laptop screen, a dented car bumper, a damaged package).
- **Secondary:** A human reviewer who needs to audit *why* the system reached a decision, not just the decision itself.

## 3. Vision
Build an AI-powered claim adjudication platform that verifies damage claims using four evidence sources, ranked by trust:
1. **Images** — primary source of truth.
2. **Claim conversation** — what the claimant says happened.
3. **Evidence requirements** — what proof *should* exist for this object/damage combination.
4. **User history** — contextual risk signal only.

## 4. Key Principle (non-negotiable)
> Images are the primary source of truth. User history may raise or lower a confidence score and trigger manual review, but it can never flip a decision that the visual evidence already supports or contradicts.

In practice: a first-time claimant and a claimant with five prior claims get the *same* decision (SUPPORTED/CONTRADICTED) if the photo evidence is identical — history only changes the confidence score and whether the claim gets flagged for human review.

## 5. Scope

### In scope (v1)
- Object types: **Car**, **Laptop**, **Package**.
- Single damage claim per submission (one object, one primary damage area per claim).
- Locally stored images (no live camera/upload pipeline needed for the hackathon).
- Batch processing of a CSV of claims, producing a CSV of decisions.
- Full agent reasoning trace per claim (for auditability).

### Out of scope (v1)
- Multi-object claims (e.g. car + contents) — treat as separate claims.
- Real-time/streaming claim intake.
- Payout calculation or policy/coverage lookup — we adjudicate *whether the claim is evidenced*, not what it's worth.
- Video evidence (image stills only).
- Multi-language conversation support (English only for v1).
- Human-in-the-loop UI for overturning decisions (logged as a future extension, not built this cycle).

## 6. Inputs
| Input | Description |
|---|---|
| `claims.csv` | One row per claim: claim_id, user_id, object_type, conversation text, claimed_part, claimed_damage. |
| `user_history.csv` | One row per user_id: prior claim count, prior claims on same part/object, account age, prior fraud flags. |
| `images/` | Local folder of claim photos, referenced by claim_id. |

## 7. Decisions
The system outputs exactly one of three labels per claim, plus a confidence score (0.0–1.0) and a justification string:

| Decision | Meaning |
|---|---|
| `SUPPORTED` | Visual evidence is consistent with the claimed damage on the claimed part/object, and the evidence checklist is sufficiently satisfied. |
| `CONTRADICTED` | Visual evidence directly conflicts with the claim (e.g. no damage visible where claimed, damage on a different part, undamaged object, evidence shows pre-existing/inconsistent damage). |
| `INSUFFICIENT_EVIDENCE` | Visual evidence neither confirms nor conflicts — required evidence is missing, image quality is too poor to assess, or the claim is ambiguous. |

## 8. Example Claim (worked reference case — used throughout all docs)
- **claim_id:** `CLM-1042`
- **object_type:** Car
- **conversation:** "Someone backed into my rear bumper in the parking lot, there's a big dent and the paint is scraped off."
- **claimed_part:** rear_bumper
- **claimed_damage:** dent + paint_scrape
- **images:** 2 photos — one wide shot of the car's rear, one close-up of the bumper.
- **user_history:** 1 prior claim (18 months ago, different part), account age 3 years.
- **Expected reasoning:** Vision Agent confirms a dent and paint scrape on the rear bumper in both photos at high confidence → Evidence Matching Agent finds all *critical* checklist items satisfied → Risk Agent notes mild prior history but nothing disqualifying → Final Judge returns `SUPPORTED`, confidence 0.91.

This example is referenced again in `APP_FLOW.md`, `AGENT_ARCHITECTURE.md`, and `SYSTEM_DESIGN.md` to keep all docs consistent.

## 9. Success Metrics
| Metric | Definition | Target (hackathon demo) |
|---|---|---|
| **Decision Accuracy** | % of claims where system decision matches labeled ground truth. | ≥ 80% on demo set |
| **Explainability** | % of decisions where the justification cites specific evidence (image + checklist item), reviewed manually by judges. | 100% (every decision must cite evidence) |
| **Reliability** | % of claims that complete the full pipeline without an agent error/crash. | ≥ 95% |
| **Reproducibility** | Same claim + same images → same decision across repeated runs (temperature/seed controlled). | 100% identical decision label across 3 runs |

## 10. Deliverables
| Deliverable | Description |
|---|---|
| `output.csv` | One row per claim: claim_id, decision, confidence, evidence_coverage_score, justification. See `DATABASE_SCHEMA.md` for exact columns. |
| Evaluation reports | Accuracy breakdown by object type, damage type, and ablation results — see `EVALUATION_AND_EXPERIMENTS.md`. |
| Agent logs | Per-claim, per-agent JSON output (full reasoning trace) for audit — stored in `agent_outputs` table. |
| Chat transcript | The raw claim conversation as received, stored alongside the claim for traceability. |

## 11. Non-Goals / Explicit Risks
- We are **not** trying to detect fraud definitively — `CONTRADICTED` means "evidence doesn't support this claim," not "this claimant is lying." The justification language must reflect this distinction.
- Image-based damage detection will have false negatives on subtle damage (hairline cracks, fine scratches) — this is a known v1 limitation, tracked in `EVALUATION_AND_EXPERIMENTS.md` failure analysis.
