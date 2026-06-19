# System Design

## 1. End-to-End Flow

```
Conversation ──────────────► Claim Understanding Agent ──► ClaimFact
                                                               │
                                                               ▼
                                              Evidence Requirement Agent ──► RequiredEvidence[]
Images ────────────────────► Vision Analysis Agent ──► VisualFact[]
Images ────────────────────► Authenticity Agent ─────► AuthenticityFlag[]
User History ───────────────► Risk Agent ─────────────► RiskFact[]

ClaimFact + RequiredEvidence[] + VisualFact[] + AuthenticityFlag[] + RiskFact[]
                          │
                          ▼
                  EVIDENCE GRAPH (all facts as nodes, relationships as edges)
                          │
                          ▼
                  Evidence Matching Agent ──► Evidence Coverage Score (ECS) + contradiction flags
                          │
                          ▼
                  Decision Engine (rule-based, inside Final Judge Agent) ──► decision + confidence + justification
                          │
                          ▼
                      output.csv
```

## 2. Evidence Graph Schema

The Evidence Graph is the shared structure all agents write into and the Matching/Decision Engine read from. It is a simple typed node/edge graph, one per claim.

### Node types
| Node type | Fields | Written by |
|---|---|---|
| `ClaimFact` | `id, object_type, claimed_part, claimed_damage[], claimed_severity, source="conversation"` | Claim Understanding Agent |
| `RequiredEvidence` | `id, evidence_type, criticality ("critical"\|"supporting"), satisfied (bool, default false)` | Evidence Requirement Agent |
| `VisualFact` | `id, image_id, detected_object, detected_part, detected_damage[], severity, confidence (0-1)` | Vision Analysis Agent |
| `AuthenticityFlag` | `id, image_id, flag_type ("blur"\|"crop"\|"duplicate"\|"manipulation_suspected"), severity ("low"\|"high")` | Authenticity Agent |
| `RiskFact` | `id, risk_type, value, weight (0-1)` | Risk Agent |

### Edge types
| Edge | From → To | Meaning |
|---|---|---|
| `requires` | `ClaimFact → RequiredEvidence` | This claim generates this checklist item. |
| `satisfies` | `VisualFact → RequiredEvidence` | This image evidence fulfills this checklist item. |
| `contradicts` | `VisualFact → ClaimFact` | This image evidence conflicts with what was claimed (e.g. damage on a different part, no damage visible, undamaged object). |
| `discounts` | `AuthenticityFlag → VisualFact` | This flag reduces the trust weight of a visual fact (does not delete it — a blurry photo is weighted lower, not ignored). |
| `modifies_confidence` | `RiskFact → Decision` | Risk facts may only adjust the confidence score / trigger a manual-review flag; they cannot create or remove a `contradicts`/`satisfies` edge. This edge enforces the Key Principle from the PRD: **images decide; history only adjusts confidence.** |

### Example graph instance — claim `CLM-1042` (rear bumper dent, see PRD Section 8)
```
ClaimFact(C1: car, rear_bumper, [dent, paint_scrape])
  --requires--> RequiredEvidence(R1: damage_visible_on_claimed_part, critical)
  --requires--> RequiredEvidence(R2: full_vehicle_context_shot, supporting)
  --requires--> RequiredEvidence(R3: close_up_of_damage, critical)

VisualFact(V1: image=IMG-1042-1, part=rear, damage=[dent], confidence=0.88)
  --satisfies--> R2
VisualFact(V2: image=IMG-1042-2, part=rear_bumper, damage=[dent, paint_scrape], confidence=0.93)
  --satisfies--> R1
  --satisfies--> R3

AuthenticityFlag: none raised for V1 or V2.

RiskFact(K1: prior_claims_count=1, weight=0.1)
  --modifies_confidence--> (minor downward adjustment only)

Result: R1 ✅, R2 ✅, R3 ✅ → ECS = 1.0, no contradicts edges → SUPPORTED, confidence 0.91
```

### Counter-example — what `CONTRADICTED` looks like
If `V2` instead detected `detected_part=front_bumper, damage=[none]`, the Matching Agent would write a `contradicts` edge from `V2` to `C1` (claimed rear bumper damage, photo shows undamaged front bumper). Per the Key Principle, this `contradicts` edge **forces `CONTRADICTED`** regardless of how clean the user's history is.

## 3. Matching Engine (algorithm)
For each claim:
1. For every `RequiredEvidence` node, search `VisualFact` nodes for a `satisfies` relationship (a visual fact whose `detected_part`/`detected_damage` matches the required evidence's `evidence_type`, above a confidence threshold of 0.6).
2. Discount any `VisualFact`'s effective confidence by the severity of its `discounts` edges from `AuthenticityFlag`s (high severity flag → confidence capped at 0.4; low severity → confidence × 0.85).
3. Mark `RequiredEvidence.satisfied = true` if a discounted-confidence visual fact satisfies it.
4. Separately, check every `VisualFact` against the `ClaimFact` for direct conflict (wrong part, wrong/absent damage, undamaged object) → write `contradicts` edge if found.
5. Compute **Evidence Coverage Score (ECS)**:
   ```
   ECS = (sum of satisfied critical items × 2 + sum of satisfied supporting items × 1)
         ÷ (total critical items × 2 + total supporting items × 1)
   ```
   Critical items are weighted 2x supporting items, since a missing close-up shot shouldn't block a decision the way a missing damage photo would.

## 4. Decision Engine (rule-based, deterministic)
Applied in this strict priority order — never an LLM judgment call, so it's reproducible by construction:

1. **If any `contradicts` edge exists** between a `VisualFact` (with discounted confidence ≥ 0.6) and the `ClaimFact` → `CONTRADICTED`.
2. **Else if ECS ≥ 0.8 AND all critical `RequiredEvidence` items are satisfied** → `SUPPORTED`.
3. **Else** → `INSUFFICIENT_EVIDENCE`.

Confidence score (0–1) is then computed as:
```
confidence = (0.6 × ECS) + (0.4 × avg_visual_fact_confidence) − risk_adjustment
risk_adjustment = min(0.15, sum(RiskFact.weight for high-risk facts))
```
`risk_adjustment` can only ever lower confidence within the already-determined decision band — it never changes which of the three labels is chosen (enforces the Key Principle). If `risk_adjustment` would push confidence below 0.5 on a `SUPPORTED` decision, the claim is additionally flagged `needs_manual_review = true` in the output, but the label itself stays `SUPPORTED`.

## 5. Benefits of This Design
- **Explainable reasoning** — every decision traces back to specific named nodes/edges (which photo, which checklist item, which contradiction) rather than an opaque model judgment.
- **Multi-modal fusion** — conversation, images, and history are combined through structured facts, not concatenated into one giant prompt where the model might over-weight whichever source happens to be more verbose.
- **Reduced hallucinations** — the Decision Engine is plain rule-based code operating on validated JSON facts; the only free-form LLM step left near the decision is generating the justification *text*, not the label itself.
- **Auditability** — the full graph per claim is persisted, so a human reviewer can replay exactly why a claim was adjudicated a given way, which is required for any real-world claims tool.
