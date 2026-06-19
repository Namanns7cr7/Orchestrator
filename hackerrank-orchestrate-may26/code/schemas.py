"""
schemas.py — typed fact nodes for the Evidence Graph.

These are the support-ticket analogs of the claim-adjudication fact types in
AGENT_ARCHITECTURE.md / SYSTEM_DESIGN.md:

    ClaimFact          -> TicketFact          (what the user is asking)
    VisualFact         -> EvidencePassage     (retrieved KB passage = "evidence")
    AuthenticityFlag   -> PolicyFlag          (safety / scope / escalation signals)
    Evidence Coverage  -> Coverage            (how well the KB covers the ticket)
    final_decisions    -> Disposition         (status / request_type / response)

Every agent writes one of these into the EvidenceGraph; the rule-based
Resolution Engine reads the whole graph and emits a Disposition.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class TicketFact:
    """Normalized understanding of the incoming ticket (Agent 1)."""
    ticket_id: str
    company: str                  # raw Company field, normalized lower (or "none")
    issue: str
    subject: str
    query: str                    # combined issue + subject used for retrieval
    language: str = "en"          # detected language; non-en is a routing signal
    intent: str = "support_question"

    def to_node(self) -> dict[str, Any]:
        return {"type": "TicketFact", **asdict(self)}


@dataclass
class EvidencePassage:
    """A retrieved knowledge-base passage — the unit of evidence (Agent 2)."""
    id: str                       # e.g. "E1"
    doc_id: str                   # relative path of the source doc
    namespace: str                # claude | hackerrank | visa
    title: str
    score: float                  # normalized retrieval score 0..1
    url: str = ""
    snippet: str = ""

    def to_node(self) -> dict[str, Any]:
        return {"type": "EvidencePassage", **asdict(self)}


@dataclass
class PolicyFlag:
    """A safety / scope / escalation signal (Agent 3).

    flag_type ∈ {
        out_of_scope, pleasantry, outage, prompt_injection,
        account_action, financial_action, security_report, legal_or_safety,
        non_english
    }
    Mirrors AuthenticityFlag: these never *answer* the ticket, they only modify
    how it is routed (the Key Principle analog — evidence answers, flags route).
    """
    id: str
    flag_type: str
    severity: str                 # "low" | "high"
    detail: str = ""

    def to_node(self) -> dict[str, Any]:
        return {"type": "PolicyFlag", **asdict(self)}


@dataclass
class Coverage:
    """Rule-based evidence-coverage result (Agent 4 — deterministic)."""
    top_score: float
    coverage_level: str           # "sufficient" | "weak" | "none"
    supporting_doc_ids: list[str] = field(default_factory=list)

    def to_node(self) -> dict[str, Any]:
        return {"type": "Coverage", **asdict(self)}


@dataclass
class Disposition:
    """Final rule-based decision (Agent 5/6) — what lands in output.csv."""
    response: str
    product_area: str
    status: str                   # "Replied" | "Escalated"
    request_type: str             # "product_issue" | "bug" | "invalid"
    justification: str
    confidence: float = 0.0
    needs_manual_review: bool = False

    def to_node(self) -> dict[str, Any]:
        return {"type": "Disposition", **asdict(self)}


@dataclass
class EvidenceGraph:
    """The shared per-ticket structure all agents write into (SYSTEM_DESIGN §2)."""
    ticket_id: str
    ticket_fact: Optional[TicketFact] = None
    passages: list[EvidencePassage] = field(default_factory=list)
    flags: list[PolicyFlag] = field(default_factory=list)
    coverage: Optional[Coverage] = None
    disposition: Optional[Disposition] = None

    def to_audit(self) -> dict[str, Any]:
        """Serialize the full graph for the audit trail (agent_outputs)."""
        return {
            "ticket_id": self.ticket_id,
            "TicketFact": self.ticket_fact.to_node() if self.ticket_fact else None,
            "EvidencePassages": [p.to_node() for p in self.passages],
            "PolicyFlags": [f.to_node() for f in self.flags],
            "Coverage": self.coverage.to_node() if self.coverage else None,
            "Disposition": self.disposition.to_node() if self.disposition else None,
        }
