"""
config.py — central configuration, paths, and tunable thresholds.

All knobs that affect the deterministic decision engine live here so a reviewer
can audit and reproduce behaviour without grepping the agent code.
"""
from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths (resolved relative to the repo root, never hardcoded absolute paths)
# --------------------------------------------------------------------------- #
CODE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CODE_DIR.parent

DATA_DIR = REPO_ROOT / "data"
TICKETS_DIR = REPO_ROOT / "support_tickets"

INPUT_TICKETS_CSV = TICKETS_DIR / "support_tickets.csv"
SAMPLE_TICKETS_CSV = TICKETS_DIR / "sample_support_tickets.csv"
OUTPUT_CSV = TICKETS_DIR / "output.csv"

# Per-ticket reasoning traces (the audit log analog of the `agent_outputs` table
# in DATABASE_SCHEMA.md). One JSON file per ticket = full Evidence Graph.
AGENT_OUTPUTS_DIR = TICKETS_DIR / "agent_outputs"

# Knowledge-base namespaces. A ticket's `Company` selects which namespace to
# retrieve from first; "None"/unknown companies fall back to all namespaces.
KB_NAMESPACES = {
    "claude": DATA_DIR / "claude",
    "hackerrank": DATA_DIR / "hackerrank",
    "visa": DATA_DIR / "visa",
}

# --------------------------------------------------------------------------- #
# Output schema — fixed column order of output.csv (see DATABASE_SCHEMA.md).
# --------------------------------------------------------------------------- #
OUTPUT_COLUMNS = [
    "issue",
    "subject",
    "company",
    "response",
    "product_area",
    "status",
    "request_type",
    "justification",
]

# --------------------------------------------------------------------------- #
# Retrieval / Evidence-coverage thresholds (the support-ticket analog of the
# Evidence Coverage Score in SYSTEM_DESIGN.md §3).
# --------------------------------------------------------------------------- #
RETRIEVAL_TOP_K = 5          # passages pulled into the Evidence Graph per ticket
# Normalized BM25 top-passage score >= this means retrieval is "sufficient" to
# answer confidently from the knowledge base (analogous to ECS >= 0.8).
# Calibrated against the labeled sample-set score distribution.
EVIDENCE_SUFFICIENT_SCORE = 0.20
# Below this, coverage is too weak to ground an answer at all -> escalate.
EVIDENCE_WEAK_SCORE = 0.08

# --------------------------------------------------------------------------- #
# LLM configuration. The pipeline is fully deterministic and runs OFFLINE with
# no key; if a key is present it uses Claude (temperature=0) to synthesize the
# response text only — never to choose the status/request_type label, which is
# always rule-based (mirrors the "Decision Engine is rule-based" principle).
# --------------------------------------------------------------------------- #
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.environ.get("ORCHESTRATE_MODEL", "claude-opus-4-8")
LLM_TEMPERATURE = 0.0
LLM_MAX_TOKENS = 700
USE_LLM = bool(ANTHROPIC_API_KEY)

# Canonical fixed responses for non-answerable dispositions. These match the
# style observed in sample_support_tickets.csv ground-truth rows.
RESPONSE_OUT_OF_SCOPE = "I am sorry, this is out of scope from my capabilities"
RESPONSE_PLEASANTRY = "Happy to help"
RESPONSE_ESCALATE = "Escalate to a human"
