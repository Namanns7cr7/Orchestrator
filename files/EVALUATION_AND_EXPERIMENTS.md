# Evaluation and Experiments

## 1. Ground Truth
Each claim in the demo/eval set needs a human-labeled `ground_truth_decision` (`SUPPORTED` / `CONTRADICTED` / `INSUFFICIENT_EVIDENCE`) plus, where applicable, ground-truth `damage_type`, `part`, and `severity` for the per-field accuracy metrics below. For the hackathon, this is a small (~30-50 claim) hand-labeled set covering all three object types, constructed alongside the sample data in Implementation Plan Phase 1 — labeled by a team member who did **not** write the agent prompts, to avoid label bias toward the system's own outputs.

## 2. Metrics (with formulas)

### Decision Accuracy
```
Decision Accuracy = (# claims where system.decision == ground_truth.decision) / (total claims)
```
Reported overall and broken down by object_type and by ground-truth decision label (a confusion matrix across the 3 labels is more informative than the single accuracy number — e.g. it surfaces if the system is biased toward `INSUFFICIENT_EVIDENCE` as a "safe" default).

### Damage Accuracy
```
Damage Accuracy = (# images where VisualFact.detected_damage matches ground_truth.damage_type) / (total labeled images)
```
Use set-overlap (Jaccard similarity) rather than exact match, since a claim can have multiple damage types.

### Part Accuracy
```
Part Accuracy = (# images where VisualFact.detected_part == ground_truth.part) / (total labeled images)
```

### Severity Accuracy
```
Severity Accuracy = (# images where VisualFact.severity == ground_truth.severity) / (total labeled images)
```
Reported both as exact match and as "within one severity tier" (e.g. predicting `moderate` when truth is `severe` is a smaller error than predicting `none`).

### Risk Flag Accuracy
```
Risk Flag Accuracy = (# claims where system needs_manual_review flag matches a human reviewer's judgment of "this warrants a second look") / (total claims)
```
Requires a separate small reviewer pass specifically on the manual-review flag, since it's not the same as decision correctness — a claim can be correctly `SUPPORTED` and still reasonably flagged for review due to risk history.

## 3. Baseline to Beat
Before claiming the multi-agent system is "good," compare against a trivial baseline: **a single-prompt LLM call** given the full claim (conversation + images + history concatenated) asked to directly output a decision. This baseline:
- Has no Evidence Graph, no checklist, no separation of concerns.
- Is expected to perform reasonably on clear-cut cases but to (a) struggle to explain *which* evidence drove the decision, and (b) be more likely to let user history override clear visual evidence — which is exactly the failure mode the Key Principle in `PRD.md` is designed to prevent.
- Decision Accuracy and Explainability (per `PRD.md` Section 9) should both be measured for this baseline so the architecture's value-add is quantified, not just asserted.

## 4. Experiments
| Experiment | What it tests | How to run it |
|---|---|---|
| **Single Agent vs Multi-Agent** | Does decomposing into 7 specialized agents actually outperform the single-prompt baseline (Section 3)? | Run both pipelines on the same labeled set, compare Decision Accuracy + manual review of justification quality. |
| **Evidence Graph Impact** | Does routing through the structured graph + rule-based Matching/Decision Engine improve reproducibility and accuracy over letting an LLM directly read the agent outputs and decide? | Variant pipeline: same 7 agents, but replace the rule-based Decision Engine (`SYSTEM_DESIGN.md` Section 4) with a single LLM call given all agent outputs as context. Compare reproducibility (Section 5 below) between the two. |
| **Prompt Comparison** | Sensitivity of each agent to prompt phrasing — e.g. does explicitly telling the Vision Agent "don't assume the claimed damage is present" (`AGENT_ARCHITECTURE.md` Section 3) measurably reduce false `SUPPORTED` decisions vs. a more leading prompt? | A/B the Vision Agent prompt on the same image set; compare Damage/Part Accuracy and contradiction-detection rate. |
| **Model Comparison** | How much of performance depends on the specific multimodal model used for Vision/Claim/Judge agents. | Swap models (e.g. Claude Sonnet vs Haiku) for the Vision Analysis Agent specifically, holding everything else fixed; compare Damage/Part/Severity Accuracy and latency. |

## 5. Ablation Studies
For each ablation, measure Decision Accuracy and the confusion matrix on the same labeled set, and report the delta vs. the full pipeline.

| Ablation | Implementation | Expected effect |
|---|---|---|
| **Without Risk Agent** | Skip Step 7 in `APP_FLOW.md`; Decision Engine runs with no `RiskFact`s (confidence formula's `risk_adjustment = 0`). | Decision label distribution should be **unchanged** (Key Principle: risk only adjusts confidence) — if it changes, that's a bug, not just a metric drop. Confidence scores and manual-review flag rates will shift. |
| **Without Authenticity Agent** | Skip Step 6; all `VisualFact`s used at full confidence with no `discounts` edges. | Expect more false `SUPPORTED`/`CONTRADICTED` decisions on low-quality (blurry/duplicate) images, since unreliable evidence is no longer down-weighted. |
| **Without Evidence Graph** | Use the "single LLM call given raw agent outputs" variant from Section 4's Evidence Graph Impact experiment. | Expect a drop in reproducibility (same input, different output across runs) and weaker, less specific justifications. |

## 6. Reproducibility Measurement
Run the full pipeline **3 times** on the same labeled set with no changes to inputs.
```
Reproducibility = (# claims with identical decision label across all 3 runs) / (total claims)
```
Target: 100%, per `PRD.md` Section 9. Any claim that flips labels across runs should be individually inspected — likely cause is either a non-zero effective temperature somewhere in the pipeline, or a borderline ECS score sitting exactly at the 0.8 threshold (`SYSTEM_DESIGN.md` Section 4), which is itself useful information to report.

## 7. Failure Analysis
Document every false positive and false negative from the Decision Accuracy confusion matrix using a consistent template:

```
Claim ID:
Ground truth: <label>      System output: <label>
Evidence Coverage Score:
Contradictions found:
Likely root cause: [vision misdetection / missing evidence requirement / authenticity false flag /
                     risk over-weighting / ambiguous ground truth / other]
Which agent's output, if corrected, would have fixed this?
```

Group failures by root cause category and report counts — this turns "we got 82% accuracy" into an actionable list (e.g. "6 of 9 errors traced to the Vision Agent under-detecting minor scratches," which is a concrete, fixable finding to present at the demo rather than a single opaque accuracy number).
