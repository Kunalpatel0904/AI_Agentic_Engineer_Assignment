"""Audit trail: every event goes to Python logging (output/run.log) and an in-memory list saved as audit_log.json."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("adjustment_agent")


class AuditLog:
    def __init__(self):
        self.events = []

    def record(self, entry_id, event, **detail):
        ev = {"seq": len(self.events) + 1, "ts": datetime.now(timezone.utc).isoformat(),
              "entry_id": entry_id, "event": event, **detail}
        self.events.append(ev)
        log.info("%s %s %s", entry_id, event, detail)

    def save(self, path):
        Path(path).write_text(json.dumps(self.events, indent=2, default=str), encoding="utf-8")


def setup_logging(log_file):
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(log_file, mode="w", encoding="utf-8")], force=True)
