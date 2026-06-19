"""
main.py — evaluable entry point for the HackerRank Orchestrate submission.

Reads support_tickets/support_tickets.csv, runs every ticket through the
multi-agent Evidence-Graph pipeline, and writes support_tickets/output.csv
plus a full per-ticket reasoning trace (the `agent_outputs` audit log).

Usage:
    python code/main.py                      # run on support_tickets.csv
    python code/main.py --input PATH.csv     # run on a different ticket file
    python code/main.py --no-trace           # skip writing audit JSON files

The pipeline is deterministic and runs fully offline. If ANTHROPIC_API_KEY is
set, Claude (temperature=0) phrases the response text; the decision labels are
always rule-based, so output is reproducible across runs.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

# Allow running as `python code/main.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (  # noqa: E402
    AGENT_OUTPUTS_DIR,
    INPUT_TICKETS_CSV,
    OUTPUT_COLUMNS,
    OUTPUT_CSV,
    USE_LLM,
)
from knowledge_base import KnowledgeBase  # noqa: E402
from pipeline import TicketPipeline  # noqa: E402


def _read_tickets(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _col(row: dict, *names: str) -> str:
    """Case/space-insensitive column lookup."""
    norm = {k.strip().lower(): (v or "") for k, v in row.items() if k}
    for n in names:
        if n.lower() in norm:
            return norm[n.lower()].strip()
    return ""


def run(input_path: Path, write_trace: bool = True) -> list[dict]:
    print(f"Loading knowledge base ...", flush=True)
    kb = KnowledgeBase().load()
    print(f"  indexed {len(kb.docs)} documents "
          f"({', '.join(f'{ns}:{len(idxs)}' for ns, idxs in kb._by_namespace.items())})")
    print(f"LLM response synthesis: {'ON (Claude, temperature=0)' if USE_LLM else 'OFF (offline extractive)'}")

    pipeline = TicketPipeline(kb)
    tickets = _read_tickets(input_path)
    print(f"Processing {len(tickets)} tickets from {input_path.name} ...\n", flush=True)

    if write_trace:
        AGENT_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for i, t in enumerate(tickets, start=1):
        ticket_id = f"T-{i:03d}"
        issue = _col(t, "issue")
        subject = _col(t, "subject")
        company = _col(t, "company")

        graph = pipeline.process(ticket_id, issue, subject, company)
        d = graph.disposition
        rows.append({
            "issue": issue,
            "subject": subject,
            "company": company,
            "response": d.response,
            "product_area": d.product_area,
            "status": d.status,
            "request_type": d.request_type,
            "justification": d.justification,
        })

        if write_trace:
            (AGENT_OUTPUTS_DIR / f"{ticket_id}.json").write_text(
                json.dumps(graph.to_audit(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        flagrev = " *review" if d.needs_manual_review else ""
        print(f"  [{ticket_id}] {company or 'None':<10} -> "
              f"{d.status:<9} / {d.request_type:<13}{flagrev}")

    _write_output(rows)
    _print_summary(rows)
    return rows


def _write_output(rows: list[dict]) -> None:
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {len(rows)} rows -> {OUTPUT_CSV}")


def _print_summary(rows: list[dict]) -> None:
    print("\n=== Batch summary ===")
    by_status = Counter(r["status"] for r in rows)
    by_type = Counter(r["request_type"] for r in rows)
    print("  status:      " + ", ".join(f"{k}={v}" for k, v in by_status.items()))
    print("  request_type:" + " " + ", ".join(f"{k}={v}" for k, v in by_type.items()))
    print(f"  audit traces: {AGENT_OUTPUTS_DIR}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Support-ticket resolution agent")
    ap.add_argument("--input", type=Path, default=INPUT_TICKETS_CSV,
                    help="path to a tickets CSV (default: support_tickets.csv)")
    ap.add_argument("--no-trace", action="store_true",
                    help="do not write per-ticket audit JSON")
    args = ap.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input file not found: {args.input}")
    run(args.input, write_trace=not args.no_trace)


if __name__ == "__main__":
    main()
