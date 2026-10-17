"""P1: everything one user has, parsed and deduped into one Ledger.

    ledger = load("1749913629362473")
    ledger.txns, ledger.dues, ledger.balances, ledger.cards, ledger.sources

Regex does the parsing; SMS that read like money but match no rule are
kept in ``ledger.leftovers`` (``paisadost.llm_fallback`` can label them).
The result is cached per user under ``data/``.
"""

from __future__ import annotations

import hashlib
import pickle
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from paisadost import csvdata, dedupe, parse_email, parse_sms
from paisadost.config import AS_OF, STORE_DIR, _get

LLM_FALLBACK = _get("PAISA_LLM_FALLBACK", "1") == "1"
from paisadost.models import Balance, CardObs, Due, Source, Txn
from paisadost.sources import iter_emails, iter_sms, user_profile

CACHE_VERSION = 7


@dataclass
class Card:
    account_ref: str
    available: Optional[float] = None
    available_at: Optional[str] = None
    outstanding: Optional[float] = None
    min_due: Optional[float] = None
    limit: Optional[float] = None
    source_ids: List[str] = field(default_factory=list)
    source_label: str = ""


@dataclass
class Ledger:
    user_id: str
    name: str
    as_of: date
    sources: Dict[str, Source]
    txns: List[Txn]
    dues: List[Due]
    balances: Dict[str, Balance]          # latest per account
    balance_history: List[Balance]
    cards: Dict[str, Card]
    holdings: list
    loans: list
    leftovers: List[str]                  # source ids
    raw_counts: Dict[str, int] = field(default_factory=dict)
    enquiries: List[Dict] = field(default_factory=list)   # credit-report checks by lenders

    def label(self, source_ids: List[str]) -> str:
        """The citation for a fact: the most recent source, spoken."""
        srcs = [self.sources[s] for s in source_ids if s in self.sources]
        if not srcs:
            return ""
        return "from " + max(srcs, key=lambda s: s.at).label


def _stable_id(prefix: str, *parts) -> str:
    return prefix + ":" + hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:10]


def build(user_id: str, as_of: date = AS_OF) -> Ledger:
    sources: Dict[str, Source] = {}
    txns: List[Txn] = []; dues: List[Due] = []; bals: List[Balance] = []; obs: List[CardObs] = []
    leftovers: List[str] = []
    counts = {"sms": 0, "email": 0}

    enquiries: List[Dict] = []
    for src in iter_sms(user_id):
        counts["sms"] += 1
        enq = parse_sms.enquiry(src)
        if enq:
            sources[src.id] = src
            enquiries.append(enq)
        (t, b, c, d), ok = parse_sms.parse(src)
        if t or b or c or d or not ok:
            sources[src.id] = src
        if not ok:
            leftovers.append(src.id)
        txns += t; bals += b; obs += c; dues += d

    for src in iter_emails(user_id):
        counts["email"] += 1
        d, c = parse_email.parse(src)
        t = parse_email.parse_txn(src)
        txns += t
        if d or c or t:
            src.text = f"{src.subject} — {src.body[:600]}"
            sources[src.id] = src
        dues += d; obs += c

    # Regex first; the LLM only labels what no rule understood (amounts verified against the text).
    if leftovers and LLM_FALLBACK:
        from paisadost import llm_fallback
        lt, ld = llm_fallback.records(user_id, [sources[i] for i in leftovers])
        txns += lt; dues += ld
        counts["llm_txns"], counts["llm_dues"] = len(lt), len(ld)

    csv_sources, csv_txns, csv_dues, holdings, loans = csvdata.load(user_id, as_of)
    sources.update(csv_sources)
    txns += csv_txns; dues += csv_dues

    _resolve_accounts(txns, bals, dues)
    raw = {"txns": len(txns), "dues": len(dues)}
    txns = dedupe.merge_txns(txns)
    dues = dedupe.merge_dues(dues)

    for t in txns:
        t.id = _stable_id("txn", t.on, t.amount, t.direction, t.source_ids[0])
        t.source_label = _label(sources, t.source_ids)
    for d in dues:
        d.id = _stable_id("due", d.due_date, d.amount, d.title)
        d.source_label = _label(sources, d.source_ids)
    _due_status(dues, txns, as_of)

    latest: Dict[str, Balance] = {}
    for b in sorted(bals, key=lambda b: b.at):
        b.id = _stable_id("bal", b.account_ref, b.at)
        if b.at.date() <= as_of:
            latest[b.account_ref] = b

    cards = _cards(obs, dues, sources)
    prof = user_profile(user_id)
    name = f"{prof.get('first_name', '').title()} {prof.get('last_name', '').title()}".strip()
    counts.update(raw)
    return Ledger(user_id, name, as_of, sources, txns, dues, latest, bals, cards, holdings, loans, leftovers, counts,
                  sorted(enquiries, key=lambda e: e["on"]))


def _label(sources, ids) -> str:
    srcs = [sources[s] for s in ids if s in sources]
    return "from " + max(srcs, key=lambda s: s.at).label if srcs else ""


def _resolve_accounts(txns, bals, dues) -> None:
    """A message that names only the bank ("BOB") belongs to that bank's one numbered account."""
    numbered: Dict[str, set] = {}
    for r in list(txns) + list(bals) + list(dues):
        ref = r.account_ref
        if " XX" in ref and " card " not in ref:
            numbered.setdefault(ref.split(" XX")[0], set()).add(ref)
    for r in list(txns) + list(bals) + list(dues):
        accts = numbered.get(r.account_ref)
        if accts and len(accts) == 1:
            r.account_ref = next(iter(accts))


def _due_status(dues: List[Due], txns: List[Txn], as_of: date) -> None:
    pays = [t for t in txns if t.direction == "debit" or t.type == "card_payment"]
    used: set = set()                     # one payment settles one due
    for d in sorted(dues, key=lambda d: d.due_date):
        if d.amount <= 0:
            d.status = "paid"
            continue
        lo, hi = d.due_date - timedelta(days=20), d.due_date + timedelta(days=5)
        for t in sorted(pays, key=lambda t: abs((t.on - d.due_date).days)):
            if id(t) in used or not (lo <= t.on <= hi) or abs(t.amount - d.amount) > max(1.0, d.amount * 0.01):
                continue
            card_match = d.kind == "card" and t.type == "card_payment" and t.account_ref == d.account_ref
            name_match = dedupe.similar(t.merchant, d.title.split(":")[-1]) >= 0.6
            acct_match = d.kind in ("mandate", "sip") and t.account_ref and t.account_ref == d.account_ref
            if card_match or name_match or acct_match:
                d.status = "paid"
                used.add(id(t))
                d.source_ids += [s for s in t.source_ids if s not in d.source_ids]
                break
        else:
            if d.due_date < as_of:
                # Only recent dues can honestly be called overdue: for older ones the
                # payment may simply be in a channel we cannot see.
                recent = (as_of - d.due_date).days <= 30
                d.status = "past" if d.kind in ("mandate", "sip") else "overdue" if recent else "unconfirmed"


def _cards(obs: List[CardObs], dues: List[Due], sources) -> Dict[str, Card]:
    cards: Dict[str, Card] = {}
    for o in sorted(obs, key=lambda o: o.at):
        c = cards.setdefault(o.account_ref, Card(o.account_ref))
        if o.available is not None:
            c.available, c.available_at = o.available, o.at.date().isoformat()
        if o.outstanding is not None:
            c.outstanding, c.min_due = o.outstanding, o.min_due
        c.source_ids += [s for s in o.source_ids if s not in c.source_ids]
    for d in sorted((d for d in dues if d.kind == "card" and " XX" in d.account_ref), key=lambda d: d.due_date):
        c = cards.setdefault(d.account_ref, Card(d.account_ref))
        c.outstanding, c.min_due = d.amount, d.min_amount
        c.source_ids += [s for s in d.source_ids if s not in c.source_ids]
    for c in cards.values():
        # Limit = what is free + what is owed, when both are known from the same period.
        if c.available is not None and c.outstanding is not None and c.outstanding >= 0:
            c.limit = round(c.available + c.outstanding, 2)
        c.source_label = _label(sources, c.source_ids)
    return cards


def load(user_id: str, as_of: date = AS_OF, refresh: bool = False) -> Ledger:
    path = STORE_DIR / user_id / f"ledger-v{CACHE_VERSION}-{as_of.isoformat()}.pkl"
    if path.exists() and not refresh:
        with open(path, "rb") as fh:
            return pickle.load(fh)
    ledger = build(user_id, as_of)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        pickle.dump(ledger, fh)
    return ledger
