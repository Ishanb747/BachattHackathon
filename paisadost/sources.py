"""Raw readers: one user's SMS, emails and structured CSV rows, as Sources.

Nothing is interpreted here, only read, cleaned (HTML stripped, time in
IST) and given a stable id the UI can point back to.
"""

from __future__ import annotations

import csv
import html
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterator, List

from paisadost.config import DATA_DIR
from paisadost.models import Source

csv.field_size_limit(10**9)
IST = timezone(timedelta(hours=5, minutes=30))

# DLT sender suffixes → a name people say out loud.
SENDER_NAMES = {
    "BOBSMS": "Bank of Baroda", "BOBTXN": "Bank of Baroda", "BOBONE": "BOBCARD", "IDFCFB": "IDFC FIRST Bank",
    "YESBNK": "YES Bank", "INDUSB": "IndusInd Bank", "AXISBK": "Axis Bank", "HDFCBK": "HDFC Bank", "HDFCBN": "HDFC Bank",
    "SBIBNK": "SBI", "CBSSBI": "SBI", "SBIINB": "SBI", "KOTAKB": "Kotak Bank", "ICICIB": "ICICI Bank", "ICICIT": "ICICI Bank",
    "PNBSMS": "PNB", "CENTBK": "Central Bank", "AIRBNK": "Airtel Payments Bank", "LICIND": "LIC", "CHLins": "Canara HSBC Life",
    "POLBAZ": "Policybazaar", "AIRBIL": "Airtel", "AIRTEL": "Airtel", "AIRINF": "Airtel", "BAJAJF": "Bajaj Pay",
    "MOBIKW": "MobiKwik", "GKIWIP": "Kiwi", "ANGONE": "Angel One", "IPRUMF": "ICICI Prudential MF", "ABSLMF": "Aditya Birla MF",
    "DSPAMC": "DSP MF", "MOAMCL": "Motilal Oswal MF", "UTIAMC": "UTI MF", "AXISMF": "Axis MF", "CIBILA": "CIBIL",
    "PFINCO": "Poonawalla Fincorp", "TRCRED": "True Credits", "BRNCHI": "Branch", "ISTMNY": "InstaMoney",
}


def sender_name(dlt: str) -> str:
    """'JX-BOBSMS-S' → 'Bank of Baroda'."""
    parts = dlt.split("-")
    key = parts[1] if len(parts) >= 2 else dlt
    return SENDER_NAMES.get(key, key)


def _ist(stamp: str) -> datetime:
    dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if dt.tzinfo is None:          # sms.csv is already IST, naive
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def iter_sms(user_id: str) -> Iterator[Source]:
    seen = set()
    with open(DATA_DIR / "sms" / "sms.csv", newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            if row["user_id"] != user_id:
                continue
            body = re.sub(r"\s+", " ", row["body_text"]).strip()
            at = _ist(row["received_at_ist"])
            # Operators resend the same text from several headers within minutes.
            key = (body, at.replace(second=0, microsecond=0))
            if key in seen:
                continue
            seen.add(key)
            src = Source(id=f"sms:{row['sms_id']}", kind="sms", at=at, sender=sender_name(row["sender"]), text=body)
            src.dlt = row["sender"]   # type: ignore[attr-defined]
            yield src


_TAG = re.compile(r"<(style|script)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)


def clean_html(text: str) -> str:
    text = _TAG.sub(" ", text)
    text = html.unescape(text).replace("‌", " ").replace("͏", " ")
    return re.sub(r"\s+", " ", text).strip()


def _from_name(subject: str, body: str) -> str:
    blob = f"{subject} {body[:400]}".lower()
    for key, name in (("yes bank", "YES Bank"), ("indusind", "IndusInd Bank"), ("idfc", "IDFC FIRST Bank"),
                      ("hdfc", "HDFC Bank"), ("axis", "Axis Bank"), ("sbi", "SBI"), ("airtel", "Airtel"),
                      ("lic", "LIC"), ("cred", "CRED"), ("kotak", "Kotak Bank"), ("icici", "ICICI Bank")):
        if re.search(rf"\b{key}\b", blob):
            return name
    m = re.match(r"payment successful for (.+)", subject, re.I)
    if m:
        return f"{m.group(1).strip()} payment"
    return " ".join(subject.split()[:3]) or "email"


def iter_emails(user_id: str) -> Iterator[Source]:
    with open(DATA_DIR / "emails" / "emails.csv", newline="", encoding="utf-8", errors="replace") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            if row["user_id"] != user_id:
                continue
            body = clean_html(row["body"])
            subject = row["subject"].strip()
            src = Source(id=f"email:{i}", kind="email", at=_ist(row["received_at"]),
                         sender=_from_name(subject, body), text=f"{subject} — {body}")
            src.subject = subject            # type: ignore[attr-defined]
            src.body = body                  # type: ignore[attr-defined]
            src.attachments = row["attachments_path"]  # type: ignore[attr-defined]
            yield src


def read_user_rows(rel_path: str, user_id: str) -> List[Dict[str, str]]:
    with open(DATA_DIR / rel_path, newline="", encoding="utf-8", errors="replace") as fh:
        return [r for r in csv.DictReader(fh) if r.get("user_id") == user_id]


def read_rows(rel_path: str) -> List[Dict[str, str]]:
    with open(DATA_DIR / rel_path, newline="", encoding="utf-8", errors="replace") as fh:
        return list(csv.DictReader(fh))


def user_profile(user_id: str) -> Dict[str, str]:
    for r in read_rows("emails/users_data.csv"):
        if r["user_id"] == user_id:
            return r
    return {}
