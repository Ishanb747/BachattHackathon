"""Email → Due / CardObs. Statement summaries and bill notices, regex only.

Emails are mostly marketing; only messages whose subject says bill,
statement, due or premium are looked at, and promotional ones are dropped.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from paisadost.models import CardObs, Due, Source, Txn
from paisadost.textparse import AMOUNT, DATE, categorize, money, normalize_merchant, parse_date

I = re.I
_SUBJECT = re.compile(r"bill|statement|due|premium|payment reminder|renew", I)
_PROMO = re.compile(r"offer|cashback|sale|deal|%\s*off|upgrade|pre-?approved|loan on card|eligib", I)
_BANK = [("yes bank", "YES"), ("indusind", "IndusInd"), ("first select", "IDFC"), ("idfc", "IDFC"), ("hdfc", "HDFC"),
         ("axis", "Axis"), ("sbi", "SBI"), ("icici", "ICICI"), ("kotak", "Kotak"), ("au bank", "AU"), ("onecard", "BOBCARD")]


def _bank(text: str) -> str:
    low = text.lower()
    for key, name in _BANK:
        if key in low:
            return name
    return "Card"


_RECEIPT = re.compile(r"^payment successful for|sip instalment|transaction receipt alert: purchase|payment receipt|"
                      r"payment received for|premium receipt", I)


def parse_txn(src: Source) -> List[Txn]:
    """Payment receipts: the email side of a charge an SMS may also report."""
    subject = getattr(src, "subject", "")
    body = getattr(src, "body", src.text)
    if not _RECEIPT.search(subject) or _PROMO.search(subject):
        return []
    ref = src.at.date()
    m = re.search(r"^payment successful for (.+)$", subject, I)
    if m:                                              # Razorpay: "bachatt ₹ 101 .00 Paid Successfully … Paid On 16 Oct, 2026"
        a = re.search(r"₹\s*([\d,]+)\s*\.(\d\d)", body)
        d = re.search(r"paid on " + DATE, body, I)
        if not a:
            return []
        amount = money(a.group(1)) + int(a.group(2)) / 100
        on = parse_date(d.group(1), ref) if d else ref
        merchant = m.group(1)
    else:
        a = re.search(AMOUNT, f"{subject} {body}", I)
        if not a:
            return []
        amount = money(a.group(1))
        d = re.search(r"debited on " + DATE, subject, I)
        on = parse_date(d.group(1), ref) if d else ref
        merchant = f"{subject} {body[:300]}"
    merch = normalize_merchant(merchant)
    return [Txn(id="", amount=amount, direction="debit", on=on or ref, merchant=merch, type="receipt",
                category=categorize(merch, merchant), at=src.at, source_ids=[src.id], source_label=src.label)]


def parse(src: Source) -> Tuple[List[Due], List[CardObs]]:
    dues: List[Due] = []
    cards: List[CardObs] = []
    subject = getattr(src, "subject", "")
    body = getattr(src, "body", src.text)
    if not _SUBJECT.search(subject) or _PROMO.search(subject):
        return dues, cards
    ref = src.at.date()

    def due(title, amount, d, kind, account="", min_amount=None):
        dues.append(Due(id="", title=title, amount=amount, due_date=d, kind=kind, account_ref=account,
                        min_amount=min_amount, source_ids=[src.id], source_label=src.label))

    # CRED-style reminder: "YES Bank •••• 9269 Due amount Due date ₹399.97 Oct 10, 2026"
    m = re.search(r"([A-Za-z ]{2,20}?) [•*x]{2,} ?(\d{4}) due amount due date " + AMOUNT + r" " + DATE, body, I)
    if m:
        bank = _bank(m.group(1))
        card = f"{bank} card XX{m.group(2)}"
        due(f"{bank} credit card bill", money(m.group(3)), parse_date(m.group(4), ref), "card", card)
        return dues, cards

    # Issuer statement summary: "card ending with XXXX1641: Statement Date 24/Sep/2026 Total Amount Due ₹0.00 … Payment Due Date 09/Oct/2026"
    m = re.search(r"card (?:ending (?:with )?|no\.? )?[x*]*(\d{4}).{0,80}?statement date:? " + DATE +
                  r".{0,40}?total amount due:? " + AMOUNT + r".{0,120}?(?:payment )?due date:? " + DATE, body, I)
    if m:
        bank = _bank(f"{subject} {body[:300]}")
        card = f"{bank} card XX{m.group(1)}"
        total = money(m.group(3))
        mn = re.search(r"minimum amount due:? " + AMOUNT, body, I)
        due(f"{bank} credit card bill", total, parse_date(m.group(4), ref), "card", card, money(mn.group(1)) if mn else None)
        cards.append(CardObs(id="", account_ref=card, at=src.at, outstanding=total,
                             min_due=money(mn.group(1)) if mn else None,
                             statement_date=parse_date(m.group(2), ref), source_ids=[src.id], source_label=src.label))
        return dues, cards

    # Generic card statement: total amount due + due date anywhere in the body
    m = re.search(r"total (?:amount )?due:? " + AMOUNT, body, I)
    d = re.search(r"(?:payment )?due (?:date|by|on):? " + DATE, body, I)
    c = re.search(r"card (?:ending (?:with )?|no\.? )?[x*•]*\s?(\d{4})\b", body, I)
    if m and d and c and "card" in f"{subject} {body[:500]}".lower():
        bank = _bank(f"{subject} {body[:300]}")
        due(f"{bank} credit card bill", money(m.group(1)), parse_date(d.group(1), ref), "card", f"{bank} card XX{c.group(1)}")
        return dues, cards

    # Postpaid / utility bill: "₹195.88 Due on 15 Oct 2026"
    m = re.search(AMOUNT + r" due on " + DATE, body, I)
    if m and re.search(r"bill", subject, I):
        name = "Airtel postpaid bill" if "airtel" in subject.lower() else subject[:40]
        due(name, money(m.group(1)), parse_date(m.group(2), ref), "bill")
        return dues, cards

    # Insurance premium reminder without a date: "Policy no. 42733153 Premium ₹1401"
    m = re.search(r"policy no\.? (\d+) premium " + AMOUNT, body, I)
    if m:
        insurer = "LIC" if re.search(r"\blic\b", body, I) else "Insurance"
        d = re.search(r"due (?:on|by|date):? " + DATE, body, I)
        # No date in the mail: the premium is "due for renewal" now, i.e. as of the email.
        due(f"{insurer} premium (policy {m.group(1)})", money(m.group(2)),
            parse_date(d.group(1), ref) if d else ref, "premium")
        return dues, cards
    return dues, cards
