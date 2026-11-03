"""Orchestrates validation -> decision -> audit for a batch of manual journal entries."""
from audit_logger import AuditLog
from decision_engine import decide
from validator import QUARANTINE, Finding, Validator


class AdjustmentAgent:
    def __init__(self, coa, fx, period, functional_currency):
        self.validator = Validator(coa, fx, period, functional_currency)
        self.audit = AuditLog()

    def process_entry(self, entry, index):
        is_obj = isinstance(entry, dict)
        eid = entry.get("id") if is_obj else None
        key = eid or f"<entry #{index}>"
        self.audit.record(key, "received", index=index)
        try:
            findings = self.validator.validate(entry)
        except Exception as ex:  # never drop a record silently: unexpected failure -> human review
            findings = [Finding("internal_error", QUARANTINE, f"Validator error: {ex!r}")]
        decision, explanation = decide(findings)
        for f in findings:
            self.audit.record(key, "check", check=f.check, status=f.status, message=f.message)
        self.audit.record(key, "decision", decision=decision, explanation=explanation)
        return {"input_index": index, "entry_id": eid,
                "description": entry.get("description") if is_obj else None,
                "decision": decision, "explanation": explanation,
                "checks": [f.__dict__ for f in findings], "source_entry": entry}

    def process_batch(self, entries):
        return [self.process_entry(e, i) for i, e in enumerate(entries)]
