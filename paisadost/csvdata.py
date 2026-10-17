"""The structured CSVs for one user: investments, insurance, loans.

Each CSV row becomes a Source too, so a fact built from it can be cited
("from your investment orders on 3 Sep") and highlighted like an SMS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List

from paisadost.models import Due, Source, Txn
from paisadost.sources import IST, read_rows, read_user_rows
from paisadost.textparse import money


@dataclass
class Holding:
    fund: str
    invested: float
    current: float
    source_ids: List[str] = field(default_factory=list)
    source_label: str = ""


@dataclass
class LoanTerm:
    lender: str
    amount: float
    apr: float
    status: str
    source_ids: List[str] = field(default_factory=list)
    source_label: str = ""


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=IST)


def _src(id_: str, at: datetime, sender: str, text: str) -> Source:
    return Source(id=id_, kind="csv", at=at, sender=sender, text=text)


def load(user_id: str, as_of: date):
    sources: Dict[str, Source] = {}
    txns: List[Txn] = []
    dues: List[Due] = []
    holdings: List[Holding] = []
    loans: List[LoanTerm] = []

    funds = {r["fund_id"]: r["fund_name"] for r in read_rows("investment/funds.csv")}
    baskets = {r["basket_id"]: r["basket_name"] for r in read_rows("investment/baskets.csv")}

    for r in read_user_rows("investment/orders.csv", user_id):
        if r["status"] != "SUCCESS" or not r["amount_inr"]:
            continue
        at = _dt(r["succeeded_at"] or r["created_at"])
        name = funds.get(r["fund_id"], r["fund_id"])
        sell = r["order_type"] != "BUY"
        src = _src(f"order:{r['order_id']}", at, "investment orders",
                   f"{r['order_type']} {name} ₹{r['amount_inr']} ({r['buy_mode'] or r['withdrawal_type']}) on {at:%d %b %Y}")
        sources[src.id] = src
        amount = money(r["amount_credited_inr"] or r["amount_inr"]) if sell else money(r["amount_inr"])
        txns.append(Txn(id="", amount=amount, direction="credit" if sell else "debit", on=at.date(), merchant=name,
                        type="sip" if r["buy_mode"] == "SIP" else "investment", category="Investments",
                        account_ref="", at=at, source_ids=[src.id], source_label=src.label))

    for r in read_user_rows("investment/holdings.csv", user_id):
        if not r["current_value_inr"] or money(r["current_value_inr"]) <= 0:
            continue
        name = funds.get(r["fund_id"], r["fund_id"])
        src = _src(f"holding:{user_id}:{r['fund_id']}", _dt(r["nav_date"] + " 00:00:00"), "investment holdings",
                   f"{name}: {r['units']} units, invested ₹{r['invested_amount_inr']}, worth ₹{r['current_value_inr']} on {r['nav_date']}")
        sources[src.id] = src
        holdings.append(Holding(name, money(r["invested_amount_inr"]), money(r["current_value_inr"]), [src.id], src.label))

    for r in read_user_rows("investment/sip_plans.csv", user_id):
        if r["status"] != "ACTIVE":
            continue
        name = baskets.get(r["basket_id"]) or funds.get(r["fund_id"], "SIP")
        nxt = _next_debit(r, as_of)
        if not nxt:
            continue
        src = _src(f"sip:{r['sip_plan_id']}", _dt(r["activated_at"] or r["created_at"]), "SIP plans",
                   f"{r['frequency']} SIP ₹{r['amount_inr']} into {name}, active since {r['activated_at'][:10]}")
        sources[src.id] = src
        dues.append(Due(id="", title=f"SIP: {name}", amount=money(r["amount_inr"]), due_date=nxt, kind="sip",
                        source_ids=[src.id], source_label=src.label))

    for r in read_user_rows("insurance/policies.csv", user_id):
        if r["status"] != "active" or not r["next_payment_at"]:
            continue
        src = _src(f"policy:{r['policy_id']}", _dt(r["created_at"]), "insurance policy",
                   f"Health policy {r['policy_id']}: premium ₹{r['cycle_premium']}, next payment {r['next_payment_at'][:10]}")
        sources[src.id] = src
        dues.append(Due(id="", title="Health insurance premium", amount=money(r["cycle_premium"]),
                        due_date=_dt(r["next_payment_at"]).date(), kind="premium",
                        source_ids=[src.id], source_label=src.label))

    for r in read_user_rows("loan/emis.csv", user_id):
        if r["emi_status"] in ("PAID", "CANCELLED") or not r["due_date"]:
            continue
        src = _src(f"emi:{r['loan_id']}#{r['emi_number']}", _dt(r["due_date"] + " 00:00:00"), f"{r['lender']} loan",
                   f"{r['lender']} EMI {r['emi_number']}: ₹{r['emi_amount']} due {r['due_date']} ({r['emi_status']})")
        sources[src.id] = src
        dues.append(Due(id="", title=f"{r['lender']} EMI", amount=money(r["amount_still_due"] or r["emi_amount"]),
                        due_date=date.fromisoformat(r["due_date"]), kind="emi",
                        status="overdue" if r["emi_status"] == "OVERDUE" else "upcoming",
                        source_ids=[src.id], source_label=src.label))

    for r in read_user_rows("loan/loan_applications.csv", user_id):
        if not r["interest_rate_yearly_pct"] or not (r["disbursed_amount"] or r["approved_amount"]):
            continue
        src = _src(f"loanapp:{r['application_id']}", _dt(r["applied_at"]), f"{r['lender']} loan",
                   f"{r['lender']}: ₹{r['disbursed_amount'] or r['approved_amount']} at {r['interest_rate_yearly_pct']}% a year, {r['loan_status']}")
        sources[src.id] = src
        loans.append(LoanTerm(r["lender"], money(r["disbursed_amount"] or r["approved_amount"]),
                              float(r["interest_rate_yearly_pct"]), r["loan_status"], [src.id], src.label))

    return sources, txns, dues, holdings, loans


def _next_debit(r: Dict[str, str], as_of: date):
    first = r["first_debit_date"]
    if not first:
        return None
    d = date.fromisoformat(first)
    if r["frequency"] == "DAILY":
        return max(d, as_of + timedelta(days=1))
    if r["frequency"] == "MONTHLY" and r["debit_day"]:
        day = int(r["debit_day"])
        y, m = as_of.year, as_of.month
        if as_of.day >= day:
            m += 1
            if m > 12:
                y, m = y + 1, 1
        return max(d, date(y, m, min(day, 28)))
    return d if d > as_of else None
