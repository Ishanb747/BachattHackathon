"""The last resort for SMS no regex understood: gpt-4o-mini labels them.

Regex first, always (context.md). This only sees the leftovers, returns
structured fields, and is checked against the text: an amount that does
not appear in the SMS itself is thrown away, so the LLM can read numbers
but never invent one. Results are cached per user, so it runs once.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional, Tuple

from paisadost.config import STORE_DIR
from paisadost.models import Due, Source, Txn
from paisadost.parse_sms import PROMO
from paisadost.textparse import categorize, normalize_merchant, parse_date

logger = logging.getLogger(__name__)
MODEL = "gpt-4o-mini"

PROMPT = """You label Indian bank/fintech SMS. For each SMS return one JSON object:
{"id": <id>, "kind": "txn" | "due" | "none", "direction": "debit" | "credit" | null,
 "amount": "<the amount exactly as written in the SMS, digits only>" | null,
 "merchant": "<payee / payer / biller>" | null, "date": "<date as written>" | null}
"txn" = money already moved. "due" = a bill/EMI/premium the user must pay by a date. Otherwise "none"
(offers, OTPs, failed payments, refunds initiated, statements without amounts).
Reply with {"items": [...]} only."""


def _cache_path(user_id: str):
    return STORE_DIR / user_id / "llm_leftovers.json"


def label(user_id: str, sources: List[Source]) -> Dict[str, dict]:
    path = _cache_path(user_id)
    cache: Dict[str, dict] = json.loads(path.read_text()) if path.exists() else {}
    todo = [s for s in sources if s.id not in cache]
    if todo:
        try:
            from openai import OpenAI
            from cascadevoice.defaults import load_keys
            client = OpenAI(api_key=load_keys().openai)
            for i in range(0, len(todo), 25):
                batch = todo[i:i + 25]
                msg = "\n".join(json.dumps({"id": s.id, "sms": s.text[:400]}, ensure_ascii=False) for s in batch)
                r = client.chat.completions.create(model=MODEL, temperature=0, response_format={"type": "json_object"},
                                                   messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": msg}])
                for item in json.loads(r.choices[0].message.content).get("items", []):
                    if item.get("id"):
                        cache[item["id"]] = item
                for s in batch:
                    cache.setdefault(s.id, {"id": s.id, "kind": "none"})
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
        except Exception as exc:   # noqa: BLE001 — the fallback is optional; regex results stand
            logger.warning(f"[LLM fallback] skipped: {exc!r}")
    return cache


def _verified_amount(item: dict, text: str) -> Optional[float]:
    raw = re.sub(r"[^\d.]", "", str(item.get("amount") or ""))
    if not raw:
        return None
    digits = text.replace(",", "")
    if raw not in digits and raw.rstrip("0").rstrip(".") not in digits:
        return None          # not in the SMS: never trust an amount the model produced itself
    try:
        return float(raw)
    except ValueError:
        return None


def records(user_id: str, sources: List[Source]) -> Tuple[List[Txn], List[Due]]:
    labels = label(user_id, sources)
    by_id = {s.id: s for s in sources}
    txns: List[Txn] = []
    dues: List[Due] = []
    for sid, item in labels.items():
        src = by_id.get(sid)
        if not src or item.get("kind") not in ("txn", "due"):
            continue
        # Offers dressed as alerts ("funds ready for disbursal", "convert to EMI") are not money that moved.
        if PROMO.search(src.text) or re.search(r"verify|authori[sz]e|disburs|initiated|switch-in", src.text, re.I):
            continue
        amount = _verified_amount(item, src.text)
        if not amount:
            continue
        when = parse_date(str(item.get("date") or ""), src.at.date()) if item.get("date") else None
        merchant = normalize_merchant(item.get("merchant") or src.sender)
        label_txt = src.label + " (read by AI)"
        if item["kind"] == "txn" and item.get("direction") in ("debit", "credit"):
            txns.append(Txn(id="", amount=amount, direction=item["direction"], on=when or src.at.date(), merchant=merchant,
                            type="other", category=categorize(merchant, src.text) if item["direction"] == "debit" else "Income & refunds",
                            at=src.at, source_ids=[src.id], source_label=label_txt))
        elif item["kind"] == "due" and when:
            dues.append(Due(id="", title=f"{merchant} payment", amount=amount, due_date=when, kind="bill",
                            source_ids=[src.id], source_label=label_txt))
    return txns, dues
