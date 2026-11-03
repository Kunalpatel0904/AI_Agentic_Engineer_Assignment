"""Deterministic validation checks. Each check returns Findings; none depend on an LLM."""
from dataclasses import dataclass
from datetime import date

from data_loader import to_decimal

PASS, QUARANTINE, REJECT = "PASS", "QUARANTINE", "REJECT"
TOLERANCE = 0.005  # Assumption: balance tolerance of half a cent
FX_ACCOUNT_PREFIX = "FX Gain/Loss"


@dataclass
class Finding:
    check: str
    status: str
    message: str


def parse_period(period):
    """'2024-Q4' -> (date(2024,10,1), date(2024,12,31))."""
    y, q = str(period).split("-Q")
    y, q = int(y), int(q)
    if q not in (1, 2, 3, 4):
        raise ValueError(period)
    start = date(y, 3 * q - 2, 1)
    nxt = date(y + 1, 1, 1) if q == 4 else date(y, 3 * q + 1, 1)
    return start, date.fromordinal(nxt.toordinal() - 1)


def _pos(v):
    try:
        return to_decimal(v) > 0
    except ValueError:
        return False


class Validator:
    def __init__(self, coa, fx, period, functional_currency):
        self.coa = {r.account_code: r for r in coa.itertuples()}
        self.fx = {(r.currency, r.rate_type): r.rate for r in fx.itertuples()}
        self.period_start, self.period_end = parse_period(period)
        self.period = period
        self.func = functional_currency
        self.seen_ids = {}
        self.seen_sigs = {}

    def check_structure(self, e):
        if not isinstance(e, dict):
            return [Finding("structure", REJECT, "Entry is not a JSON object.")], None
        lines = e.get("lines")
        if not isinstance(lines, list) or not lines:
            return [Finding("structure", REJECT, "Entry has no journal lines.")], None
        if len(lines) < 2 or not all(isinstance(l, dict) for l in lines):
            return [Finding("structure", REJECT,
                            "A journal entry needs at least two lines, each a JSON object.")], None
        miss = [k for k in ("id", "description", "date", "source") if not str(e.get(k) or "").strip()]
        if miss:
            return [Finding("required_fields", QUARANTINE,
                            f"Missing required field(s): {', '.join(miss)}. A person must supply them.")], lines
        return [Finding("required_fields", PASS, "All header fields present.")], lines

    def check_amounts(self, lines):
        """Returns (findings, parsed [(debit, credit)] or None)."""
        bad, parsed = [], []
        for i, ln in enumerate(lines, 1):
            try:
                d, c = to_decimal(ln.get("debit", 0)), to_decimal(ln.get("credit", 0))
            except ValueError as ex:
                bad.append(f"line {i}: {ex}")
                continue
            if d < 0 or c < 0:
                bad.append(f"line {i}: negative amount (debit={d}, credit={c})")
            elif d > 0 and c > 0:
                bad.append(f"line {i}: has both a debit and a credit")
            elif d == 0 and c == 0:
                bad.append(f"line {i}: zero amount")
            parsed.append((d, c))
        if bad:
            return [Finding("amounts", REJECT, "Invalid amount(s): " + "; ".join(bad))], None
        return [Finding("amounts", PASS, "All line amounts are valid positive numbers.")], parsed

    def check_balance(self, parsed):
        d, c = sum(p[0] for p in parsed), sum(p[1] for p in parsed)
        if abs(d - c) > TOLERANCE:
            return Finding("balance", REJECT,
                           f"Debits ({d:,.2f}) do not equal credits ({c:,.2f}); difference {d - c:,.2f}. "
                           "Correct the amounts so total debits equal total credits.")
        return Finding("balance", PASS, f"Debits equal credits ({d:,.2f}).")

    def check_accounts(self, lines):
        out, unknown, headers, tbd, nocode = [], [], [], [], []
        for i, ln in enumerate(lines, 1):
            code = str(ln.get("account") or "").strip()
            if not code:
                nocode.append(i)
                continue
            acct = self.coa.get(code)
            if acct is None:
                unknown.append(code)
            elif acct.account_type == "Header":
                headers.append(code)
            elif acct.cf_category == "TBD":
                if f"{code} ({acct.account_name})" not in tbd:
                    tbd.append(f"{code} ({acct.account_name})")
        if nocode:
            out.append(Finding("account_missing", QUARANTINE, f"Line(s) {nocode} have no account code."))
        if unknown:
            out.append(Finding("account_exists", REJECT,
                               f"Account(s) {sorted(set(unknown))} are not in the chart of accounts. "
                               "Map to a valid account (or add it to the COA) and resubmit."))
        if headers:
            out.append(Finding("account_postable", REJECT,
                               f"Account(s) {sorted(set(headers))} are header/summary accounts and cannot be posted to."))
        if tbd:
            out.append(Finding("account_mapping", QUARANTINE,
                               f"Account(s) {tbd} have an unresolved cash-flow category ('TBD') in the COA; "
                               "a human must confirm the classification."))
        if not (unknown or headers or tbd or nocode):
            out.append(Finding("accounts", PASS, "All accounts exist, are postable and fully mapped."))
        return out

    def check_circular(self, lines):
        deb = {str(l.get("account")) for l in lines if _pos(l.get("debit"))}
        cre = {str(l.get("account")) for l in lines if _pos(l.get("credit"))}
        both = deb & cre
        if both:
            return Finding("circular", REJECT,
                           f"Account(s) {sorted(both)} appear on both the debit and credit side; the entry nets to "
                           "zero effect on them (circular/self-offsetting).")
        return Finding("circular", PASS, "No account is both debited and credited.")

    def check_period(self, e):
        raw = e.get("date")
        try:
            d = date.fromisoformat(str(raw))
        except ValueError:
            return Finding("period", QUARANTINE, f"Entry date {raw!r} is missing or not a valid YYYY-MM-DD date.")
        if not self.period_start <= d <= self.period_end:
            return Finding("period", REJECT, f"Entry date {d} is outside period {self.period} "
                           f"({self.period_start} to {self.period_end}).")
        return Finding("period", PASS, f"Date {d} is within {self.period}.")

    def check_fx(self, lines):
        out, issues, fxacc = [], [], []
        for i, ln in enumerate(lines, 1):
            ccy = str(ln.get("currency") or self.func).upper()
            if ccy != self.func and (ccy, "period_end") not in self.fx:
                issues.append(f"line {i}: no period_end FX rate for {ccy}")
            acct = self.coa.get(str(ln.get("account")))
            if acct is not None and acct.account_name.startswith(FX_ACCOUNT_PREFIX):
                fxacc.append(str(ln.get("account")))
        if issues:
            out.append(Finding("fx_rate", QUARANTINE, "; ".join(issues) +
                               f". Cannot translate to {self.func}; supply the rate."))
        if fxacc:
            ccys = {c for c, _ in self.fx if c != self.func}
            no_end = sorted(c for c in ccys if (c, "period_end") not in self.fx)
            extra = f" Note: no period_end rate is available for {no_end}." if no_end else ""
            out.append(Finding("fx_revaluation", QUARANTINE,
                               f"Entry posts to FX gain/loss account(s) {sorted(set(fxacc))}; the amount cannot be "
                               f"reproduced from the supplied inputs, so a person must verify the revaluation.{extra}"))
        if not out:
            out.append(Finding("fx", PASS, "No FX translation or revaluation required."))
        return out

    def check_duplicate(self, e, lines):
        eid = e.get("id")
        sig = (str(e.get("date")), tuple(sorted((str(l.get("account")), str(l.get("debit")), str(l.get("credit")))
                                                 for l in lines)))
        if eid in self.seen_ids:
            return Finding("duplicate", REJECT, f"Entry id {eid} was already processed in this batch.")
        if sig in self.seen_sigs:
            return Finding("duplicate", QUARANTINE,
                           f"Same date and lines as {self.seen_sigs[sig]}; possible duplicate under a new id.")
        self.seen_ids[eid] = True
        self.seen_sigs[sig] = eid
        return Finding("duplicate", PASS, "Not a duplicate.")

    def validate(self, e):
        findings, lines = self.check_structure(e)
        if lines is None:
            return findings
        findings.append(self.check_period(e))
        f, parsed = self.check_amounts(lines)
        findings += f
        if parsed is not None:
            findings.append(self.check_balance(parsed))
            findings.append(self.check_circular(lines))
        findings += self.check_accounts(lines)
        findings += self.check_fx(lines)
        findings.append(self.check_duplicate(e, lines))
        return findings
