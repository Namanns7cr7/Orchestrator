# Application Flow

This describes the runtime flow for processing one claim, including error handling at each step. All examples use reference claim `CLM-1042` (rear bumper dent — see `PRD.md` Section 8).

## Step-by-step

### 1. Load Claim
Read the claim's row from `claims.csv` by `claim_id`.
- **Error case:** `claim_id` not found, or required field empty (e.g. missing `claimed_part`) → abort this claim, write `INSUFFICIENT_EVIDENCE` to `output.csv` with justification `"malformed claim record"`, continue to next claim (per `TRD.md` Section 6 failure isolation).

### 2. Load Images
Resolve `image_ids` to files in `images/`.
- **Error case:** zero images found for a claim → skip Vision/Authenticity agents, proceed directly to Step 9 with `INSUFFICIENT_EVIDENCE` (no visual evidence exists to confirm or deny anything — see Decision Engine rule 3 in `SYSTEM_DESIGN.md`).
- **Error case:** an image file is corrupt/unreadable → drop that image_id from the set, log a warning, continue with remaining images.

### 3. Extract Claim
Run the **Claim Understanding Agent** → produces `ClaimFact` (see `AGENT_ARCHITECTURE.md` Section 1).
- **Error case:** agent output fails JSON schema validation → retry once with the same prompt (temperature=0, so this should be rare); if it fails again, abort claim with `INSUFFICIENT_EVIDENCE`, justification `"claim parsing failed"`.

### 4. Build Evidence Requirements
Run the **Evidence Requirement Agent** on the `ClaimFact` → produces `RequiredEvidence[]` (Section 2 of `AGENT_ARCHITECTURE.md`).
- For `CLM-1042`: produces R1 (damage on rear bumper, critical), R2 (full vehicle context shot, supporting), R3 (close-up of damage, critical).

### 5. Analyze Images
Run the **Vision Analysis Agent** on each loaded image → produces one `VisualFact` per image.
- For `CLM-1042`: V1 from `IMG-1042-1` (wide shot), V2 from `IMG-1042-2` (close-up).
- **Error case:** model returns low-confidence/uncertain detection on all images → those `VisualFact`s are still recorded (not discarded) but will likely fail to satisfy critical evidence in Step 8, naturally producing `INSUFFICIENT_EVIDENCE` rather than a hard error.

### 6. Analyze Quality (Authenticity)
Run the **Authenticity Agent** on each image → produces `AuthenticityFlag[]` (possibly empty).
- For `CLM-1042`: no flags raised on either image.

### 7. Assess Risk
Run the **Risk Agent** on the matching `user_history.csv` row → produces `RiskFact[]`.
- **Error case:** `user_id` not found in `user_history.csv` → treat as a new user (all risk weights default to 0), do not block the pipeline.
- For `CLM-1042`: K1 (1 prior claim, weight 0.10), K2 (account age 3yrs, weight 0.0).

### 8. Compute Evidence Coverage
Run the **Evidence Matching Agent** (rule-based, see `SYSTEM_DESIGN.md` Section 3) over the assembled Evidence Graph → produces satisfied/unsatisfied evidence, contradictions, and ECS.
- For `CLM-1042`: R1, R2, R3 all satisfied, no contradictions, ECS = 1.0.

### 9. Final Adjudication
Run the **Final Judge Agent**: apply Decision Engine rules (`SYSTEM_DESIGN.md` Section 4) to get the label, compute confidence, generate justification text.
- For `CLM-1042`: `SUPPORTED`, confidence 0.91, `needs_manual_review = false`.

### 10. Generate output.csv
Append the final row (see exact columns in `DATABASE_SCHEMA.md`) and persist all intermediate agent outputs to the `agent_outputs` table for audit.
- **Error case:** write failure (disk full, permissions) → retry once, then log claim_id to a `failed_writes.log` for manual reprocessing rather than silently dropping the result.

## Batch-level behavior
- The pipeline processes `claims.csv` row by row; a failure on one claim never halts the batch (Step 1–9 error handling above ensures every claim gets *some* row in `output.csv`).
- Re-running the full batch on the same `claims.csv` overwrites prior rows by `claim_id` (idempotent — see `TRD.md` Section 6).
- At the end of the batch, a summary is printed: total claims processed, count per decision label, count flagged for manual review, count of claims that hit an error-handling path.
