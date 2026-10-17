"""Merge the same money event reported by several sources.

Rule (context.md): same amount, dates within ±1 day, fuzzy-matching
merchant. The merged record keeps every source id. Dues merge on the same
account (or title), amount and due date.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import List

from paisadost.models import Due, Txn

FUZZY = 0.8


def similar(a: str, b: str) -> float:
    a, b = a.lower().strip(), b.lower().strip()
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    ta, tb = set(a.split()), set(b.split())
    overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return max(SequenceMatcher(None, a, b).ratio(), overlap)


def _sender(t: Txn) -> str:
    return t.source_label.split(" SMS")[0].split(" email")[0]


def _kind(t: Txn) -> str:
    return t.source_ids[0].split(":")[0]


def _same_txn(x: Txn, y: Txn) -> bool:
    if x.direction != y.direction or abs(x.amount - y.amount) > 0.01:
        return False
    if abs((x.on - y.on).days) > 1:
        return False
    kx, ky = _kind(x), _kind(y)
    if kx == ky:
        if kx not in ("sms", "email"):
            return False      # two rows of one CSV are two events by definition
        same_sender = _sender(x) == _sender(y)
        if same_sender and (not (x.at and y.at) or abs((x.at - y.at).total_seconds()) > 600):
            return False      # one sender twice: only a resend minutes apart is the same event
        if not same_sender and x.on != y.on and x.account_ref == y.account_ref:
            return False
    if x.account_ref and y.account_ref and x.account_ref != y.account_ref \
            and not (x.account_ref.startswith(y.account_ref) or y.account_ref.startswith(x.account_ref)):
        return False
    return similar(x.merchant, y.merchant) >= FUZZY or (x.account_ref and x.account_ref == y.account_ref)


def merge_txns(txns: List[Txn]) -> List[Txn]:
    out: List[Txn] = []
    for t in sorted(txns, key=lambda t: (t.on, t.amount)):
        matches = [o for o in out[-80:] if (t.on - o.on).days <= 1 and _same_txn(o, t)]
        if not matches:
            out.append(t)
            continue
        # The closest in time wins when a daily debit has several look-alikes.
        o = min(matches, key=lambda o: abs((o.at - t.at).total_seconds()) if o.at and t.at else 0)
        o.source_ids += [s for s in t.source_ids if s not in o.source_ids]
        o.account_ref = o.account_ref or t.account_ref
        if o.balance_after is None:
            o.balance_after = t.balance_after
        if o.category == "Other":
            o.category = t.category
    return out


def merge_dues(dues: List[Due]) -> List[Due]:
    out: List[Due] = []
    for d in sorted(dues, key=lambda d: (d.due_date, d.amount)):
        for o in out:
            if o.due_date != d.due_date or abs(o.amount - d.amount) > 0.01:
                continue
            same_acct = o.account_ref and d.account_ref and o.account_ref == d.account_ref
            if same_acct or similar(o.title, d.title) >= FUZZY:
                o.source_ids += [s for s in d.source_ids if s not in o.source_ids]
                o.account_ref = o.account_ref or d.account_ref
                if o.min_amount is None:
                    o.min_amount = d.min_amount
                break
        else:
            out.append(d)
    return out
