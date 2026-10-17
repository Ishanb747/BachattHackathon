"""The unified records (see SCHEMA.md). Every one carries its proof."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional


@dataclass
class Source:
    """One raw row we read: an SMS, an email, or a CSV row."""

    id: str                 # "sms:1478", "email:2026-10-06T10:06", "sip:8651…"
    kind: str               # sms | email | csv
    at: datetime            # IST
    sender: str             # "BOB", "YES BANK", "investment/orders.csv"
    text: str               # what the evidence panel shows

    @property
    def label(self) -> str:
        """How the agent cites it: "your Bank of Baroda SMS on 13 Sep"."""
        when = f"{self.at.day} {self.at:%b}"
        noun = {"sms": "SMS", "email": "email"}.get(self.kind, "records")
        return f"your {self.sender} {noun} on {when}"


@dataclass
class Txn:
    id: str
    amount: float
    direction: str          # debit | credit
    on: date
    merchant: str
    type: str               # upi | card | neft | autopay | emi | premium | sip | bill | transfer | other
    category: str
    account_ref: str = ""   # "BOB XX1626", "IndusInd card XX3359"
    balance_after: Optional[float] = None
    at: Optional[datetime] = None
    source_ids: List[str] = field(default_factory=list)
    source_label: str = ""


@dataclass
class Due:
    id: str
    title: str
    amount: float
    due_date: date
    kind: str               # card | emi | premium | bill | sip | mandate
    account_ref: str = ""
    min_amount: Optional[float] = None
    status: str = "upcoming"   # upcoming | paid | overdue
    source_ids: List[str] = field(default_factory=list)
    source_label: str = ""


@dataclass
class Balance:
    id: str
    account_ref: str
    amount: float
    at: datetime
    source_ids: List[str] = field(default_factory=list)
    source_label: str = ""


@dataclass
class CardObs:
    """One observation of a credit card's state from one message."""

    id: str
    account_ref: str
    at: datetime
    available: Optional[float] = None
    outstanding: Optional[float] = None    # statement total due
    min_due: Optional[float] = None
    statement_date: Optional[date] = None
    source_ids: List[str] = field(default_factory=list)
    source_label: str = ""
