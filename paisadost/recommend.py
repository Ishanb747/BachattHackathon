"""P3: one line per pattern, ranked by rupee impact; health score /100;
the card paydown plan (also the engine behind "what if I prepay 20k").

Every number is computed here. Each insight carries the source ids of the
rows it stands on and a ready-made spoken citation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from paisadost import patterns
from paisadost.loader import Ledger

# Card finance charges are not in the data (they sit in password-protected
# statements). These are the issuers' published monthly rates; anything that
# uses them says so in its citation.
CARD_APR_PCT = {"YES": 47.88, "IndusInd": 46.0, "HDFC": 43.2, "Axis": 52.86, "IDFC": 46.2,
                "SBI": 42.0, "ICICI": 45.0, "Kotak": 44.4, "BOBCARD": 41.88}
APR_LABEL = "the card issuer's published finance charge"
TARGET_UTIL = 30.0


def _r(x: float) -> int:
    return int(round(x))


@dataclass
class Insight:
    id: str
    kind: str
    title: str          # short, for the UI card
    say: str            # one sentence the agent may speak (numbers already in)
    detail: str
    impact_inr: float
    source_ids: List[str] = field(default_factory=list)
    source_label: str = ""
    headline: str = ""        # the one figure the UI shows big (always a real number from the data)
    headline_note: str = ""   # what that figure is


def card_apr(card_ref: str) -> Optional[float]:
    return CARD_APR_PCT.get(card_ref.split(" card")[0])


def card_paydown_plan(cards: List[Dict], cash: float) -> Dict:
    """Avalanche: pay the highest-APR balance first; first get every card under 30% use,
    then clear balances in APR order. Returns pay per card and interest saved per month.

    ``cards``: [{card, outstanding, limit?, apr_pct?, source_ids}].
    """
    left = round(cash, 2)
    rows = []
    owed = [dict(c) for c in cards if (c.get("outstanding") or 0) > 0]
    for c in owed:
        c["apr_pct"] = c.get("apr_pct") or card_apr(c["card"]) or 42.0
        c["pay"] = 0.0
    order = sorted(owed, key=lambda c: -c["apr_pct"])
    # Pass 1: bring each card under the utilisation target, highest APR first.
    for c in order:
        if c.get("limit"):
            over = c["outstanding"] - c["limit"] * TARGET_UTIL / 100
            if over > 0 and left > 0:
                p = min(over, left); c["pay"] += p; left -= p
    # Pass 2: clear what is left, highest APR first.
    for c in order:
        rest = c["outstanding"] - c["pay"]
        if rest > 0 and left > 0:
            p = min(rest, left); c["pay"] += p; left -= p
    total_saved = 0.0
    for c in order:
        saved = c["pay"] * c["apr_pct"] / 100 / 12
        total_saved += saved
        new_out = c["outstanding"] - c["pay"]
        rows.append({"card": c["card"], "outstanding": round(c["outstanding"], 2), "pay": round(c["pay"], 2),
                     "new_outstanding": round(new_out, 2), "apr_pct": c["apr_pct"],
                     "interest_saved_per_month": round(saved, 2),
                     "utilisation_before_pct": round(c["outstanding"] / c["limit"] * 100, 1) if c.get("limit") else None,
                     "utilisation_after_pct": round(new_out / c["limit"] * 100, 1) if c.get("limit") else None,
                     "source_ids": c.get("source_ids", [])})
    lim = sum(c["limit"] for c in owed if c.get("limit"))
    before = sum(c["outstanding"] for c in owed if c.get("limit"))
    after = sum(r["new_outstanding"] for r, c in zip(rows, order) if c.get("limit"))
    return {"cash": round(cash, 2), "used": round(cash - left, 2), "left_over": round(left, 2), "plan": rows,
            "interest_saved_per_month": round(total_saved, 2),
            "utilisation_before_pct": round(before / lim * 100, 1) if lim else None,
            "utilisation_after_pct": round(after / lim * 100, 1) if lim else None,
            "apr_label": APR_LABEL}


def card_rows(L: Ledger) -> List[Dict]:
    """Cards with a known bill, as card_paydown_plan input. Paid bills count as nothing owed."""
    paid = {d.account_ref for d in L.dues if d.kind == "card" and d.status == "paid" and d.due_date >= L.as_of.replace(day=1)}
    out = []
    for c in L.cards.values():
        if c.outstanding and c.outstanding > 0 and c.account_ref not in paid:
            out.append({"card": c.account_ref, "outstanding": c.outstanding, "limit": c.limit,
                        "apr_pct": card_apr(c.account_ref), "source_ids": c.source_ids})
    return out


def what_if_prepay(L: Ledger, amount: float) -> Dict:
    plan = card_paydown_plan(card_rows(L), amount)
    # Utilisation across every card whose limit we know (paid-off ones count as ₹0 used).
    known = [c for c in L.cards.values() if c.limit]
    if known:
        paid_now = {r["card"]: r["pay"] for r in plan["plan"]}
        owed = {c.account_ref: max(0.0, c.outstanding or 0) for c in known}
        for d in L.dues:
            if d.kind == "card" and d.status == "paid" and d.account_ref in owed:
                owed[d.account_ref] = 0.0
        lim = sum(c.limit for c in known)
        before = sum(owed.values())
        after = sum(max(0.0, v - paid_now.get(k, 0)) for k, v in owed.items())
        plan["utilisation_before_pct"] = round(before / lim * 100, 1)
        plan["utilisation_after_pct"] = round(after / lim * 100, 1)
        plan["utilisation_cards"] = [c.account_ref for c in known]
    bank = sum(b.amount for b in L.balances.values())
    plan["bank_balance_before"] = round(bank, 2)
    plan["bank_balance_after"] = round(bank - plan["used"], 2)
    plan["source_ids"] = [s for r in plan["plan"] for s in r["source_ids"]] + \
                         [s for b in L.balances.values() for s in b.source_ids]
    return plan


def insights(L: Ledger, P: Optional[Dict] = None) -> List[Insight]:
    P = P or patterns.analyze(L)
    out: List[Insight] = []

    # Dues that are late or about to be, with the money that should cover them.
    for d in P["dues_vs_balance"]:
        late = d["days_left"] < 0
        n = abs(d["days_left"])
        days = f"{n} day{'s' if n != 1 else ''}"
        when = f"{days} past due" if late else ("due today" if n == 0 else f"due in {days}")
        say = (f"Your {d['title']} of ₹{d['amount']:,.0f} is {when} and I see no payment yet; pay it today to avoid a late fee."
               if late else f"Your {d['title']} of ₹{d['amount']:,.0f} is {when}.")
        if d["short_by"] > 0:
            say += f" Your {d['balance_account']} balance is ₹{d['balance']:,.0f}, short by ₹{d['short_by']:,.0f}."
        out.append(Insight(f"ins:due:{d['due_id']}", "due", d["title"].split(" (")[0], say,
                           f"₹{d['amount']:,.0f} · {when}", d["amount"] + (d["short_by"] or 0),
                           d["source_ids"], d["source_label"], f"₹{d['amount']:,.0f}", "past due" if late else "due soon"))
        if not late:
            out[-1].kind = "upcoming"

    # Credit: which card to pay first, and what it saves.
    rows = card_rows(L)
    if rows:
        plan = card_paydown_plan(rows, sum(r["outstanding"] for r in rows))
        first = plan["plan"][0]
        util = P["card_utilisation"][-1] if P["card_utilisation"] and P["card_utilisation"][-1]["card"].startswith("ALL") else None
        say = (f"Pay your {first['card']} first: ₹{first['outstanding']:,.0f} at about {first['apr_pct']:.0f}% a year "
               f"costs ₹{first['interest_saved_per_month']:,.0f} a month in interest if carried.")
        if util:
            say += f" Your card use is {util['utilisation_pct']}% of known limits, under the 30% mark."
        out.append(Insight("ins:card:first", "credit", f"Pay {first['card'].split(' card')[0]} card first", say,
                           f"₹{first['outstanding']:,.0f} owed · ~{first['apr_pct']:.0f}% APR", first["outstanding"] + first["interest_saved_per_month"] * 12,
                           first["source_ids"], L.label(first["source_ids"]), f"₹{first['outstanding']:,.0f}", "on this card"))

    # Credit report checks: many lenders in a short span pull the score down.
    enq = P.get("enquiries") or {}
    if enq.get("count", 0) >= 3:
        names = ", ".join(enq["lenders"][:3])
        say = (f"Your credit report was checked {enq['count']} times by {len(enq['lenders'])} lenders in the last {enq['days']} days, including {names}; "
               f"each check can lower your CIBIL score, so pause new loan or card applications for a few months.")
        out.append(Insight("ins:credit:enquiries", "credit", "Too many credit checks", say,
                           f"{enq['count']} checks by {len(enq['lenders'])} lenders in {enq['days']} days", 5000 + 500 * enq["count"],
                           enq["source_ids"], L.label(enq["source_ids"]), str(enq["count"]), f"checks in {enq['days']} days"))

    # Recurring money going out.
    for r in P["recurring"][:3]:
        if r["per_month"] < 500:
            continue
        twice = " twice a day" if r["per_day"] >= 1.5 else ""
        say = (f"{r['merchant']} takes ₹{r['amount']:,.0f} {r['cadence']}{twice}, about ₹{r['per_month']:,.0f} a month. "
               f"Check that every plan is one you still want.")
        out.append(Insight(f"ins:recurring:{r['merchant']}", "recurring",
                           f"{r['merchant']} subscription", say,
                           f"≈ ₹{r['per_month']:,.0f}/month · {r['times']} charges", r["per_month"], r["source_ids"], L.label(r["source_ids"]),
                           f"₹{r['per_month']:,.0f}", "per month"))

    # Possible double charges.
    for d in P["duplicates"]:
        say = f"You were charged ₹{d['amount']:,.0f} twice by {d['merchant']} on {d['on']}; ask for a refund if one was a mistake."
        out.append(Insight(f"ins:dup:{d['merchant']}:{d['on']}", "duplicate", "Possible double charge",
                           say, f"{d['merchant']} · ₹{d['amount']:,.0f} × 2 on {d['on']}", d["amount"], d["source_ids"], d["source_label"],
                           f"₹{d['amount']:,.0f}", "charged twice"))

    # Spending well above usual.
    for s in P["spend_vs_usual"]:
        if s["excess"] > 1000 and s["usual_30d"] > 0:
            say = (f"{s['category']} spending was ₹{s['last_30d']:,.0f} in the last 30 days, "
                   f"₹{s['excess']:,.0f} more than your usual ₹{s['usual_30d']:,.0f}.")
            out.append(Insight(f"ins:spend:{s['category']}", "spend", f"{s['category']} spending up", say,
                               f"₹{s['excess']:,.0f} above usual ({s['change_pct']:+d}%)", s["excess"], s["source_ids"], L.label(s["source_ids"]),
                               f"₹{s['excess']:,.0f}", "above usual"))

    out.sort(key=lambda i: -i.impact_inr)
    # Late dues always lead, whatever their size: they are the time-critical ones.
    out.sort(key=lambda i: 0 if i.kind == "due" and "past due" in i.detail else 1)
    return out


def health_score(L: Ledger, P: Optional[Dict] = None) -> Dict:
    """Five parts, each from data the user can check. Missing data scores the midpoint, never full marks."""
    P = P or patterns.analyze(L)
    parts = []

    late = [d for d in L.dues if d.status == "overdue" and (L.as_of - d.due_date).days <= 60 and d.amount > 0]
    on_time = max(0, 25 - 8 * len(late))
    parts.append({"name": "Bills on time", "score": on_time, "max": 25,
                  "note": f"{len(late)} overdue in the last 60 days",
                  "source_ids": [s for d in late for s in d.source_ids[:1]]})

    bank = sum(b.amount for b in L.balances.values())
    monthly = P["monthly_outflow"] or 1
    months = bank / monthly
    parts.append({"name": "Cash buffer", "score": _r(min(25, months / 3 * 25)), "max": 25,
                  "note": f"₹{bank:,.0f} in bank ≈ {months:.1f} months of spending",
                  "source_ids": [s for b in L.balances.values() for s in b.source_ids]})

    util = P["card_utilisation"][-1] if P["card_utilisation"] and P["card_utilisation"][-1]["card"].startswith("ALL") else None
    if util:
        u = util["utilisation_pct"]
        cscore = 20 if u <= 10 else 16 if u <= 30 else 8 if u <= 50 else 2
        parts.append({"name": "Credit use", "score": cscore, "max": 20, "note": f"{u}% of known card limits",
                      "source_ids": util["source_ids"]})
    else:
        parts.append({"name": "Credit use", "score": 10, "max": 20, "note": "no card limit in your messages",
                      "source_ids": []})

    inv = sum(r["per_month"] for r in P["recurring"] if r["category"] == "Investments")
    rate = inv / (monthly + inv) * 100 if monthly + inv else 0
    parts.append({"name": "Investing habit", "score": _r(min(15, rate / 20 * 15)), "max": 15,
                  "note": f"₹{inv:,.0f}/month in SIPs ≈ {rate:.0f}% of outflow",
                  "source_ids": [s for r in P["recurring"] if r["category"] == "Investments" for s in r["source_ids"][:1]]})

    spikes = [s for s in P["spend_vs_usual"] if s["excess"] > 1000 and s["usual_30d"] > 0]
    parts.append({"name": "Steady spending", "score": max(0, 15 - 5 * len(spikes)), "max": 15,
                  "note": f"{len(spikes)} categories well above usual",
                  "source_ids": [s for x in spikes for s in x["source_ids"][:1]]})

    score = sum(p["score"] for p in parts)
    grade = "Strong" if score >= 75 else "Fair" if score >= 55 else "Needs attention"
    return {"score": score, "grade": grade, "parts": parts}


def as_dicts(items: List[Insight]) -> List[Dict]:
    return [asdict(i) for i in items]
