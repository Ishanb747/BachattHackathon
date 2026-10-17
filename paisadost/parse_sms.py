"""SMS → Txn / Balance / CardObs / Due. Regex rules, most specific first.

Each rule was written against real messages in sms.csv; the generic rules
at the end catch the same shapes from banks we have not seen. A message no
rule understands is returned as a leftover (for the optional LLM pass).
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from paisadost.models import Balance, CardObs, Due, Source, Txn
from paisadost.textparse import AMOUNT, DATE, categorize, money, normalize_merchant, parse_date

I = re.I
_LAST4 = re.compile(r"(?:a/c|acct|account|a/c no\.?)\s*(?:no\.?\s*)?[x*.\s]*?(\d{3,6})\b", I)
_BAL = re.compile(r"(?:avl\.?\s*bal|avlbal|available balance|avail(?:able)?\.? bal|new bal|total bal|clr bal|bal)\s*:?\s*(?:is\s*)?(?:rs\.?|inr)?\s*:?\s*([\d,]+(?:\.\d+)?)", I)
_CARD = re.compile(r"card\s*(?:no\.?|ending(?: with)?|xx+|x+|\*+)?\s*[x*-]*\s*(\d{4})\b", I)
_LIMIT = re.compile(r"(?:avl\.?\s*lmt|avl limit|available limit(?: is)?|avl\.? limit)\s*:?\s*(?:rs\.?|inr)?\s*:?\s*([\d,]+(?:\.\d+)?)", I)
_BANKS = [("bank of baroda", "BOB"), ("bob", "BOB"), ("idfc", "IDFC"), ("yes bank", "YES"), ("indusind", "IndusInd"),
          ("axis", "Axis"), ("hdfc", "HDFC"), ("sbi", "SBI"), ("kotak", "Kotak"), ("icici", "ICICI"), ("pnb", "PNB"),
          ("canara", "Canara"), ("central bank", "CBoI"), ("cboi", "CBoI"), ("airtel payments", "Airtel PB"),
          ("federal", "Federal"), ("au small", "AU"), ("union bank", "Union"), ("bobcard", "BOBCARD")]

Parsed = Tuple[List[Txn], List[Balance], List[CardObs], List[Due]]


def _bank(src: Source, text: str) -> str:
    blob = f"{src.sender} {text}".lower()
    for key, name in _BANKS:
        if key in blob:
            return name
    return src.sender


def _date_in(text: str, src: Source, pattern: str = DATE):
    m = re.search(pattern, text, I)
    return (parse_date(m.group(1), src.at.date()) if m else None) or src.at.date()


def _txn(src, amount, direction, merchant, typ, account, balance=None, on=None) -> Txn:
    merch = normalize_merchant(merchant)
    return Txn(id="", amount=amount, direction=direction, on=on or src.at.date(), merchant=merch, type=typ,
               category=categorize(merch, merchant, src.text) if direction == "debit" else "Income & refunds",
               account_ref=account, balance_after=balance, at=src.at,
               source_ids=[src.id], source_label=src.label)


def _bal(src, account, amount) -> Balance:
    return Balance(id="", account_ref=account, amount=amount, at=src.at, source_ids=[src.id], source_label=src.label)


def _due(src, title, amount, due_date, kind, account="", min_amount=None) -> Due:
    return Due(id="", title=title, amount=amount, due_date=due_date, kind=kind, account_ref=account,
               min_amount=min_amount, source_ids=[src.id], source_label=src.label)


def _card_ref(bank: str, last4: str) -> str:
    return f"{bank} card XX{last4}"


def _acct_ref(bank: str, last4: Optional[str]) -> str:
    return f"{bank} XX{last4[-4:]}" if last4 else bank


PROMO = re.compile(r"(offer|cashback|apply now|pre-?approved|eligible for|get up to|win |loan of rs|loan available|"
                   r"click to|limited period|voucher|convert (it|your).{0,40}emi|can now be converted|"
                   r"require consent|reward)", I)


def parse(src: Source) -> Tuple[Parsed, bool]:
    """Returns (records, understood)."""
    txns: List[Txn] = []; bals: List[Balance] = []; cards: List[CardObs] = []; dues: List[Due] = []
    t = src.text
    dlt = getattr(src, "dlt", "")
    if dlt.endswith("-P") or re.search(r"\botp\b|one time password|verification code", t, I):
        return (txns, bals, cards, dues), True
    if not re.search(AMOUNT, t, I) and "debited with" not in t:
        return (txns, bals, cards, dues), True

    bank = _bank(src, t)

    if re.search(r"unsuccessful|failed|declined|reported your fund bal|will be refunded", t, I):
        return (txns, bals, cards, dues), True
    m = re.search(r"payment of " + AMOUNT + r" settled and released on [\d:]+ [ap]m, " + DATE, t, I)
    if m:                                                                     # merchant payout (MobiKwik)
        txns.append(_txn(src, money(m.group(1)), "credit", f"{src.sender} settlement", "settlement", src.sender,
                         on=parse_date(m.group(2), src.at.date())))
        return (txns, bals, cards, dues), True
    m = re.search(AMOUNT + r" emi for your (.+?) a/c x*(\d+) is due on " + DATE + r".*?debited from a/c x*(\d+)", t, I)
    if m:                                                                     # IDFC loan EMI alert
        dues.append(_due(src, f"{bank} {m.group(2).lower()} EMI", money(m.group(1)),
                         parse_date(m.group(4), src.at.date()), "emi", _acct_ref(bank, m.group(5))))
        return (txns, bals, cards, dues), True
    m = re.search(r"received emi " + AMOUNT + r" towards (.+?) (?:loan )?account no x*(\d+)", t, I)
    if m:
        txns.append(_txn(src, money(m.group(1)), "debit", f"{bank} {m.group(2)} EMI", "emi", ""))
        txns[-1].category = "Loans & EMI"
        return (txns, bals, cards, dues), True
    m = re.search(r"credit balance of " + AMOUNT + r" on your .*?credit card (?:no\. )?[x*]*(\d{4})", t, I)
    if m:
        cards.append(CardObs(id="", account_ref=_card_ref(bank, m.group(2)), at=src.at,
                             outstanding=-money(m.group(1)), source_ids=[src.id], source_label=src.label))
        return (txns, bals, cards, dues), True

    # ── Card statement / bill (dues) ──────────────────────────────────────────
    m = re.search(r"card\s*(?:xx|x|ending)?\s*[x*-]*(\d{4}).{0,40}?statement:?\s*total due\s*" + AMOUNT +
                  r"\s*min due\s*" + AMOUNT + r"\s*due by\s*" + DATE, t, I)          # YES
    if not m:
        m2 = re.search(r"total amount due on your .*?card\s*[x*]*(\d{4}) is " + AMOUNT +
                       r"(?: cr)? and minimum amount due is " + AMOUNT + r",? payable by " + DATE, t, I)   # IndusInd
        m = m2
    if m:
        card = _card_ref(bank, m.group(1))
        d = parse_date(m.group(4), src.at.date())
        total, mn = money(m.group(2)), money(m.group(3))
        dues.append(_due(src, f"{bank} credit card bill", total, d, "card", card, mn))
        cards.append(CardObs(id="", account_ref=card, at=src.at, outstanding=total, min_due=mn,
                             source_ids=[src.id], source_label=src.label))
        return (txns, bals, cards, dues), True

    m = re.search(r"credit card bill of " + AMOUNT + r" is ready\. pay by " + DATE, t, I)   # BOBCARD One
    if m:
        dues.append(_due(src, f"{bank} credit card bill", money(m.group(1)),
                         parse_date(m.group(2), src.at.date()), "card", f"{bank} card"))
        return (txns, bals, cards, dues), True

    if PROMO.search(t):
        return (txns, bals, cards, dues), True

    # ── Card spends ───────────────────────────────────────────────────────────
    m = re.search(AMOUNT + r" spent on (\w+) (?:bank )?card xx(\d{4}) on " + DATE + r".*? at (.+?)\. avl lmt", t, I)
    if m:
        card = _card_ref(bank, m.group(3))
        lim = _LIMIT.search(t)
        txns.append(_txn(src, money(m.group(1)), "debit", m.group(5), "card", card,
                         on=parse_date(m.group(4), src.at.date())))
        if lim:
            cards.append(CardObs(id="", account_ref=card, at=src.at, available=money(lim.group(1)),
                                 source_ids=[src.id], source_label=src.label))
        return (txns, bals, cards, dues), True
    m = re.search(AMOUNT + r" spent on your .*?card ending xx(\d{4}) at (.+?) on " + DATE + r".*?avbl limit:? " + AMOUNT, t, I)
    if m:                                                                     # IDFC FIRST card
        card = _card_ref(bank, m.group(2))
        txns.append(_txn(src, money(m.group(1)), "debit", m.group(3), "card", card, on=parse_date(m.group(4), src.at.date())))
        cards.append(CardObs(id="", account_ref=card, at=src.at, available=money(m.group(5)),
                             source_ids=[src.id], source_label=src.label))
        return (txns, bals, cards, dues), True
    m = re.search(r"spent " + AMOUNT + r" .*?card no\. xx(\d{4}) (\S+) \S+ ist (.+?) avl limit", t, I)   # Axis
    if m:
        card = _card_ref(bank, m.group(2))
        txns.append(_txn(src, money(m.group(1)), "debit", m.group(4), "card", card,
                         on=parse_date(m.group(3), src.at.date())))
        lim = _LIMIT.search(t)
        if lim:
            cards.append(CardObs(id="", account_ref=card, at=src.at, available=money(lim.group(1)),
                                 source_ids=[src.id], source_label=src.label))
        return (txns, bals, cards, dues), True
    m = re.search(r"txn " + AMOUNT + r" on (\w+) bank card (\d{4}) at (\S+).*? on (\d{1,2}-\d{1,2})", t, I)   # HDFC
    if m:
        txns.append(_txn(src, money(m.group(1)), "debit", m.group(4), "card", _card_ref(bank, m.group(3)),
                         on=parse_date(m.group(5), src.at.date())))
        return (txns, bals, cards, dues), True

    # ── Card bill payments (credit on the card) ───────────────────────────────
    m = re.search(r"payment of " + AMOUNT + r" (?:has been |is )?received towards your .*?credit card", t, I) or \
        re.search(r"thank you for (?:your )?payment of " + AMOUNT + r" towards your .*?credit card", t, I) or \
        re.search(r"credit card (?:xx|x|ending with)?\s*[x*-]*\d{4} bill of " + AMOUNT + r" has been successfully paid", t, I)
    if m:
        c = _CARD.search(t) or re.search(r"ending with (\d{4})", t, I)
        card = _card_ref(bank, c.group(1)) if c else f"{bank} card"
        txns.append(_txn(src, money(m.group(1)), "credit", f"{bank} card payment", "card_payment", card,
                         on=_date_in(t, src, r"on " + DATE)))
        txns[-1].category = "Card payments"
        lim = _LIMIT.search(t)
        if lim and c:
            cards.append(CardObs(id="", account_ref=card, at=src.at, available=money(lim.group(1)),
                                 source_ids=[src.id], source_label=src.label))
        return (txns, bals, cards, dues), True

    # ── Bank account debits / credits ─────────────────────────────────────────
    m = re.search(AMOUNT + r" dr\. from a/c x*(\d+) and cr\. to (\S+?)\.? ref:\S+ avlbal:rs([\d,.]+)\((\d{4}:\d\d:\d\d)", t, I)
    if m:                                                                     # BOB debit
        acct = _acct_ref("BOB", m.group(2))
        on = parse_date(m.group(5), src.at.date())
        txns.append(_txn(src, money(m.group(1)), "debit", m.group(3), "upi", acct, money(m.group(4)), on))
        bals.append(_bal(src, acct, money(m.group(4))))
        return (txns, bals, cards, dues), True
    m = re.search(r"account is credited with " + AMOUNT + r" on (\d{4}-\d\d-\d\d).*?avlbal: ?rs([\d,.]+)", t, I)
    if m:                                                                     # BOB UPI credit (no a/c no.)
        on = parse_date(m.group(2), src.at.date())
        txns.append(_txn(src, money(m.group(1)), "credit", "UPI credit", "upi", "BOB", money(m.group(3)), on))
        bals.append(_bal(src, "BOB", money(m.group(3))))
        return (txns, bals, cards, dues), True
    m = re.search(AMOUNT + r" credited to a/c \.*(\d+) (?:thru \w+ utr \S+ by (.+?) \.|from:(\S+?)\.).*?avlbl amt:rs\.?([\d,.]+)\((\S+)", t, I)
    if m:                                                                     # BOB NEFT credit
        acct = _acct_ref("BOB", m.group(2))
        bal = money(m.group(5).rstrip("."))
        txns.append(_txn(src, money(m.group(1)), "credit", m.group(3) or m.group(4), "neft", acct, bal,
                         parse_date(m.group(6), src.at.date())))
        bals.append(_bal(src, acct, bal))
        return (txns, bals, cards, dues), True

    # Generic account debit/credit (IDFC, SBI, Kotak, Central Bank, …)
    if re.search(r"\b(debited|credited|dr\.?|cr\.?|sent|withdrawn|deposited)\b", t, I) and _LAST4.search(t) \
            and not re.search(r"will be debited|upcoming|mandate set for|scheduled", t, I):
        acct = _acct_ref(bank, _LAST4.search(t).group(1))
        amt = re.search(AMOUNT, t, I)
        if amt:
            first = re.search(r"\b(debited|credited|dr\.?|cr\.?|sent|withdrawn|deposited)\b", t, I).group(1).lower()
            direction = "credit" if first.startswith(("credit", "cr", "deposit")) else "debit"
            merch = re.search(r";\s*([A-Za-z][A-Za-z0-9 .&@_-]{2,40}?) credited", t, I) or \
                re.search(r"(?:\bto|\btowards|\bat|\bfrom|\bby (?!rs|inr))\s+([A-Za-z][A-Za-z0-9 .&@_-]{2,40}?)(?: credited| on |\.|;| ref| rrn| upi|$)", t, I)
            bal = _BAL.search(t)
            balance = money(bal.group(1)) if bal and money(bal.group(1)) != money(amt.group(1)) else None
            txns.append(_txn(src, money(amt.group(1)), direction, merch.group(1) if merch else f"{bank} transfer",
                             "upi" if "upi" in t.lower() else "transfer", acct, balance, _date_in(t, src, r"on " + DATE)))
            if balance is not None:
                bals.append(_bal(src, acct, balance))
            return (txns, bals, cards, dues), True

    # ── Upcoming debits and other dues ────────────────────────────────────────
    m = re.search(r"premium of " + AMOUNT + r"/?-? for policy no\. (\d+).*?is due on " + DATE, t, I)   # LIC
    if m:
        acct = _LAST4.search(t)
        dues.append(_due(src, f"LIC premium (policy {m.group(2)})", money(m.group(1)),
                         parse_date(m.group(3), src.at.date()), "premium",
                         _acct_ref("BOB", acct.group(1)) if acct else ""))
        return (txns, bals, cards, dues), True
    m = re.search(r"policy no\. (\d+) due on " + DATE + r" for " + AMOUNT, t, I)                      # Canara HSBC
    if m:
        dues.append(_due(src, f"{src.sender} premium (policy {m.group(1)})", money(m.group(3)),
                         parse_date(m.group(2), src.at.date()), "premium"))
        return (txns, bals, cards, dues), True
    m = re.search(r"bill for your (\w+) mobile\s+(\d+).*?amount to be paid:? " + AMOUNT + r".*?due date:? " + DATE, t, I)
    if m:
        dues.append(_due(src, f"{m.group(1).title()} mobile bill", money(m.group(3)),
                         parse_date(m.group(4), src.at.date()), "bill"))
        return (txns, bals, cards, dues), True
    m = re.search(r"(\w+) bill of " + AMOUNT + r" has been generated by (.+?)\. payment is due on " + DATE, t, I)
    if m:
        dues.append(_due(src, f"{normalize_merchant(m.group(3))} {m.group(1).lower()} bill", money(m.group(2)),
                         parse_date(m.group(4), src.at.date()), "bill"))
        return (txns, bals, cards, dues), True
    m = re.search(r"will be debited (?:with|by)? ?" + AMOUNT + r" towards (.+?) for the (?:upi )?mandate on " + DATE, t, I) \
        or re.search(AMOUNT + r" will be debited on " + DATE + r" from your .*? for (?:upcoming )?(.+?)\.", t, I)
    if m:
        if m.re.pattern.startswith("will"):
            amt, what, d = m.group(1), m.group(2), m.group(3)
        else:
            amt, d, what = m.group(1), m.group(2), m.group(3)
        acct = _LAST4.search(t) or re.search(r"(\d{4})-", t)
        dues.append(_due(src, f"Autopay: {normalize_merchant(what)}", money(amt), parse_date(d, src.at.date()),
                         "mandate", _acct_ref(bank, acct.group(1)) if acct else bank))
        return (txns, bals, cards, dues), True
    m = re.search(r"mandate set for (\d{4}-\d\d-\d\d).*?debited with ([\d,.]+) towards (.+?) for", t, I)      # BOB mandate
    if m:
        dues.append(_due(src, f"Autopay: {normalize_merchant(m.group(3))}", money(m.group(2)),
                         parse_date(m.group(1), src.at.date()), "mandate", "BOB"))
        return (txns, bals, cards, dues), True
    m = re.search(r"emi (?:of )?" + AMOUNT + r" (?:is )?due (tomorrow|today|on " + DATE + r")", t, I) or \
        re.search(r"emi:? " + AMOUNT + r" on " + DATE, t, I)
    if m:
        amt = money(m.group(1))
        when = m.group(2).lower()
        if when == "tomorrow":
            d = src.at.date().fromordinal(src.at.date().toordinal() + 1)
        elif when == "today":
            d = src.at.date()
        else:
            d = parse_date(m.groups()[-1], src.at.date())
        dues.append(_due(src, f"{src.sender} loan EMI", amt, d, "emi"))
        return (txns, bals, cards, dues), True

    # ── Payments that already happened (premiums, bills, wallets, MF buys) ────
    m = re.search(r"payment of " + AMOUNT + r" for your (.+?) policy no\. (\d+) has been successfully debited", t, I)
    if m:
        txns.append(_txn(src, money(m.group(1)), "debit", f"{m.group(2)} premium", "premium", "",
                         on=_date_in(t, src, r"debited on " + DATE)))
        return (txns, bals, cards, dues), True
    m = re.search(r"(?:received (?:the )?payment of|payment of) " + AMOUNT + r"(?: is updated against| for your| on)", t, I)
    if m and re.search(r"airtel|vi number|postpaid|mobile", t, I):
        txns.append(_txn(src, money(m.group(1)), "debit", f"{src.sender} bill", "bill", ""))
        return (txns, bals, cards, dues), True
    m = re.search(r"(?:sip )?purchase of " + AMOUNT + r" in (?:folio \S+ in )?(.+?)(?: for| \(folio| has been)", t, I) or \
        re.search(r"purchase (?:sip )?in folio \S+ in (.+?) for " + AMOUNT, t, I) or \
        re.search(r"investment in (.+?) of " + AMOUNT, t, I) or \
        re.search(r"payment of " + AMOUNT + r" towards your sip in (.+?) has been received", t, I)
    if m:
        g = m.groups()
        amt, fund = (g[0], g[1]) if re.match(r"[\d,.]+$", g[0]) else (g[1], g[0])
        txns.append(_txn(src, money(amt), "debit", fund, "sip", "", on=src.at.date()))
        txns[-1].category = "Investments"
        return (txns, bals, cards, dues), True
    m = re.search(r"wallet (?:debited|update)!? " + AMOUNT + r" debited on (\S+).*?(?:for|to) (.+?)\. (?:avl )?bal", t, I)
    if m:
        txns.append(_txn(src, money(m.group(1)), "debit", m.group(3), "wallet", f"{src.sender} wallet",
                         on=parse_date(m.group(2), src.at.date())))
        return (txns, bals, cards, dues), True
    m = re.search(r"debited with " + AMOUNT + r" on " + DATE + r" towards (.+?) autopay", t, I)
    if m:
        txns.append(_txn(src, money(m.group(1)), "debit", m.group(3), "autopay", "",
                         on=parse_date(m.group(2), src.at.date())))
        return (txns, bals, cards, dues), True

    m = re.search(r"(?:receipt of (?:renewal )?premium amount(?: of)?|premium amount) " + AMOUNT + r" (?:towards|against) your policy (?:no\.|number) (\d+)", t, I)
    if m:
        txns.append(_txn(src, money(m.group(1)), "debit", f"{src.sender} premium", "premium", ""))
        return (txns, bals, cards, dues), True
    m = re.search(r"payment of " + AMOUNT + r" for your (.+?) policy no\. (\d+) is due on " + DATE, t, I)
    if m:
        dues.append(_due(src, f"{m.group(2)} premium (policy {m.group(3)})", money(m.group(1)),
                         parse_date(m.group(4), src.at.date()), "premium"))
        return (txns, bals, cards, dues), True
    m = re.search(r"payment of " + AMOUNT + r" received towards your (.+?) account number", t, I)
    if m:                                                                     # loan repayment (Poonawalla)
        txns.append(_txn(src, money(m.group(1)), "debit", f"{src.sender} {m.group(2).title()} loan", "emi", ""))
        txns[-1].category = "Loans & EMI"
        return (txns, bals, cards, dues), True
    m = re.search(r"payment of " + AMOUNT + r" is credited to your vi number", t, I)
    if m:
        txns.append(_txn(src, money(m.group(1)), "debit", "Vi postpaid bill", "bill", ""))
        return (txns, bals, cards, dues), True
    m = re.search(AMOUNT + r" has been credited to your (\w+) account\. the amount is available for lending", t, I)
    if m:
        txns.append(_txn(src, money(m.group(1)), "debit", m.group(2), "investment", ""))
        txns[-1].category = "Investments"
        return (txns, bals, cards, dues), True

    # Money words but no rule: a leftover worth a look only if it reads like a transaction.
    finance = re.search(r"debit|credit|paid|payment|due|balance|bal\b|emi|premium|bill", t, I)
    return (txns, bals, cards, dues), not finance


_ENQUIRY = [
    (r"your cibil (?:score & report|mfi report|report) was checked by (.+?)(?: with)? ecn:?\s*\S+ on (\d{4}-\d\d-\d\d)", "CIBIL"),
    (r"your experian credit information report was (?:recently )?accessed by (.+?)(?: find|\.|$)", "Experian"),
    (r"your credit report from crif was fetched on (\S+) for .*? via (.+?)\.", "CRIF"),
]


def enquiry(src: Source):
    """A lender pulling the user's credit report (a hard enquiry): {lender, bureau, on, source_id}."""
    for pat, bureau in _ENQUIRY:
        m = re.search(pat, src.text, I)
        if not m:
            continue
        if bureau == "CRIF":
            lender, on = m.group(2), parse_date(m.group(1), src.at.date())
        elif bureau == "CIBIL":
            lender, on = m.group(1), parse_date(m.group(2), src.at.date())
        else:
            lender, on = m.group(1), src.at.date()
        return {"lender": lender.strip().title(), "bureau": bureau, "on": on or src.at.date(), "source_id": src.id}
    return None
