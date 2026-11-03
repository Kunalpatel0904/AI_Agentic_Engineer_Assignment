"""Combine findings into one decision. Precedence: REJECT > QUARANTINE > ACCEPT. Rule-based, never LLM-overridable."""
from validator import QUARANTINE, REJECT

ACCEPT = "ACCEPT"


def decide(findings):
    reject = [f for f in findings if f.status == REJECT]
    quar = [f for f in findings if f.status == QUARANTINE]
    if reject:
        return REJECT, _explain("Rejected", reject, quar)
    if quar:
        return QUARANTINE, _explain("Sent to human review", quar, [])
    return ACCEPT, "Accepted: all mandatory validations passed."


def _explain(head, main, also):
    txt = f"{head}: " + " ".join(f.message for f in main)
    if also:
        txt += " Additionally needs review: " + " ".join(f.message for f in also)
    return txt
