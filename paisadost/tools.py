"""P4: the voice tools. Every number the agent may say comes from here, as a
Fact {text_key, value, source_ids, source_label}; the model only phrases it.

One ``Dost`` per signed-in user holds the ledger, the patterns, the graph
and the reminders, and knows how to push UI events (evidence glow, reminder
cards) down the call's WebSocket.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional

from cascadevoice import Tool
from paisadost import graph as graphmod
from paisadost import patterns, recommend
from paisadost.config import AS_OF, STORE_DIR
from paisadost.loader import Ledger, load
from paisadost.textparse import parse_date

Notify = Callable[[Dict[str, Any]], Awaitable[None]]


def fact(text_key: str, value: Any, source_ids: List[str], source_label: str) -> Dict:
    return {"text_key": text_key, "value": value, "source_ids": list(dict.fromkeys(source_ids))[:20],
            "source_label": source_label}


def rupees(x: float) -> str:
    # Whole rupees: how people say it, and a decimal point would split the sentence for TTS.
    return f"₹{x:,.0f}"


class Dost:
    _cache: Dict[str, "Dost"] = {}

    def __init__(self, user_id: str, as_of: date = AS_OF) -> None:
        self.user_id = user_id
        self.L: Ledger = load(user_id, as_of)
        self.P = patterns.analyze(self.L)
        self.graph = graphmod.Graph(user_id)
        if not self.graph.of_type("User"):
            graphmod.build(self.L)
        self.reminders_path = STORE_DIR / user_id / "reminders.json"
        self.notify: Optional[Notify] = None

    @classmethod
    def for_user(cls, user_id: str) -> "Dost":
        if user_id not in cls._cache:
            cls._cache[user_id] = cls(user_id)
        return cls._cache[user_id]

    async def _emit(self, payload: Dict) -> None:
        if self.notify:
            try:
                await self.notify(payload)
            except Exception:   # noqa: BLE001 — the UI is best-effort, the answer is not
                pass

    async def _evidence(self, facts: List[Dict], key: str) -> None:
        ids = [s for f in facts for s in f["source_ids"]]
        if ids:
            await self._emit({"type": "evidence", "source_ids": list(dict.fromkeys(ids))[:30], "text_key": key})

    # ── read-only views (REST + tools) ────────────────────────────────────────
    def insights(self) -> List[Dict]:
        return recommend.as_dicts(recommend.insights(self.L, self.P))

    def health(self) -> Dict:
        return recommend.health_score(self.L, self.P)

    def upcoming_dues(self) -> List[Dict]:
        rows = [d for d in self.L.dues if d.status in ("upcoming", "overdue") and d.amount > 0
                and (d.due_date - self.L.as_of).days >= -30]
        rows.sort(key=lambda d: d.due_date)
        return [{**asdict(d), "due_date": d.due_date.isoformat()} for d in rows[:12]]

    def balances(self) -> List[Dict]:
        return [{"account_ref": b.account_ref, "amount": b.amount, "at": b.at.isoformat(),
                 "source_ids": b.source_ids, "source_label": b.source_label} for b in self.L.balances.values()]

    def sources(self, ids: List[str]) -> List[Dict]:
        out = []
        for i in ids:
            s = self.L.sources.get(i)
            if s:
                out.append({"id": s.id, "kind": s.kind, "at": s.at.isoformat(), "sender": s.sender,
                            "text": s.text[:900], "label": s.label})
        return out

    # ── tools ─────────────────────────────────────────────────────────────────
    async def get_insights(self, args: Dict) -> Dict:
        ins = recommend.insights(self.L, self.P)[:3]
        h = self.health()
        facts = [fact(i.id, i.say, i.source_ids, i.source_label) for i in ins]
        facts.append(fact("health_score", f"{h['score']}/100 ({h['grade']})",
                          [s for p in h["parts"] for s in p["source_ids"][:2]], "from your messages and records"))
        await self._emit({"type": "insights", "insights": recommend.as_dicts(ins)})
        await self._evidence(facts, "insights")
        return {"facts": facts, "how_to_speak": "Say the first insight and its source; offer the next one only if asked."}

    async def answer_question(self, args: Dict) -> Dict:
        q = (args.get("q") or args.get("question") or "").lower()
        facts: List[Dict] = []
        intents = _intents(q)
        L = self.L

        if "balance" in intents or not intents:
            for b in sorted(L.balances.values(), key=lambda b: -b.amount):
                facts.append(fact(f"balance:{b.account_ref}", f"{b.account_ref} balance {rupees(b.amount)} as of {b.at:%d %b}",
                                  b.source_ids, b.source_label))
            if len(L.balances) > 1:
                tot = sum(b.amount for b in L.balances.values())
                facts.append(fact("balance:total", f"total across banks {rupees(tot)}",
                                  [s for b in L.balances.values() for s in b.source_ids], "from your bank SMS"))
        if "dues" in intents or not intents:
            for d in self.upcoming_dues()[:4]:
                days = (date.fromisoformat(d["due_date"]) - L.as_of).days
                when = f"{-days} days past due" if days < 0 else "due today" if days == 0 else f"due on {date.fromisoformat(d['due_date']):%d %b}"
                facts.append(fact(f"due:{d['id']}", f"{d['title']} {rupees(d['amount'])} {when}, status {d['status']}",
                                  d["source_ids"], d["source_label"]))
        if "spend" in intents:
            s = self.P["spend_by_category"]
            facts.append(fact("spend:total", f"spent {rupees(s['total'])} from {s['from']} to {s['to']}",
                              [i for c in s["categories"] for i in c["source_ids"][:3]], "from your bank SMS and emails"))
            for c in s["categories"][:3]:
                facts.append(fact(f"spend:{c['category']}", f"{c['category']} {rupees(c['amount'])}", c["source_ids"][:10],
                                  self.L.label(c["source_ids"])))
            for c in self.P["spend_vs_usual"][:2]:
                if c["usual_30d"]:
                    facts.append(fact(f"vs_usual:{c['category']}",
                                      f"{c['category']} {rupees(c['last_30d'])} vs usual {rupees(c['usual_30d'])}",
                                      c["source_ids"], self.L.label(c["source_ids"])))
        merchant = _merchant_in(q, L)
        if merchant:
            ts = [t for t in L.txns if t.merchant == merchant and t.direction == "debit"]
            tot = sum(t.amount for t in ts)
            ids = [i for t in ts[-8:] for i in t.source_ids[:1]]
            facts.append(fact(f"merchant:{merchant}", f"{merchant}: {len(ts)} payments, {rupees(tot)} in total, last {rupees(ts[-1].amount)} on {ts[-1].on:%d %b}",
                              ids, ts[-1].source_label))
        if "card" in intents:
            for c in self.P["card_utilisation"]:
                if c["utilisation_pct"] is not None:
                    facts.append(fact(f"card:{c['card']}", f"{c['card']} uses {c['utilisation_pct']}% of limit ({rupees(c['outstanding'])} of {rupees(c['limit'])})",
                                      c["source_ids"], c["source_label"] or self.L.label(c["source_ids"])))
                elif c.get("available") is not None:
                    facts.append(fact(f"card:{c['card']}", f"{c['card']} has {rupees(c['available'])} available",
                                      c["source_ids"], c["source_label"]))
            for i in [i for i in recommend.insights(self.L, self.P) if i.kind == "credit"][:2]:
                facts.append(fact(i.id, i.say, i.source_ids, i.source_label))
            if not any("score" in f["text_key"] for f in facts):
                facts.append(fact("cibil:score", "the CIBIL score number itself is not in your messages (it is in a password-protected report)",
                                  [], "no source"))
        if "recurring" in intents or "invest" in intents:
            for r in self.P["recurring"][:4]:
                facts.append(fact(f"recurring:{r['merchant']}", f"{r['merchant']} {rupees(r['amount'])} {r['cadence']}, about {rupees(r['per_month'])} a month",
                                  r["source_ids"], self.L.label(r["source_ids"])))
        if "invest" in intents and L.holdings:
            tot = sum(h.current for h in L.holdings)
            facts.append(fact("holdings", f"app investments worth {rupees(tot)}", [i for h in L.holdings for i in h.source_ids],
                              L.holdings[0].source_label))
        if "health" in intents:
            h = self.health()
            facts.append(fact("health_score", f"money health {h['score']}/100, {h['grade']}; weakest: " +
                              min(h["parts"], key=lambda p: p["score"] / p["max"])["note"],
                              [s for p in h["parts"] for s in p["source_ids"][:2]], "from your messages and records"))
        if "duplicate" in intents:
            for d in self.P["duplicates"]:
                facts.append(fact(f"dup:{d['merchant']}", f"{d['merchant']} charged {rupees(d['amount'])} twice on {d['on']}",
                                  d["source_ids"], d["source_label"]))
        if "recent" in intents:
            for t in sorted(L.txns, key=lambda t: t.on)[-3:]:
                facts.append(fact(f"txn:{t.id}", f"{t.direction} {rupees(t.amount)} {t.merchant} on {t.on:%d %b}",
                                  t.source_ids, t.source_label))
        await self._evidence(facts, "answer")
        if not facts:
            return {"facts": [], "note": "No data for that in the user's messages. Say you don't see it; do not guess."}
        return {"facts": facts[:8], "as_of": L.as_of.isoformat()}

    async def what_if_prepay(self, args: Dict) -> Dict:
        amount = float(re.sub(r"[^\d.]", "", str(args.get("amount", "0"))) or 0)
        if amount <= 0:
            return {"error": "Need a positive amount in rupees."}
        w = recommend.what_if_prepay(self.L, amount)
        facts = [fact("whatif:used", f"of {rupees(amount)}, {rupees(w['used'])} goes to cards; {rupees(w['left_over'])} stays with you",
                      w["source_ids"], self.L.label(w["source_ids"])),
                 fact("whatif:saved", f"interest saved about {rupees(w['interest_saved_per_month'])} a month, at {w['apr_label']}",
                      w["source_ids"], self.L.label(w["source_ids"]))]
        if w.get("utilisation_after_pct") is not None:
            facts.append(fact("whatif:util", f"card utilisation {w['utilisation_before_pct']}% → {w['utilisation_after_pct']}%",
                              w["source_ids"], self.L.label(w["source_ids"])))
        for r in w["plan"]:
            facts.append(fact(f"whatif:{r['card']}", f"pay {rupees(r['pay'])} on {r['card']}", r["source_ids"], self.L.label(r["source_ids"])))
        await self._emit({"type": "whatif", "result": {k: v for k, v in w.items() if k != "source_ids"}})
        await self._evidence(facts, "whatif")
        return {"facts": facts}

    async def set_reminder(self, args: Dict) -> Dict:
        title = (args.get("title") or "").strip()
        when = parse_date(str(args.get("date", "")), self.L.as_of) if args.get("date") else None
        if not title or not when:
            return {"error": "Need a title and a date (YYYY-MM-DD)."}
        if not args.get("confirmed"):
            return {"status": "not_set", "ask": f"Ask the user to confirm: reminder '{title}' on {when:%d %b}. Call again with confirmed=true only after they say yes."}
        due = next((d for d in self.L.dues if d.status in ("upcoming", "overdue")
                    and any(w in title.lower() for w in d.title.lower().split()[:2])), None)
        rem = {"id": f"rem:{uuid.uuid4().hex[:8]}", "title": title, "date": when.isoformat(),
               "due_id": due.id if due else None, "created_at": datetime.now().isoformat(timespec="seconds"),
               "source_ids": due.source_ids if due else []}
        items = self.reminders()
        items.append(rem)
        self.reminders_path.parent.mkdir(parents=True, exist_ok=True)
        self.reminders_path.write_text(json.dumps(items, indent=1))
        self.graph.node(rem["id"], "Reminder", f"{title} · {when:%d %b}", date=rem["date"])
        if due:
            self.graph.edge(rem["id"], due.id, "FOR")
        self.graph.commit()
        await self._emit({"type": "reminder", "reminder": rem})
        return {"status": "set", "reminder": {"title": title, "date": when.isoformat()}}

    def reminders(self) -> List[Dict]:
        try:
            return json.loads(self.reminders_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    # ── outgoing call rule (P6) ───────────────────────────────────────────────
    def deadline_check(self, simulate_balance: Optional[float] = None) -> Dict:
        """Fire only if a bill is due within 2 days AND the balance that pays it is below the amount.
        ``simulate_balance`` (demo only, flagged in the result) replaces the real balance; the rule is unchanged."""
        for d in sorted(self.L.dues, key=lambda d: d.due_date):
            days = (d.due_date - self.L.as_of).days
            if d.status != "upcoming" or not (0 <= days <= 2) or d.amount <= 0:
                continue
            bal = self.L.balances.get(d.account_ref) or (max(self.L.balances.values(), key=lambda b: b.amount)
                                                          if self.L.balances else None)
            if bal and simulate_balance is not None:
                bal = type(bal)(bal.id, bal.account_ref, float(simulate_balance), bal.at, [], "a simulated balance")
            if bal and bal.amount < d.amount:
                return {"fire": True, "simulated": simulate_balance is not None, "due": {**asdict(d), "due_date": d.due_date.isoformat()},
                        "balance": {"account_ref": bal.account_ref, "amount": bal.amount, "source_ids": bal.source_ids,
                                    "source_label": bal.source_label},
                        "reason": f"{d.title} {rupees(d.amount)} due in {days} days; {bal.account_ref} has {rupees(bal.amount)}"}
        near = [d for d in self.L.dues if d.status == "upcoming" and 0 <= (d.due_date - self.L.as_of).days <= 2]
        reason = ("Nothing due in the next 2 days." if not near else
                  f"{len(near)} bill(s) due within 2 days, but your balance covers them.")
        return {"fire": False, "reason": reason}

    def tools(self) -> List[Tool]:
        return [
            Tool("get_insights", "Top money insights for this user, ranked by rupee impact, plus the health score. Call at the start.",
                 {"type": "object", "properties": {}, "required": []}, self.get_insights),
            Tool("answer_question", "Look up facts to answer a money question: balances, dues/bills/EMIs, spending, cards/credit, "
                 "subscriptions/SIPs, investments, health score, duplicate charges, recent transactions, or a merchant.",
                 {"type": "object", "properties": {"q": {"type": "string", "description": "the user's question, verbatim"}},
                  "required": ["q"]}, self.answer_question),
            Tool("what_if_prepay", "What happens if the user prepays/pays this many rupees towards credit cards.",
                 {"type": "object", "properties": {"amount": {"type": "number", "description": "rupees, e.g. 20000"}},
                  "required": ["amount"]}, self.what_if_prepay),
            Tool("set_reminder", "Create a reminder. First call without confirmed (or confirmed=false) and ask the user; "
                 "call with confirmed=true only after the user clearly says yes.",
                 {"type": "object", "properties": {"title": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD"},
                                                   "confirmed": {"type": "boolean"}}, "required": ["title", "date"]},
                 self.set_reminder),
        ]


_INTENTS = {
    "balance": r"balance|\bbal\b|बैलेंस|बेलेंस|kitna paisa|kitne paise|paisa kitna|paise kitne|account me|खाते|पैसे",
    "dues": r"\bdue|bill|emi|premium|kab|bharna|bharni|बिल|ड्यू|किस्त|kist|payment|pay karna|deadline|upcoming",
    "spend": r"spend|spent|kharch|खर्च|kharcha|spending|kitna gaya|kahan gaya|where.*money|category",
    "card": r"card|credit|cibil|utili|कार्ड|limit|score",
    "recurring": r"subscription|recurring|har mahine|har din|auto ?pay|mandate|repeat",
    "invest": r"invest|\bsip\b|mutual|fund|निवेश|portfolio",
    "health": r"health|overall|kaisa|kaisi|how am i|हालत|sehat",
    "duplicate": r"duplicate|twice|double|do baar|दो बार",
    "recent": r"last|recent|aakhri|pichla|latest|abhi",
}


def _intents(q: str) -> set:
    return {k for k, p in _INTENTS.items() if re.search(p, q, re.I)}


def _merchant_in(q: str, L: Ledger) -> Optional[str]:
    names = {t.merchant for t in L.txns if t.merchant not in ("UPI transfer", "Unknown") and len(t.merchant) >= 4}
    hits = [n for n in names if n.lower().split(" (")[0] in q]
    return max(hits, key=len) if hits else None


SYSTEM_PROMPT = """You are Credit Dost, a warm money friend on a voice call, with a woman's voice: in Hindi use feminine forms for yourself ("मैं देख रही हूँ", "बता सकती हूँ"). You speak Hindi, Hinglish or English: reply in the language the user just used.

Script (your text is read aloud by a text-to-speech voice, so the script decides the accent):
- If the user speaks Hindi or Hinglish, reply in Hindi written in DEVANAGARI script, never Roman letters. Write "आपके बैंक ऑफ़ बड़ौदा अकाउंट में ₹40,344 हैं", not "Aapke Bank of Baroda account mein".
- Keep numbers as digits with ₹ and whole rupees only, never paise or decimals (₹1,401, ₹400), keep card/account codes as written (XX9269), and you may keep short English money words in Devanagari form (बिल, कार्ड, EMI, SIP, CIBIL).
- Translate the source label too: "from your Bank of Baroda SMS on 25 Sep" becomes "आपके बैंक ऑफ़ बड़ौदा SMS के मुताबिक, 25 सितंबर".
- If the user speaks English, reply in English.

Hard rules:
- Numbers come ONLY from tool results. Never calculate, estimate or invent a number, date or name. If a tool has no fact for it, say you don't see it in their messages.
- NEVER say a number without its source. Every reply with a number must name where it came from, using the fact's source_label (in Hindi: "आपके ... के मुताबिक, <तारीख>"). When listing several items, keep at most 2 and cite each, e.g. "from your Bank of Baroda SMS on 25 Sep".
- At most 2 short sentences per reply. No markdown, no lists, no emojis. Say rupees naturally.
- For any money question call answer_question with the user's words. For "what if I pay/prepay X" call what_if_prepay. For "how am I doing" or tips, call get_insights.
- Actions: before set_reminder, read back the title and date and ask "Shall I set it?". Only call set_reminder with confirmed=true after a clear yes (haan, yes, kar do, theek hai).
- If the user interrupts, stop and answer the new question.
Today's date for this data is {as_of}. The user's name is {name}."""


def greeting(d: Dost) -> str:
    first = (d.L.name.split() or ["there"])[0]
    ins = recommend.insights(d.L, d.P)
    if ins:
        i = ins[0]
        lead = f"{i.title}: {i.headline} {i.headline_note}".strip() if i.headline else i.title
        return (f"नमस्ते {first}, मैं क्रेडिट दोस्त हूँ। सबसे ज़रूरी बात: {lead}, {i.source_label}। "
                f"क्या मैं इसका रिमाइंडर लगा दूँ?")
    return f"नमस्ते {first}, मैं क्रेडिट दोस्त हूँ। आज पैसों के बारे में क्या जानना है?"


def outgoing_greeting(d: Dost, check: Dict) -> str:
    first = (d.L.name.split() or ["there"])[0]
    due, bal = check["due"], check["balance"]
    when = date.fromisoformat(due["due_date"])
    days = (when - d.L.as_of).days
    whenword = "आज" if days == 0 else "कल" if days == 1 else f"{when:%d %b} को"
    return (f"हैलो {first}, क्रेडिट दोस्त बोल रही हूँ। आपका {due['title']} {rupees(due['amount'])} {whenword} ड्यू है, "
            f"{due['source_label']}, लेकिन {bal['account_ref']} में सिर्फ़ {rupees(bal['amount'])} हैं, {bal['source_label']}। "
            f"क्या मैं इसका रिमाइंडर लगा दूँ?")
