"""P2: patterns in one user's ledger. Plain arithmetic, every result cited.

Each function returns plain dicts carrying ``source_ids`` so the caller can
turn any number into a spoken, highlighted Fact.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List

from paisadost.dedupe import similar
from paisadost.loader import Ledger
from paisadost.models import Txn

# Money that leaves but is not "spending": own transfers, card bill payments, investing.
NOT_SPEND = {"Card payments", "Investments", "Transfers", "Income & refunds"}
WINDOW = 30


def _bank_txns(L: Ledger) -> List[Txn]:
    """Txns seen by a bank/card/email (CSV order rows describe the same money from the fund side)."""
    return [t for t in L.txns if t.source_ids[0].split(":")[0] in ("sms", "email")]


def spend_end(L: Ledger) -> date:
    """The last day bank messages cover: windows end here, not at as_of, or the data's tail looks like a freeze."""
    days = [t.on for t in _bank_txns(L) if t.on <= L.as_of]
    return max(days) if days else L.as_of


def spend_by_category(L: Ledger, days: int = WINDOW) -> Dict:
    end = spend_end(L)
    start = end - timedelta(days=days - 1)
    cats: Dict[str, Dict] = defaultdict(lambda: {"amount": 0.0, "count": 0, "source_ids": []})
    for t in _bank_txns(L):
        if t.direction == "debit" and start <= t.on <= end and t.category not in NOT_SPEND:
            c = cats[t.category]
            c["amount"] += t.amount; c["count"] += 1; c["source_ids"] += t.source_ids[:1]
    rows = sorted(({"category": k, **v, "amount": round(v["amount"], 2)} for k, v in cats.items()),
                  key=lambda r: -r["amount"])
    return {"from": start.isoformat(), "to": end.isoformat(), "total": round(sum(r["amount"] for r in rows), 2),
            "categories": rows}


def spend_vs_usual(L: Ledger) -> List[Dict]:
    """Last 30 days per category vs the average of the 30-day windows before it."""
    end = spend_end(L)
    first = min((t.on for t in _bank_txns(L)), default=end)
    windows = max(1, (end - first).days // WINDOW)
    per = defaultdict(lambda: [0.0] * (windows + 1))
    ids = defaultdict(list)
    for t in _bank_txns(L):
        if t.direction != "debit" or t.category in NOT_SPEND or t.on > end:
            continue
        w = (end - t.on).days // WINDOW
        if w <= windows:
            per[t.category][w] += t.amount
            if w == 0:
                ids[t.category] += t.source_ids[:1]
    out = []
    for cat, series in per.items():
        now, before = series[0], series[1:windows + 1]
        usual = statistics.mean(before) if before else 0.0
        if usual <= 0 and now <= 0:
            continue
        out.append({"category": cat, "last_30d": round(now, 2), "usual_30d": round(usual, 2),
                    "change_pct": round((now - usual) / usual * 100) if usual else None,
                    "excess": round(now - usual, 2), "source_ids": ids[cat][:12]})
    return sorted(out, key=lambda r: -abs(r["excess"]))


def recurring_charges(L: Ledger) -> List[Dict]:
    """Same payee, near-equal amount, at least three times on a steady rhythm."""
    groups: Dict[str, List[Txn]] = defaultdict(list)
    for t in _bank_txns(L):
        if t.direction == "debit" and t.merchant not in ("UPI transfer", "Unknown"):
            groups[t.merchant].append(t)
    out = []
    for merchant, ts in groups.items():
        ts.sort(key=lambda t: t.on)
        amounts = [t.amount for t in ts]
        mode = max(set(amounts), key=amounts.count)
        same = [t for t in ts if abs(t.amount - mode) <= max(1.0, mode * 0.05)]
        if len(same) < 3:
            continue
        gaps = [(b.on - a.on).days for a, b in zip(same, same[1:]) if (b.on - a.on).days > 0]
        if not gaps:
            continue
        gap = statistics.median(gaps)
        cadence = "daily" if gap <= 2 else "weekly" if gap <= 9 else "monthly" if 20 <= gap <= 40 else None
        if not cadence:
            continue
        span = max(30, (same[-1].on - same[0].on).days + 1)
        per_month = sum(t.amount for t in same) / span * 30
        per_day = len(same) / len({t.on for t in same})
        out.append({"merchant": merchant, "amount": mode, "cadence": cadence, "times": len(same),
                    "per_day": round(per_day, 1),
                    "per_month": round(per_month, 2), "last": same[-1].on.isoformat(),
                    "category": same[-1].category, "source_ids": [s for t in same[-3:] for s in t.source_ids[:1]]})
    return sorted(out, key=lambda r: -r["per_month"])


def dues_vs_balance(L: Ledger, within_days: int = 7) -> List[Dict]:
    """Unpaid dues (overdue, or due within N days of as_of) against the balance that will pay them."""
    total_bank = sum(b.amount for b in L.balances.values())
    out = []
    for d in sorted(L.dues, key=lambda d: d.due_date):
        if d.status not in ("upcoming", "overdue") or d.amount <= 0:
            continue
        days = (d.due_date - L.as_of).days
        if days > within_days or days < -30:
            continue
        bal = L.balances.get(d.account_ref)
        pay_from = bal or (max(L.balances.values(), key=lambda b: b.amount) if L.balances else None)
        out.append({"due_id": d.id, "title": d.title, "amount": d.amount, "due_date": d.due_date.isoformat(),
                    "days_left": days, "status": d.status, "account_ref": d.account_ref,
                    "balance_account": pay_from.account_ref if pay_from else None,
                    "balance": pay_from.amount if pay_from else None,
                    "balance_at": pay_from.at.date().isoformat() if pay_from else None,
                    "short_by": round(d.amount - pay_from.amount, 2) if pay_from and pay_from.amount < d.amount else 0,
                    "total_bank": round(total_bank, 2),
                    "source_ids": d.source_ids + (pay_from.source_ids if pay_from else []),
                    "source_label": d.source_label})
    return out


def card_utilisation(L: Ledger) -> List[Dict]:
    out = []
    for c in L.cards.values():
        if c.limit and c.limit > 0 and c.outstanding is not None:
            used = max(0.0, c.outstanding)
            out.append({"card": c.account_ref, "outstanding": used, "limit": c.limit,
                        "utilisation_pct": round(used / c.limit * 100, 1), "source_ids": c.source_ids,
                        "source_label": c.source_label})
        elif c.available is not None and c.outstanding is None:
            out.append({"card": c.account_ref, "outstanding": None, "limit": None, "available": c.available,
                        "utilisation_pct": None, "source_ids": c.source_ids, "source_label": c.source_label})
    known = [r for r in out if r["utilisation_pct"] is not None]
    if known:
        tot_out = sum(r["outstanding"] for r in known)
        tot_lim = sum(r["limit"] for r in known)
        out.append({"card": "ALL (known limits)", "outstanding": round(tot_out, 2), "limit": round(tot_lim, 2),
                    "utilisation_pct": round(tot_out / tot_lim * 100, 1),
                    "source_ids": [s for r in known for s in r["source_ids"]], "source_label": ""})
    return out


def duplicate_charges(L: Ledger) -> List[Dict]:
    """Two separate debits, same payee and amount, within a day: often a double charge."""
    debits = sorted((t for t in _bank_txns(L) if t.direction == "debit" and t.amount >= 50), key=lambda t: (t.on, t.amount))
    out, seen = [], set()
    for i, a in enumerate(debits):
        for b in debits[i + 1:i + 12]:
            if (b.on - a.on).days > 1:
                break
            if a.id in seen or b.id in seen or abs(a.amount - b.amount) > 0.01:
                continue
            if a.merchant in ("UPI transfer", "Unknown") or a.merchant != b.merchant:
                continue
            # A daily SIP debits the same amount every day by design; only same-day repeats count there.
            if a.on != b.on:
                continue
            seen |= {a.id, b.id}
            out.append({"merchant": a.merchant, "amount": a.amount, "on": a.on.isoformat(),
                        "txn_ids": [a.id, b.id], "source_ids": a.source_ids + b.source_ids,
                        "source_label": a.source_label})
    # A payee that bills twice on most days runs two plans by design; that is a recurring
    # pattern (reported there), not a double charge.
    per_payee = defaultdict(int)
    for d in out:
        per_payee[(d["merchant"], d["amount"])] += 1
    return [d for d in out if per_payee[(d["merchant"], d["amount"])] <= 2]


ONE_OFF = 25000


def monthly_outflow(L: Ledger) -> float:
    """Average everyday spend per 30 days (excludes investing, own transfers and one-off payments ≥ ₹25k)."""
    txns = [t for t in _bank_txns(L) if t.direction == "debit" and t.category not in NOT_SPEND and t.amount < ONE_OFF]
    if not txns:
        return 0.0
    span = max(WINDOW, (spend_end(L) - min(t.on for t in txns)).days + 1)
    return round(sum(t.amount for t in txns) / span * 30, 2)


def credit_enquiries(L: Ledger, days: int = 90) -> Dict:
    """Hard enquiries: each lender that pulled the credit report. Many in a short span lowers the score."""
    since = L.as_of - timedelta(days=days)
    rows = [e for e in getattr(L, "enquiries", []) if e["on"] >= since]
    lenders = sorted({e["lender"] for e in rows})
    last30 = [e for e in rows if e["on"] >= L.as_of - timedelta(days=30)]
    return {"count": len(rows), "days": days, "count_30d": len(last30), "lenders": lenders,
            "last": max((e["on"] for e in rows), default=None),
            "source_ids": [e["source_id"] for e in rows]}


def analyze(L: Ledger) -> Dict:
    return {"as_of": L.as_of.isoformat(), "spend_end": spend_end(L).isoformat(),
            "spend_by_category": spend_by_category(L), "spend_vs_usual": spend_vs_usual(L),
            "recurring": recurring_charges(L), "dues_vs_balance": dues_vs_balance(L),
            "card_utilisation": card_utilisation(L), "duplicates": duplicate_charges(L),
            "monthly_outflow": monthly_outflow(L), "enquiries": credit_enquiries(L)}
