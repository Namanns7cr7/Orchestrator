# Implementation Plan

Assumes a 36-hour hackathon build window with a small team (2-4 people). Time estimates are wall-clock, assuming parallel work where noted.

| Phase | Tasks | Owner-able in parallel? | Est. time |
|---|---|---|---|
| **1. Data Layer** | Define CSV/image loading, set up SQLite schema (`DATABASE_SCHEMA.md`), write seed/sample data for car/laptop/package. | Yes — independent of agent logic | 2 hrs |
| **2. Claim Understanding** | Build Claim Understanding Agent, JSON schema validation, retry logic. | Yes | 2 hrs |
| **3. Vision Pipeline** | Build Vision Analysis Agent + Authenticity Agent (deterministic blur/hash checks first, then LLM manipulation check). | Yes (separate from Phase 2) | 4 hrs |
| **4. Evidence Graph** | Implement graph data structure (nodes/edges from `SYSTEM_DESIGN.md` Section 2), wire in outputs from Phases 2 & 3. | No — depends on 2 & 3 | 3 hrs |
| **5. Matching Engine** | Implement rule-based matching algorithm + Evidence Coverage Score (`SYSTEM_DESIGN.md` Section 3). | No — depends on 4 | 3 hrs |
| **6. Risk Engine** | Build Risk Agent, weighting rubric (`AGENT_ARCHITECTURE.md` Section 5). | Yes — independent of 3, 4, 5 | 2 hrs |
| **7. Judge Agent** | Implement Decision Engine rules (`SYSTEM_DESIGN.md` Section 4) + justification generation. | No — depends on 5 & 6 | 2 hrs |
| **8. Evaluation** | Build accuracy scoring against labeled set, ablation harness (`EVALUATION_AND_EXPERIMENTS.md`). | Yes, once Phase 7 produces decisions | 3 hrs |
| **9. CSV Generation** | Wire up `output.csv` export, error-handling paths from `APP_FLOW.md`. | No — depends on 7 | 1 hr |
| **10. Submission Packaging** | Run full batch, generate evaluation reports, package agent logs + chat transcripts, write demo script. | No — final step | 2 hrs |
| | | **Total** | **~24 hrs** (leaves ~12 hrs buffer for debugging, demo prep, sleep) |

## MVP Cutline (what to drop first if time runs short)
If the clock is tight, cut in this order — each item degrades gracefully rather than breaking the pipeline:

1. **Authenticity Agent → deterministic checks only.** Drop the LLM manipulation-detection pass; keep blur/duplicate-hash checks (cheap, still meaningful for the demo).
2. **Ablation studies (Phase 8).** Run accuracy eval only; skip "without Risk Agent / without Authenticity Agent" comparisons if time is short — these strengthen the writeup but aren't required for the system to work.
3. **Package object type.** Build Car and Laptop fully; treat Package as a stretch goal — the architecture is dataset-agnostic (per `TRD.md`) so adding it later is mostly checklist-template work, not new code.
4. **Manual review flagging UI.** The `needs_manual_review` field still gets computed and written to `output.csv`; just skip building any UI to surface it.

**Never cut:** the Decision Engine being rule-based (Phase 7) and the audit log (`agent_outputs` table) — these are the explainability differentiators the PRD's success metrics depend on.

## Suggested team split (4 people)
- **Person A:** Phases 1, 4, 5 (data layer → graph → matching engine — the core architecture spine).
- **Person B:** Phase 3 (vision + authenticity).
- **Person C:** Phases 2, 6, 7 (claim understanding, risk, judge).
- **Person D:** Phases 8, 9, 10 (evaluation, output, packaging) — can start building the evaluation harness against mocked decisions before Phase 7 is finished, then wire in real output once ready.

## Demo readiness checklist
- [ ] At least one fully worked example per object type (car/laptop minimum) shown end-to-end with the Evidence Graph visualized.
- [ ] One `SUPPORTED`, one `CONTRADICTED`, and one `INSUFFICIENT_EVIDENCE` example ready to walk through live.
- [ ] Reproducibility demo: run the same claim twice, show identical output.
- [ ] Ablation result ready to cite verbally even if not in slides (e.g. "accuracy drops X% without the Authenticity Agent").
