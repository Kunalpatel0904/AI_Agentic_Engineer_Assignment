# Architecture

## 1. Scope
The product turns an ERP trial balance + manual adjustments + COA into four statements. This repo builds **one slice**: the **Manual Adjustments Agent**, which decides ACCEPT / REJECT / QUARANTINE for each unposted journal entry and explains why. The statement generator, mapper and reconciler are designed below but not built.

## 2. Agent topology (full product)
An **orchestrator with deterministic stages**, not a swarm: `Mapper -> Adjuster -> Statement Builder -> Verifier`. Each stage has a different reliability requirement (mapping is fuzzy; adjustment validation and statement arithmetic must be exact), so they are separate modules with typed hand-offs and a human-review queue between them. Inside each stage there is plain code with at most one LLM call. A single LLM-with-tools agent is rejected because it makes the audit trail the model's memory instead of the system's.

## 3. This prototype
```
manual_adjustments.json --> AdjustmentAgent --> Validator (ordered checks -> Findings)
coa / fx_rates          -->                 --> DecisionEngine (REJECT > QUARANTINE > ACCEPT)
                                            --> AuditLog (+ python logging)
                                            --> output/{validation_results.csv, decisions.json, audit_log.json}
```
| Module | Responsibility |
|---|---|
| `data_loader.py` | Reads inputs read-only; strict amount parsing; data-quality report on TB/COA/FX |
| `validator.py` | All checks; each returns `Finding(check, PASS/QUARANTINE/REJECT, message)` |
| `decision_engine.py` | Pure function: findings -> decision + plain-English explanation |
| `adjustment_agent.py` | Runs a batch; catches any validator exception and quarantines the entry (no silent drops) |
| `audit_logger.py` | Append-only event list (`received`, `check`, `decision`) with sequence numbers and UTC timestamps |

## 4. Python vs LLM
**Python (all of this prototype):** parsing, balance, account existence/postability, duplicate detection, period, FX-rate availability, decision precedence. These are exact, testable, and must be reproducible for an auditor.
**LLM (not wired in; optional):** (a) rewriting the template explanation into friendlier wording for a finance user; (b) *suggesting* a replacement account for a rejected unknown code (e.g. 6315 -> 6310 T&E) as a proposal a human must approve. The LLM receives the final decision as read-only input; nothing it returns can change a decision or post an entry. No API key or network call exists in the code.

## 5. Validation and decision process
Checks, all run for every entry so the CSV shows every outcome:

| Check | Fail result |
|---|---|
| Structure (object, >=2 line objects) | REJECT |
| Required header fields (id, description, date, source) | QUARANTINE |
| Date inside period (2024-Q4) | REJECT; unparseable date -> QUARANTINE |
| Amounts numeric, finite, non-negative, one side per line, non-zero | REJECT |
| Debits = credits (tolerance 0.005) | REJECT |
| Circular: same account on both sides | REJECT |
| Account in COA | REJECT |
| Account is not a Header | REJECT |
| Account missing, or cash-flow category `TBD` | QUARANTINE |
| Non-functional line currency without period-end rate | QUARANTINE |
| Posts to an `FX Gain/Loss` account (amount cannot be recomputed from inputs) | QUARANTINE |
| Duplicate id | REJECT; same date+lines under new id -> QUARANTINE |

Precedence: any REJECT -> REJECT (QUARANTINE findings are appended to the explanation); else any QUARANTINE -> QUARANTINE; else ACCEPT. REJECT means a mandatory accounting rule is violated; QUARANTINE means a person must supply or confirm information.

## 6. Error handling and human review
Malformed input never raises: bad types become findings. An unexpected exception becomes a QUARANTINE with `internal_error`. Quarantined entries are the human queue; the explanation says exactly what the reviewer must provide. Nothing is posted; this agent only classifies.

## 7. Traceability
Every row in `validation_results.csv` carries `entry_id` and `input_index` (position in the JSON). `decisions.json` embeds the untouched `source_entry` beside its checks and decision. `audit_log.json` gives a time-ordered `received -> check* -> decision` trail per entry. `output/run.log` mirrors it through Python logging. Inputs are never modified. Rerunning on the same inputs gives identical decisions (timestamps aside).

## 8. Findings on the supplied data (computed in `output/data_quality_report.json`)
TB: duplicate `6310/USD` row, orphan `9999` Suspense, raw debits - credits = -4,800 (and the multi-currency rows are not translated, so the true imbalance needs FX). Prior TB: orphan `6905` (a likely renamed/retired code of `6900`; not confirmed) and a 2.83M raw imbalance. FX: GBP has no `period_end` rate. COA: `1150` and `2170` have category `TBD`; `1290` is a Header with no children. Entries: JE-002 unbalanced, JE-005 unknown account 6315, JE-008 circular on 2170, JE-003 FX posting needs verification.

## 9. Assumptions
- Balance tolerance 0.005; period 2024-Q4 = 2024-10-01..2024-12-31.
- Entry lines without a `currency` are in the functional currency (USD).
- `TBD` cash-flow category means ambiguous mapping, so quarantine rather than reject.
- Posting to FX gain/loss accounts is quarantined because the revaluation base (which balances, opening vs period-end rate) is not specified; I did not guess a formula.
- Contra/normal-balance direction is not enforced (e.g. debiting a credit-normal account is legitimate).
- Exact-ID duplicates are rejected; same-content duplicates are only quarantined as they can be legitimate recurring entries.

## 10. Limitations and next steps
No approval-workflow persistence; no cross-check against the TB (e.g. whether an accrual exceeds the account balance); no materiality thresholds or approval limits (not in the assignment); revaluation recomputation; the LLM explainer/suggester; multi-entity and intercompany matching (JE-008 style entries should be matched against the counterparty's books, not just detected as self-offsetting).
