# Manual Adjustments Agent

Validates unposted manual journal entries (period 2024-Q4, USD) against a chart of accounts and FX rates, and decides **ACCEPT**, **REJECT** or **QUARANTINE** (human review) for each, with a plain-English reason. All accounting checks are deterministic Python; no LLM is called, and none could override a failed check. See [docs/architecture.md](docs/architecture.md) and [reflection.txt](reflection.txt).

## Features
Balance, amount validity, account existence/postability/mapping, circular entries, required fields, accounting period, FX-rate availability and FX-posting review, duplicates, malformed input handling, audit log, data-quality report on the TB/COA/FX inputs.

## Folder structure
```
inputs/        original data (never modified)
src/           data_loader, validator, decision_engine, adjustment_agent, audit_logger, main
tests/         pytest suite
output/        validation_results.csv, decisions.json, audit_log.json, data_quality_report.json, run.log
docs/          architecture.md
reflection.txt
```

## Install and run (Windows, Python 3.10+)
```
pip install -r requirements.txt
python src/main.py
```
Options: `--inputs <dir> --output <dir>`.

## Tests
```
python -m pytest -q
```

## Sample output (from the supplied data)
| Entry | Decision | Why |
|---|---|---|
| JE-001, 004, 006, 007, 009, 010 | ACCEPT | All checks passed |
| JE-002 | REJECT | Debits 28,500.00 != credits 25,000.00 (difference 3,500.00) |
| JE-005 | REJECT | Account 6315 is not in the chart of accounts |
| JE-008 | REJECT | Account 2170 is both debited and credited (circular); 2170 also has an unresolved cash-flow category |
| JE-003 | QUARANTINE | Posts to FX gain/loss 7310; the revaluation cannot be reproduced from the inputs, and GBP has no period-end rate |

Result: 10 processed, 6 ACCEPT, 3 REJECT, 1 QUARANTINE. Decision rules and assumptions are in the architecture doc.
