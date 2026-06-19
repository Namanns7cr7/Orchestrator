# Agent Architecture

Each agent below has a fixed responsibility, a strict JSON input/output contract, and runs with `temperature=0` (see `TRD.md` Section 5). All examples use the reference claim `CLM-1042` from `PRD.md` Section 8.

---
## 1. Claim Understanding Agent
**Purpose:** Extracts object, damage, part, and claim intent from the structured claim fields and free-text conversation, producing a single normalized `ClaimFact`.

**Input:**
```json
{
  "claim_id": "CLM-1042",
  "object_type": "car",
  "claimed_part": "rear_bumper",
  "claimed_damage": "dent;paint_scrape",
  "conversation": "Someone backed into my rear bumper in the parking lot, there's a big dent and the paint is scraped off."
}
```
**Output (`ClaimFact`):**
```json
{
  "id": "C1",
  "object_type": "car",
  "claimed_part": "rear_bumper",
  "claimed_damage": ["dent", "paint_scrape"],
  "claimed_severity": "moderate",
  "claim_intent": "collision_damage",
  "source": "conversation"
}
```
**Prompt strategy:** System prompt constrains the model to only use the structured fields + conversation (no outside knowledge), and to output strictly the `ClaimFact` schema. If conversation and structured fields disagree (e.g. conversation mentions a second damage area not in `claimed_damage`), the agent includes both and flags `field_conversation_mismatch: true` for the Final Judge to mention in its justification.

---
## 2. Evidence Requirement Agent
**Purpose:** Given the `ClaimFact`, generates the checklist of evidence a claim like this *should* have, marked critical vs. supporting. This is the only agent that holds object-specific domain knowledge (kept as data/templates, not code — see `TRD.md` Section 5).

**Checklist templates (by object type):**
| Object | Critical | Supporting |
|---|---|---|
| Car | damage_visible_on_claimed_part, close_up_of_damage | full_vehicle_context_shot |
| Laptop | damage_visible_on_claimed_part, close_up_of_damage | device_model_or_serial_visible |
| Package | damage_visible, shipping_label_visible | contents_photo (only if conversation mentions contents damage) |

**Input:** the `ClaimFact` from Agent 1.

**Output (`RequiredEvidence[]`):**
```json
[
  {"id": "R1", "evidence_type": "damage_visible_on_claimed_part", "criticality": "critical", "satisfied": false},
  {"id": "R2", "evidence_type": "full_vehicle_context_shot", "criticality": "supporting", "satisfied": false},
  {"id": "R3", "evidence_type": "close_up_of_damage", "criticality": "critical", "satisfied": false}
]
```

---
## 3. Vision Analysis Agent
**Purpose:** Per image, detects the object, the part shown, any damage, its severity, and the model's own confidence.

**Input:** one image + `claim_id` + `object_type` (for context, not as a leading assumption — the agent must still report what it actually sees, including "no damage" or "wrong object").

**Output (`VisualFact`), one per image:**
```json
{
  "id": "V2",
  "image_id": "IMG-1042-2",
  "detected_object": "car",
  "detected_part": "rear_bumper",
  "detected_damage": ["dent", "paint_scrape"],
  "severity": "moderate",
  "confidence": 0.93
}
```
**Prompt strategy:** The agent is explicitly instructed *not* to assume the claimed damage is present — it must independently describe what it observes, then the Matching Agent (not this agent) compares it to the claim. This separation is what prevents the vision step from rubber-stamping the conversation.

---
## 4. Authenticity Agent
**Purpose:** Per image, flags signals that the image may be unreliable evidence — independent of whether damage is visible.

**Checks performed:**
- Blur (deterministic: Laplacian variance below threshold)
- Crop / framing irregularities (deterministic + LLM judgment)
- Duplicate image (deterministic: perceptual hash match against other images in the dataset, including images attached to *other* claims by the same user)
- Manipulation suspected (LLM visual judgment: inconsistent lighting/shadows, visible editing artifacts)

**Output (`AuthenticityFlag[]`), zero or more per image:**
```json
[]
```
(For `CLM-1042`, both images pass clean — empty array, as shown in `SYSTEM_DESIGN.md`'s worked example.)

Example of a non-empty case:
```json
[{"id": "A1", "image_id": "IMG-0917-1", "flag_type": "duplicate", "severity": "high"}]
```

---
## 5. Risk Agent
**Purpose:** Converts the `user_history.csv` row into weighted `RiskFact`s. Never touches images or the claim's damage description — strictly a history-to-risk-signal converter, which is what enforces the Key Principle architecturally (this agent has no path to write a `contradicts` or `satisfies` edge).

**Input:**
```json
{"user_id": "U-201", "prior_claims_count": 1, "prior_claims_same_object_type": 0, "prior_claims_same_part": 0, "account_age_days": 1095, "prior_fraud_flags": 0}
```
**Output (`RiskFact[]`):**
```json
[
  {"id": "K1", "risk_type": "prior_claims_count", "value": 1, "weight": 0.10},
  {"id": "K2", "risk_type": "account_age", "value": 1095, "weight": 0.0}
]
```
Weighting rubric: `prior_fraud_flags > 0` → weight 0.5 each (capped); `prior_claims_same_part ≥ 2` → weight 0.3; `account_age_days < 30` → weight 0.15; otherwise low/no weight. Weights feed only into the confidence formula in `SYSTEM_DESIGN.md` Section 4, never into the decision label.

---
## 6. Evidence Matching Agent
**Purpose:** The core deterministic comparison step. Reads the full Evidence Graph (all nodes above) and computes satisfaction, contradictions, and the Evidence Coverage Score. This is implemented as **rule-based code, not an LLM call** — see `SYSTEM_DESIGN.md` Section 3 for the exact algorithm.

**Input:** the full Evidence Graph for one claim.

**Output:**
```json
{
  "claim_id": "CLM-1042",
  "satisfied_required_evidence": ["R1", "R2", "R3"],
  "unsatisfied_required_evidence": [],
  "contradictions": [],
  "evidence_coverage_score": 1.0
}
```

---
## 7. Final Judge Agent
**Purpose:** Applies the Decision Engine rules (`SYSTEM_DESIGN.md` Section 4 — also rule-based, not a free LLM judgment) and generates the human-readable justification text. This is the *only* place an LLM call is used after the decision label is already fixed by rules — its job is strictly to phrase the "why," not to choose the "what."

**Input:** Matching Agent output + `RiskFact[]` + `ClaimFact`.

**Output:**
```json
{
  "claim_id": "CLM-1042",
  "decision": "SUPPORTED",
  "confidence": 0.91,
  "evidence_coverage_score": 1.0,
  "needs_manual_review": false,
  "justification": "Both submitted photos show a dent and paint scrape on the rear bumper consistent with the claimed damage (IMG-1042-2, confidence 0.93). All critical evidence requirements are satisfied. Claimant has one prior unrelated claim, which has minimal effect on confidence."
}
```
**Prompt strategy:** The justification prompt is given the already-decided label and the structured evidence as fixed facts, and instructed to cite specific node IDs/image IDs rather than free-form reasoning — this keeps the text grounded in the graph instead of letting the model "explain" a different decision than the one the rules actually produced.
