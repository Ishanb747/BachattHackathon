"""Feed Credit Dost: drop in a credit report or statement; it reads, verifies, merges.

    result = ingest(dost, data, filename, password)

1. Text out of the file (pdftotext, with the user's own password if the PDF is locked).
2. An LLM lists what the document says: score, accounts, limits, balances,
   enquiries, dues. Extraction only — it reads numbers, never computes them.
3. Every number is checked against the document text; one that is not there is dropped.
4. The facts merge into the user's ledger as new cited Sources, and patterns,
   insights, health score and the graph are recomputed. The diff is returned.
"""

from __future__ import annotations

import json
import re
import subprocess
import uuid
from datetime import date, datetime
from typing import Dict, List, Optional

from paisadost.config import STORE_DIR
from paisadost.loader import Card
from paisadost.models import Balance, Due, Source
from paisadost.sources import IST
from paisadost.textparse import parse_date

MODEL = "gpt-4o"
DOC_LABEL = {"cibil_report": "credit report", "bank_statement": "bank statement", "card_statement": "card statement", "other": "document"}


class DocError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


PROMPT = """You read Indian personal-finance documents (CIBIL / Experian / CRIF credit reports, bank statements,
credit-card statements). Return JSON only:
{"doc_type": "cibil_report"|"bank_statement"|"card_statement"|"other",
 "bureau": string|null, "holder_name": string|null, "report_date": string|null,
 "credit_score": "<digits exactly as printed>"|null,
 "accounts": [{"lender": str, "type": "credit_card"|"loan"|"savings"|"current"|"other", "account_ref": "<masked no. as printed>"|null,
               "limit": "<as printed>"|null, "outstanding": "<as printed>"|null, "overdue": "<as printed>"|null,
               "status": str|null, "dpd_recent": "<days past due as printed>"|null}],
 "enquiries": [{"lender": str, "date": "<as printed>"}],
 "balances": [{"account_ref": str, "amount": "<as printed>", "date": "<as printed>"}],
 "dues": [{"title": str, "amount": "<as printed>", "due_date": "<as printed>", "min_amount": "<as printed>"|null}],
 "summary": ["<= 4 short plain-English lines on what this document shows"]}
Copy every number EXACTLY as printed in the text. Never compute, total or guess. Omit what is not there.
At most 25 accounts and 25 enquiries, most recent first."""


# ── 1. text ───────────────────────────────────────────────────────────────────

def extract_text(path, name: str, password: Optional[str]) -> (str, int):
    if name.lower().endswith((".txt", ".csv", ".md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        return text, 1
    if not name.lower().endswith(".pdf"):
        raise DocError("unreadable", "Upload a PDF, TXT or CSV file.")
    cmd = ["pdftotext", "-layout"]
    if password:
        cmd += ["-upw", password]
    r = subprocess.run(cmd + [str(path), "-"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        if "password" in (r.stderr or "").lower():
            if password:
                raise DocError("password_wrong", "That password did not open the PDF. Try again.")
            raise DocError("password_required", "This PDF is password-protected. Enter its password.")
        raise DocError("unreadable", "Could not read this PDF.")
    pages = r.stdout.count("\f") or 1
    if len(r.stdout.strip()) < 40:
        raise DocError("unreadable", "This PDF has no readable text (it may be a scanned image).")
    return r.stdout, pages


# ── 2–3. extract + verify ─────────────────────────────────────────────────────

def _llm(text: str) -> Dict:
    from openai import OpenAI
    from cascadevoice.defaults import load_keys
    client = OpenAI(api_key=load_keys().openai)
    r = client.chat.completions.create(model=MODEL, temperature=0, response_format={"type": "json_object"},
                                       messages=[{"role": "system", "content": PROMPT},
                                                 {"role": "user", "content": text[:60000]}])
    return json.loads(r.choices[0].message.content)


def _num(raw, text_digits: str) -> Optional[float]:
    """The number, only if those digits are printed in the document."""
    if raw in (None, ""):
        return None
    s = re.sub(r"[^\d.]", "", str(raw))
    if not s or s == ".":
        return None
    core = s.rstrip("0").rstrip(".") if "." in s else s
    if core not in text_digits and s not in text_digits:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _snippet(text: str, needle: str, width: int = 160) -> str:
    i = text.find(needle) if needle else -1
    if i < 0:
        return ""
    return re.sub(r"\s+", " ", text[max(0, i - width // 2): i + width // 2]).strip()


# ── 4. merge ──────────────────────────────────────────────────────────────────

def _docs_index(user_id: str):
    return STORE_DIR / user_id / "docs.json"


def list_docs(user_id: str) -> List[Dict]:
    p = _docs_index(user_id)
    return json.loads(p.read_text()) if p.exists() else []


def apply(L, doc: Dict) -> None:
    """Merge one ingested document into the ledger (idempotent per doc id)."""
    did, at = doc["id"], datetime.fromisoformat(doc["at"])
    kind = DOC_LABEL.get(doc["doc_type"], "document")
    sender = f"uploaded {(doc.get('bureau') or '').strip() + ' ' if doc.get('bureau') else ''}{kind}".replace("  ", " ")

    def src(i, text) -> str:
        sid = f"doc:{did}:{i}"
        s = Source(id=sid, kind="doc", at=at, sender=sender, text=text or doc["name"])
        L.sources[sid] = s
        return sid

    for i, f in enumerate(doc["facts"]):
        f["source_id"] = src(i, f.get("snippet") or f"{f['label']}: {f['value']}")
        f["source_label"] = "from " + L.sources[f["source_id"]].label

    for f in doc["facts"]:
        sid, kind_ = f["source_id"], f["kind"]
        if kind_ == "score":
            L.credit_report = {"score": f["num"], "bureau": doc.get("bureau") or "credit bureau", "date": doc.get("report_date"),
                               "source_ids": [sid], "source_label": f["source_label"]}
        elif kind_ == "card":
            ref = f["ref"]
            c = L.cards.get(ref) or Card(ref)
            if f.get("limit") is not None:
                c.limit = f["limit"]
            if f.get("outstanding") is not None:
                c.outstanding = f["outstanding"]
                if c.limit:
                    c.available = round(c.limit - c.outstanding, 2)
            c.source_ids = [sid] + [s for s in c.source_ids if s != sid]
            c.source_label = f["source_label"]
            L.cards[ref] = c
        elif kind_ == "enquiry":
            # Same day = the same check, whatever the lender is called in each place ("Au Sfb" / "AU Small Finance Bank").
            if not any(e["on"] == f["on"] for e in L.enquiries):
                L.enquiries.append({"lender": f["lender"], "bureau": doc.get("bureau") or "report", "on": f["on"], "source_id": sid})
        elif kind_ == "balance":
            b = Balance(id=f"bal:{sid}", account_ref=f["ref"], amount=f["num"], at=at, source_ids=[sid], source_label=f["source_label"])
            old = L.balances.get(f["ref"])
            if not old or old.at <= at:
                L.balances[f["ref"]] = b
        elif kind_ == "due":
            if not any(d.id == f"due:{sid}" for d in L.dues):
                status = "overdue" if f["on"] < L.as_of else "upcoming"
                L.dues.append(Due(id=f"due:{sid}", title=f["title"], amount=f["num"], due_date=f["on"], kind="card" if "card" in f["title"].lower() else "bill",
                                  min_amount=f.get("min"), status=status, source_ids=[sid], source_label=f["source_label"]))
        elif kind_ == "loan":
            L.report_loans = [x for x in getattr(L, "report_loans", []) if x["ref"] != f["ref"]] + [f]


def _facts(x: Dict, text: str, as_of: date) -> List[Dict]:
    digits = text.replace(",", "")
    facts: List[Dict] = []
    score = _num(x.get("credit_score"), digits)
    if score and 300 <= score <= 900:
        facts.append({"kind": "score", "label": "Credit score", "value": f"{score:.0f}", "num": score,
                      "snippet": _snippet(text, str(x.get("credit_score")))})
    for a in (x.get("accounts") or [])[:25]:
        lender = (a.get("lender") or "Lender").strip().title()[:30]
        tail = re.sub(r"\D", "", str(a.get("account_ref") or ""))[-4:]
        limit, out = _num(a.get("limit"), digits), _num(a.get("outstanding"), digits)
        if a.get("type") == "credit_card" and (limit or out is not None):
            from paisadost.parse_sms import _BANKS
            short = next((name for key, name in _BANKS if key in lender.lower()), lender.split()[0])
            ref = f"{short} card XX{tail}" if tail else f"{short} card"
            parts = [f"limit ₹{limit:,.0f}" if limit else "", f"owed ₹{out:,.0f}" if out is not None else ""]
            facts.append({"kind": "card", "label": ref, "value": ", ".join(p for p in parts if p), "ref": ref,
                          "limit": limit, "outstanding": out,
                          "snippet": _snippet(text, str(a.get("limit") or a.get("outstanding") or lender))})
        elif a.get("type") == "loan" and out is not None:
            ref = f"{lender} loan" + (f" XX{tail}" if tail else "")
            facts.append({"kind": "loan", "label": ref, "value": f"₹{out:,.0f} outstanding" + (f", {a.get('status')}" if a.get("status") else ""),
                          "ref": ref, "num": out, "snippet": _snippet(text, str(a.get("outstanding")))})
    for e in (x.get("enquiries") or [])[:25]:
        on = parse_date(str(e.get("date") or ""), as_of)
        if on and e.get("lender"):
            facts.append({"kind": "enquiry", "label": "Credit check", "value": f"{e['lender'].title()} on {on:%d %b %Y}",
                          "lender": e["lender"].strip().title(), "on": on, "snippet": _snippet(text, str(e.get("date")))})
    for b in (x.get("balances") or [])[:5]:
        amt = _num(b.get("amount"), digits)
        if amt is not None:
            ref = str(b.get("account_ref") or "Account")[:30]
            facts.append({"kind": "balance", "label": f"{ref} balance", "value": f"₹{amt:,.0f}", "ref": ref, "num": amt,
                          "snippet": _snippet(text, str(b.get("amount")))})
    for d in (x.get("dues") or [])[:5]:
        amt, on = _num(d.get("amount"), digits), parse_date(str(d.get("due_date") or ""), as_of)
        if amt is not None and on:
            facts.append({"kind": "due", "label": d.get("title") or "Payment due", "value": f"₹{amt:,.0f} due {on:%d %b}",
                          "title": d.get("title") or "Payment due", "num": amt, "on": on, "min": _num(d.get("min_amount"), digits),
                          "snippet": _snippet(text, str(d.get("amount")))})
    return facts


def ingest(dost, data: bytes, name: str, password: Optional[str]) -> Dict:
    from paisadost import patterns, recommend
    did = uuid.uuid4().hex[:10]
    folder = STORE_DIR / dost.user_id / "docs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{did}-{re.sub(r'[^A-Za-z0-9._-]', '_', name)[-80:]}"
    path.write_bytes(data)
    try:
        text, pages = extract_text(path, name, password)
    except DocError:
        path.unlink(missing_ok=True)
        raise
    x = _llm(text)
    facts = _facts(x, text, dost.L.as_of)
    if not facts:
        raise DocError("nothing_found", "I could read the file but found no money facts I could verify in it.")

    before = _snapshot(dost)
    doc = {"id": did, "name": name, "doc_type": x.get("doc_type") or "other", "bureau": x.get("bureau"),
           "report_date": x.get("report_date"), "pages": pages, "at": datetime.now(IST).isoformat(timespec="seconds"),
           "summary": [s for s in (x.get("summary") or [])][:4], "facts": facts}
    apply(dost.L, doc)
    dost.refresh()
    after = _snapshot(dost)

    store = [{**doc, "facts": [{k: (v.isoformat() if isinstance(v, date) else v) for k, v in f.items()} for f in doc["facts"]]}]
    _docs_index(dost.user_id).write_text(json.dumps(list_docs(dost.user_id) + store, indent=1, ensure_ascii=False))
    changes = [{"label": k, "before": before[k], "after": after[k]} for k in after if before.get(k) != after[k]]
    public = {**doc, "facts": [{"label": f["label"], "value": f["value"], "source_label": f["source_label"]} for f in facts]}
    return {"doc": public, "changes": changes, "health_before": before["Money health"], "health_after": after["Money health"]}


def _snapshot(dost) -> Dict:
    from paisadost import recommend
    L, P = dost.L, dost.P
    util = P["card_utilisation"][-1]["utilisation_pct"] if P["card_utilisation"] and P["card_utilisation"][-1]["card"].startswith("ALL") else None
    cr = getattr(L, "credit_report", None)
    return {"Money health": recommend.health_score(L, P)["score"],
            "Credit score": int(cr["score"]) if cr else "unknown",
            "Cards with known limit": sum(1 for c in L.cards.values() if c.limit),
            "Card utilisation": f"{util}%" if util is not None else "unknown",
            "Credit checks (90 days)": P["enquiries"]["count"],
            "Open dues": sum(1 for d in L.dues if d.status in ("upcoming", "overdue"))}


def reapply_all(dost) -> None:
    """On startup: merge every document this user has fed in before."""
    for d in list_docs(dost.user_id):
        for f in d["facts"]:
            if isinstance(f.get("on"), str):
                f["on"] = date.fromisoformat(f["on"])
        apply(dost.L, d)
