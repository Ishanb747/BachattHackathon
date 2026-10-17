"""Amounts, dates and merchants out of Indian bank text. Regex only."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

AMOUNT = r"(?:rs\.?|inr|₹)\s*:?\s*(\d[\d,]*(?:\.\d+)?)"
_AMOUNT_RE = re.compile(AMOUNT, re.I)

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def money(s: str) -> float:
    return float(s.replace(",", ""))


def first_amount(text: str) -> Optional[float]:
    m = _AMOUNT_RE.search(text)
    return money(m.group(1)) if m else None


def _year(y: str, ref: date) -> int:
    y = int(y)
    return y + 2000 if y < 100 else y


def parse_date(s: str, ref: date) -> Optional[date]:
    """Day-first Indian formats; a date without a year takes the one nearest ``ref``."""
    s = s.strip().rstrip(".,")
    m = re.fullmatch(r"(\d{4})[-:/](\d{1,2})[-:/](\d{1,2})", s)
    if m:
        return _safe(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)
    if m:
        return _safe(_year(m[3], ref), int(m[2]), int(m[1]))
    m = re.fullmatch(r"(\d{1,2})[-/ ]?([A-Za-z]{3})[A-Za-z]*[-/, ]*(\d{2,4})?", s)
    if m:
        mon = _MONTHS.get(m[2].lower())
        if mon:
            return _with_year(int(m[1]), mon, m[3], ref)
    m = re.fullmatch(r"([A-Za-z]{3})[A-Za-z]*\.? (\d{1,2})(?:st|nd|rd|th)?,? ?(\d{4})?", s)
    if m:
        mon = _MONTHS.get(m[1].lower())
        if mon:
            return _with_year(int(m[2]), mon, m[3], ref)
    m = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})", s)       # "On 14-09"
    if m:
        return _with_year(int(m[1]), int(m[2]), None, ref)
    return None


def _with_year(day: int, mon: int, y: Optional[str], ref: date) -> Optional[date]:
    if y:
        return _safe(_year(y, ref), mon, day)
    best = None
    for yy in (ref.year - 1, ref.year, ref.year + 1):
        d = _safe(yy, mon, day)
        if d and (best is None or abs((d - ref).days) < abs((best - ref).days)):
            best = d
    return best


def _safe(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


DATE = (r"(\d{4}[-:/]\d{1,2}[-:/]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{1,2}[-/ ][A-Za-z]{3,9}[-/, ]*\d{2,4}"
        r"|[A-Za-z]{3,9}\.? \d{1,2}(?:st|nd|rd|th)?,? ?\d{4}|[A-Za-z]{3} \d{1,2}|\d{1,2} [A-Za-z]{3,9})")


# ── Merchants ─────────────────────────────────────────────────────────────────

_VPA_NOISE = re.compile(r"(\.rzp|\.payu|\.easebuzz|\.bdpg|ombk\.|paytm\.|bharatpe\.|q\d+|\d{4,}|@\S+|privulg|pvt|private|limited|ltd|marketplace|priv)", re.I)

# A few brands appear under many names; the first match wins.
_ALIASES = [   # regex, display name
    ("airtel", "Airtel"), ("zepto", "Zepto"), ("swiggy", "Swiggy"), ("zomato", "Zomato"),
    ("flipkart", "Flipkart"), ("amazon", "Amazon"), ("trusave", "Trusave (SIP)"), ("bachatt", "Trusave (SIP)"), ("angel", "Angel One MF"),
    ("canara", "Canara HSBC Life"), ("chl", "Canara HSBC Life"), ("policybazaar", "Policybazaar"),
    ("jvvnl", "JVVNL Electricity"), ("vidyut", "JVVNL Electricity"), ("mobikwik", "MobiKwik"),
    ("phonepe", "PhonePe"), (r"\bcred\b", "CRED"), ("kiwi", "Kiwi"), ("indmoney", "INDmoney"),
    (r"\blic\b", "LIC"), ("dainik", "Dainik Bhaskar"), ("motilal", "Motilal Oswal MF"), ("bandhan", "Bandhan MF"),
    ("icici prudential", "ICICI Prudential MF"), (r"hdfc (mf|mutual)", "HDFC MF"), ("srimandir", "Sri Mandir"),
]


def normalize_merchant(raw: str) -> str:
    low = raw.lower()
    for key, name in _ALIASES:
        if re.search(key, low):
            return name
    s = _VPA_NOISE.sub(" ", raw)
    s = re.sub(r"[^A-Za-z ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    words = s.split()
    # A random UPI handle ("ombk.AAGV136451lhdpwsx4zv@mbk") leaves letter soup, not a name.
    if not words or "@" in raw and (sum(len(w) <= 2 for w in words) >= 2 or not any(len(w) >= 4 and re.search(r"[aeiou]", w, re.I) for w in words)):
        return "UPI transfer"
    return s.title()[:40]


_CATEGORIES = [
    ("Groceries & food", r"zepto|blinkit|swiggy|zomato|bigbasket|instamart|dmart|grocery|restaurant|food"),
    ("Shopping", r"flipkart|amazon|myntra|ajio|meesho|croma|tata ?cliq|reliance digital"),
    ("Bills & recharges", r"airtel|jio|vodafone|\bvi\b|electric|jvvnl|vidyut|broadband|gas|water|dth|postpaid|recharge"),
    ("Insurance", r"lic|insurance|policy|premium|canara|hsbc life|policybazaar|care health|icici lombard"),
    ("Investments", r"sip|mutual|mutul|\bmf\b|fund|trusave|angel ?one|groww|zerodha|indmoney|smallcase|folio|lendenclub"),
    ("Card payments", r"credit card|card bill|cred\b|kiwi"),
    ("Loans & EMI", r"\bemi\b|loan|finance|fincorp|instamoney|kreditbee|navi|moneyview"),
    ("Transfers", r"neft|imps|transfer|self|upi"),
]


def categorize(*texts: str) -> str:
    blob = " ".join(texts).lower()
    for name, pat in _CATEGORIES:
        if re.search(pat, blob):
            return name
    return "Other"
