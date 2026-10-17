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
    # Only money that left an account or card (a bank/card debit) can be charged twice;
    # merchant receipts and confirmations are acknowledgements, not separate debits.
    debits = sorted((t for t in _bank_txns(L) if t.direction == "debit" and t.amount >= 50 and t.account_ref
                     and t.type in ("upi", "card", "transfer", "autopay", "neft")), key=lambda t: (t.on, t.amount))
    out, seen = [], set()
    for i, a in enumerate(debits):
        for b in debits[i + 1:i + 12]:
            if (b.on - a.on).days > 1:
                break
            if a.id in seen or b.id in seen or abs(a.amount - b.amount) > 0.01:
                continue
            first = (L.name.split() or [""])[0].lower()
            if a.merchant in ("UPI transfer", "Unknown") or a.merchant != b.merchant or "transfer" in a.merchant.lower() \
                    or (first and first in a.merchant.lower()):   # own-account moves are not charges
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


def forecast(L: Ledger, days: int = 30) -> Dict:
    """Bank balance, day by day, from the last known balance to as_of + ``days``.

    Only known, repeating money moves: recurring debits on their rhythm, recurring
    credits likewise, and dated dues. Irregular spending is not guessed, so the
    curve is the floor of what is already committed, not a prediction of everything.
    """
    if not L.balances:
        return {"series": [], "note": "no bank balance in the messages"}
    start_bal = sum(b.amount for b in L.balances.values())
    start = max(b.at.date() for b in L.balances.values())
    end = L.as_of + timedelta(days=days)
    events: Dict[date, List[Dict]] = defaultdict(list)

    def rhythm(rows, sign):
        for r in rows:
            last = date.fromisoformat(r["last"])
            step = {"daily": 1, "weekly": 7, "monthly": 30}[r["cadence"]]
            per = max(1, round(r.get("per_day", 1))) if r["cadence"] == "daily" else 1
            d = last + timedelta(days=step)
            while d <= end:
                if d > start:
                    events[d].append({"what": r["merchant"], "amount": sign * r["amount"] * per, "kind": "recurring",
                                      "source_ids": r["source_ids"][:2]})
                d += timedelta(days=step)

    rhythm(recurring_charges(L), -1)
    # Expected income: the regular monthly income, on the day it usually arrives.
    cf = cashflow(L)
    if cf.get("income"):
        payday = income_day(L)
        inc_ids = [i for r in cf["income_items"] for i in r["source_ids"]][:4]
        y, m = start.year, start.month
        while True:
            try:
                d = date(y, m, min(payday, 28))
            except ValueError:
                d = date(y, m, 28)
            if d > end:
                break
            if d > start:
                events[d].append({"what": "Expected income", "amount": cf["income"], "kind": "income", "source_ids": inc_ids})
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    for d in L.dues:
        if d.status in ("upcoming", "overdue") and d.amount > 0 and d.kind not in ("sip", "mandate"):
            when = max(d.due_date, start + timedelta(days=1))
            if when <= end:
                events[when].append({"what": d.title, "amount": -d.amount, "kind": "due", "source_ids": d.source_ids[:2]})

    series, bal, low = [], start_bal, None
    day = start
    while day <= end:
        todays = events.get(day, [])
        bal += sum(e["amount"] for e in todays)
        point = {"date": day.isoformat(), "balance": round(bal, 2), "events": todays}
        series.append(point)
        if low is None or bal < low["balance"]:
            low = point
        day += timedelta(days=1)
    first_short = next((p for p in series if p["balance"] < 0), None)
    return {"start": start.isoformat(), "start_balance": round(start_bal, 2), "end": end.isoformat(),
            "series": series, "lowest": low, "first_negative": first_short,
            "committed_out": round(sum(-e["amount"] for p in series for e in p["events"] if e["amount"] < 0), 2),
            "committed_in": round(sum(e["amount"] for p in series for e in p["events"] if e["amount"] > 0), 2),
            "source_ids": [s for b in L.balances.values() for s in b.source_ids],
            "monthly_income": cf.get("income", 0), "income_day": income_day(L) if cf.get("income") else None,
            "note": "Known money only: your usual monthly income on its usual day, repeating charges and dated bills; one-off spending is not guessed."}


def _recurring_credits(L: Ledger) -> List[Dict]:
    """Money that comes in on a rhythm (salary, payouts): same payer, similar amount, 3+ times."""
    groups: Dict[str, List[Txn]] = defaultdict(list)
    for t in _bank_txns(L):
        if t.direction == "credit" and t.merchant not in ("UPI transfer", "Unknown", "UPI credit") and t.type != "card_payment":
            groups[t.merchant].append(t)
    out = []
    for merchant, ts in groups.items():
        ts.sort(key=lambda t: t.on)
        if len(ts) < 3:
            continue
        gaps = [(b.on - a.on).days for a, b in zip(ts, ts[1:]) if (b.on - a.on).days > 0]
        if not gaps:
            continue
        gap = statistics.median(gaps)
        cadence = "weekly" if 5 <= gap <= 9 else "monthly" if 25 <= gap <= 35 else None
        if not cadence:
            continue
        amt = statistics.median(t.amount for t in ts)
        out.append({"merchant": merchant, "amount": round(amt, 2), "cadence": cadence, "last": ts[-1].on.isoformat(),
                    "source_ids": [t.source_ids[0] for t in ts[-2:]]})
    return out


LARGE_DEPOSIT = 5000


def cashflow(L: Ledger) -> Dict:
    """Monthly money in (large deposits) vs fixed money out (EMIs, premiums, SIPs, repeating bills).

    Income = deposits of ₹5,000+ into bank accounts, averaged over the months bank
    messages cover (card refunds, card-bill credits and small UPI receipts are left out).
    Fixed = what repeats every month: loan EMIs and insurance premiums actually paid,
    plus recurring charges on their rhythm.
    """
    txns = _bank_txns(L)
    if not txns:
        return {"months": 0}
    end = spend_end(L)
    first = min(t.on for t in txns)
    months = max(1.0, ((end - first).days + 1) / 30)

    deposits = [t for t in txns if t.direction == "credit" and t.amount >= LARGE_DEPOSIT
                and t.type not in ("card_payment",) and " card" not in (t.account_ref or "")]
    by_payer: Dict[str, List[Txn]] = defaultdict(list)
    for t in deposits:
        by_payer[t.merchant].append(t)
    income_items = sorted(({"from": p, "total": round(sum(t.amount for t in ts), 2), "times": len(ts),
                            "per_month": round(sum(t.amount for t in ts) / months, 2),
                            "source_ids": [t.source_ids[0] for t in ts[-3:]]} for p, ts in by_payer.items()),
                          key=lambda r: -r["total"])
    # Regular = a payer who deposits ₹5k+ at least twice; a single big credit (FD maturity, a stock sale) is one-off.
    regular = [r for r in income_items if r["times"] >= 2]
    income = round(sum(r["total"] for r in regular) / months, 2)
    one_off = round(sum(r["total"] for r in income_items if r["times"] < 2), 2)

    fixed: Dict[str, Dict] = {}
    for t in txns:   # loans and insurance actually paid
        if t.direction == "debit" and t.category in ("Loans & EMI", "Insurance") and t.amount < 50000:
            key = t.merchant
            r = fixed.setdefault(key, {"what": key, "kind": "EMI" if t.category == "Loans & EMI" else "Premium",
                                       "total": 0.0, "times": 0, "source_ids": []})
            r["total"] += t.amount; r["times"] += 1; r["source_ids"] = (r["source_ids"] + t.source_ids[:1])[-3:]
    for r in fixed.values():
        r["per_month"] = round(r["total"] / months, 2)
    for r in recurring_charges(L):   # SIPs, subscriptions, autopays on a rhythm
        if r["merchant"] not in fixed:
            fixed[r["merchant"]] = {"what": r["merchant"], "kind": "SIP" if r["category"] == "Investments" else "Repeating",
                                    "per_month": r["per_month"], "times": r["times"], "source_ids": r["source_ids"]}
    items = sorted((r for r in fixed.values() if r["per_month"] >= 100), key=lambda r: -r["per_month"])
    fixed_total = round(sum(r["per_month"] for r in items), 2)
    return {"months": round(months, 1), "from": first.isoformat(), "to": end.isoformat(),
            "income": income, "income_items": regular[:5], "one_off_deposits": one_off,
            "one_off_items": [r for r in income_items if r["times"] < 2][:3],
            "fixed": fixed_total, "fixed_items": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items() if k != "total"} for r in items[:8]],
            "free": round(income - fixed_total, 2),
            "fixed_ratio_pct": round(fixed_total / income * 100) if income else None,
            "note": f"Income = repeat deposits of ₹{LARGE_DEPOSIT:,}+ (one-off big credits shown apart); fixed = EMIs, premiums, SIPs and repeating charges."}


def income_by_month(L: Ledger) -> List[Dict]:
    """Money received per calendar month, from the messages: everything credited to bank
    accounts (card-bill credits and refunds to cards excluded), the large deposits within it,
    and who paid most."""
    months: Dict[str, Dict] = {}
    for t in _bank_txns(L):
        if t.direction != "credit" or t.type == "card_payment" or " card" in (t.account_ref or ""):
            continue
        key = t.on.strftime("%Y-%m")
        m = months.setdefault(key, {"month": key, "label": t.on.strftime("%B %Y"), "received": 0.0, "large": 0.0,
                                     "count": 0, "payers": defaultdict(float), "source_ids": [], "first": t.on, "last": t.on})
        m["received"] += t.amount; m["count"] += 1
        m["first"], m["last"] = min(m["first"], t.on), max(m["last"], t.on)
        if t.amount >= LARGE_DEPOSIT:
            m["large"] += t.amount
            m["source_ids"].append(t.source_ids[0])
        m["payers"][t.merchant] += t.amount
    out = []
    for m in sorted(months.values(), key=lambda m: m["month"]):
        top = sorted(m["payers"].items(), key=lambda kv: -kv[1])[:3]
        days = (m["last"] - m["first"]).days + 1
        out.append({"month": m["month"], "label": m["label"], "received": round(m["received"], 2), "large": round(m["large"], 2),
                    "count": m["count"], "top_payers": [{"from": p, "amount": round(a, 2)} for p, a in top],
                    "partial": days < 25, "covered": f"{m['first']:%d %b}–{m['last']:%d %b}",
                    "source_ids": m["source_ids"][:8]})
    return out


def income_day(L: Ledger) -> int:
    """The day of the month regular income usually lands (median of repeat large deposits)."""
    c = cashflow(L)
    regular = {r["from"] for r in c.get("income_items", [])}
    days = [t.on.day for t in _bank_txns(L) if t.direction == "credit" and t.merchant in regular and t.amount >= LARGE_DEPOSIT]
    return int(statistics.median(days)) if days else 1
