"""
evaluate.py — accuracy harness against the labeled sample set.

sample_support_tickets.csv carries ground-truth Status and Request Type
columns. This script runs the pipeline on those tickets and reports
classification accuracy plus a confusion matrix — the support-ticket analog
of the Decision Accuracy metric in EVALUATION_AND_EXPERIMENTS.md §2.

Usage:
    python code/evaluate.py
"""
from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import SAMPLE_TICKETS_CSV  # noqa: E402
from knowledge_base import KnowledgeBase  # noqa: E402
from pipeline import TicketPipeline  # noqa: E402


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def evaluate() -> None:
    kb = KnowledgeBase().load()
    pipeline = TicketPipeline(kb)

    with SAMPLE_TICKETS_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    status_correct = type_correct = total = 0
    status_cm: dict = defaultdict(Counter)   # truth -> predicted counts
    type_cm: dict = defaultdict(Counter)
    misses: list[str] = []

    for i, r in enumerate(rows, start=1):
        issue = (r.get("Issue") or "").strip()
        subject = (r.get("Subject") or "").strip()
        company = (r.get("Company") or "").strip()
        gt_status = _norm(r.get("Status"))
        gt_type = _norm(r.get("Request Type"))
        if not gt_status and not gt_type:
            continue
        total += 1

        g = pipeline.process(f"S-{i:03d}", issue, subject, company)
        pred_status = _norm(g.disposition.status)
        pred_type = _norm(g.disposition.request_type)

        # Ground-truth "Escalated" vs our "Escalated"; "Replied" vs "Replied".
        if pred_status == gt_status:
            status_correct += 1
        if pred_type == gt_type:
            type_correct += 1
        else:
            misses.append(
                f"  [{i}] {(subject or issue)[:48]!r}\n"
                f"        type  truth={gt_type:<14} pred={pred_type}\n"
                f"        status truth={gt_status:<13} pred={pred_status}")
        status_cm[gt_status][pred_status] += 1
        type_cm[gt_type][pred_type] += 1

    print(f"\n=== Evaluation on {total} labeled tickets ===")
    print(f"  Status accuracy:       {status_correct}/{total} "
          f"= {status_correct / total:.0%}")
    print(f"  Request-type accuracy: {type_correct}/{total} "
          f"= {type_correct / total:.0%}")

    print("\n  Request-type confusion (truth -> predicted):")
    for truth in sorted(type_cm):
        preds = ", ".join(f"{p}:{c}" for p, c in type_cm[truth].most_common())
        print(f"    {truth:<14} -> {preds}")

    if misses:
        print(f"\n  Misclassified request_type ({len(misses)}):")
        print("\n".join(misses))


if __name__ == "__main__":
    evaluate()
