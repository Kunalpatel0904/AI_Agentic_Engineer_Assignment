"""CLI: python src/main.py [--inputs inputs] [--output output]"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from adjustment_agent import AdjustmentAgent  # noqa: E402
from audit_logger import setup_logging  # noqa: E402
from data_loader import data_quality_report, load_inputs  # noqa: E402


def run(inputs_dir, output_dir):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    setup_logging(out / "run.log")
    inp = load_inputs(inputs_dir)
    adj = inp["adjustments"]
    agent = AdjustmentAgent(inp["coa"], inp["fx"], adj["period"], adj["functional_currency"])
    results = agent.process_batch(adj["entries"])
    rows = [{"entry_id": r["entry_id"], "input_index": r["input_index"], "check": c["check"],
             "status": c["status"], "message": c["message"], "decision": r["decision"]}
            for r in results for c in r["checks"]]
    pd.DataFrame(rows).to_csv(out / "validation_results.csv", index=False)
    summary = dict(Counter(r["decision"] for r in results))
    (out / "decisions.json").write_text(json.dumps(
        {"period": adj["period"], "total": len(results), "summary": summary, "decisions": results},
        indent=2, default=str), encoding="utf-8")
    agent.audit.save(out / "audit_log.json")
    (out / "data_quality_report.json").write_text(json.dumps(data_quality_report(inp), indent=2), encoding="utf-8")
    return results, summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("--inputs", default=root / "inputs")
    ap.add_argument("--output", default=root / "output")
    a = ap.parse_args()
    res, summ = run(a.inputs, a.output)
    for r in res:
        print(f"{r['entry_id']}: {r['decision']:<10} {r['explanation'][:150]}")
    print(f"\nProcessed {len(res)} entries: {summ}")
