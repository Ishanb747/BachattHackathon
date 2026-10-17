"""P4: the voice tools. Every number the agent may say comes from here, as a
Fact {text_key, value, source_ids, source_label}; the model only phrases it.

One ``Dost`` per signed-in user holds the ledger, the patterns, the graph
and the reminders, and knows how to push UI events (evidence glow, reminder
cards) down the call's WebSocket.
"""

from __future__ import annotations

import asyncio
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
        self.speak = None                     # set during a call: say a line out loud
        from paisadost import documents
        if documents.list_docs(user_id):
            documents.reapply_all(self)
            self.refresh()

    def refresh(self) -> None:
        """Recompute everything after new facts arrived (a document was fed in)."""
        self.P = patterns.analyze(self.L)
        graphmod.build(self.L)

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

    async def _evidence(self, facts: List[Dict], key: str, top: int = 3) -> None:
        # Light up only what is being said: the first few facts (tools order them most-relevant first).
        ids = [s for f in facts[:top] for s in f["source_ids"][:4]]
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
            cr = getattr(L, "credit_report", None)
            if cr:
                facts.insert(0, fact("cibil:score", f"{cr['bureau']} credit score {cr['score']:.0f}" + (f" (report date {cr['date']})" if cr.get("date") else ""),
                                     cr["source_ids"], cr["source_label"]))
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
        month = _month_in(q, L.as_of)
        if "cashflow" in intents and month:
            row = next((m for m in patterns.income_by_month(L) if m["month"] == month), None)
            if row:
                ids = row["source_ids"]
                facts.append(fact(f"cash:month:{month}", f"in {row['label']} you received {rupees(row['received'])} across {row['count']} credits"
                                  + (f" (messages cover {row['covered']} only)" if row["partial"] else ""), ids, self.L.label(ids)))
                if row["large"]:
                    facts.append(fact(f"cash:month_large:{month}", f"of that, {rupees(row['large'])} came as large deposits of ₹5,000+", ids, self.L.label(ids)))
                if row["top_payers"]:
                    facts.append(fact(f"cash:month_top:{month}", "biggest payers: " + ", ".join(f"{p['from']} {rupees(p['amount'])}" for p in row["top_payers"][:2]), ids, self.L.label(ids)))
            else:
                facts.append(fact(f"cash:month:{month}", f"no bank messages cover {month}", [], "no source"))
        if "cashflow" in intents:
            c = patterns.cashflow(L)
            if c.get("months"):
                in_ids = [i for r in c["income_items"] for i in r["source_ids"]][:6]
                fx_ids = [i for r in c["fixed_items"] for i in r["source_ids"]][:6]
                facts.append(fact("cash:income", f"regular income about {rupees(c['income'])} a month" +
                                  (f" (mostly from {c['income_items'][0]['from']})" if c["income_items"] else ""), in_ids, self.L.label(in_ids)))
                facts.append(fact("cash:fixed", f"fixed spending about {rupees(c['fixed'])} a month ({c['fixed_ratio_pct']}% of income); biggest: " +
                                  ", ".join(f"{r['what']} {rupees(r['per_month'])}" for r in c["fixed_items"][:3]), fx_ids, self.L.label(fx_ids)))
                facts.append(fact("cash:free", f"left after fixed costs about {rupees(c['free'])} a month", in_ids + fx_ids, "from your bank SMS"))
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
            bank = [t for t in L.txns if t.source_ids[0].split(":")[0] in ("sms", "email")]
            recent = sorted(bank, key=lambda t: (t.on, t.at.timestamp() if t.at else 0))[-5:][::-1]
            for t in recent:
                facts.append(fact(f"txn:{t.id}", f"{'paid' if t.direction == 'debit' else 'received'} {rupees(t.amount)} "
                                  f"{'to' if t.direction == 'debit' else 'from'} {t.merchant} on {t.on:%d %b}", t.source_ids, t.source_label))
            biggest = max((t for t in bank if t.direction == "debit" and (L.as_of - t.on).days <= 30), key=lambda t: t.amount, default=None)
            if biggest:
                facts.append(fact(f"txn:big:{biggest.id}", f"biggest payment in the last 30 days: {rupees(biggest.amount)} to {biggest.merchant} on {biggest.on:%d %b}",
                                  biggest.source_ids, biggest.source_label))
        # Most specific first: a named merchant/card beats the generic balance/dues lists.
        order = ["cibil", "cash:", "txn:", "merchant:", "card:", "whatif", "dup:", "recurring:", "holdings", "health", "spend", "vs_usual", "due:", "txn:", "balance:"]
        rank = lambda f: next((i for i, p in enumerate(order) if f["text_key"].startswith(p)), len(order))
        if "dues" in intents and "card" in intents:
            # "YES card bill": the matching card's due first.
            words = [w for w in q.split() if len(w) >= 3]
            facts.sort(key=lambda f: (0 if f["text_key"].startswith("due:") and any(w in f["value"].lower() for w in words) else 1, rank(f)))
        else:
            facts.sort(key=rank)
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

    # ── advisor tools ─────────────────────────────────────────────────────────
    async def web_lookup(self, args: Dict) -> Dict:
        """Live web search for prices, rates, product facts. Cited by site."""
        q = (args.get("query") or "").strip()
        if not q:
            return {"error": "Need a query."}
        def run():
            from openai import OpenAI
            from cascadevoice.defaults import load_keys
            r = OpenAI(api_key=load_keys().openai).responses.create(
                model="gpt-4o-mini", tools=[{"type": "web_search"}],
                input=f"{q}\nAnswer for India in 2 short sentences with prices in rupees if relevant, and name the source website.")
            urls = re.findall(r"https?://([^/\s)]+)", r.output_text)
            return {"answer": re.sub(r"\(\[([^\]]+)\]\([^)]+\)\)", r"(\1)", r.output_text)[:600],
                    "sources": list(dict.fromkeys(u.replace("www.", "") for u in urls))[:3]}
        try:
            out = await asyncio.to_thread(run)
        except Exception as exc:   # noqa: BLE001
            return {"error": f"web search failed: {exc!r}"[:200]}
        await self._emit({"type": "web", "query": q, "answer": out["answer"], "sources": out["sources"]})
        return {**out, "how_to_cite": "say 'according to <source site>' for any number from here"}

    async def assess_purchase(self, args: Dict) -> Dict:
        """Can the user afford this? Their real balance, spending, dues and forecast decide; the code does the maths."""
        item = (args.get("item") or "this").strip()
        price = args.get("price")
        web = None
        if not price:
            web = await self.web_lookup({"query": f"current price in India of {item}"})
            m = re.search(r"₹\s?([\d,]+(?:\.\d+)?)", (web or {}).get("answer", ""))
            price = float(m.group(1).replace(",", "")) if m else None
        else:
            price = float(re.sub(r"[^\d.]", "", str(price)) or 0)
        if not price:
            return {"error": f"Could not find a price for {item}; ask the user for it.", "web": web}
        L, P = self.L, self.P
        bank = sum(b.amount for b in L.balances.values())
        monthly = P["monthly_outflow"] or 1
        due30 = sum(d.amount for d in L.dues if d.status in ("upcoming", "overdue") and (d.due_date - L.as_of).days <= 30 and d.amount > 0)
        fc = patterns.forecast(L)
        low = fc["lowest"]["balance"] if fc.get("lowest") else bank
        after = bank - price
        months_after = after / monthly
        low_after = low - price
        if low_after >= 3 * monthly:
            verdict = "affordable"
        elif low_after >= monthly:
            verdict = "a stretch"
        else:
            verdict = "not advisable now"
        bal_ids = [s for b in L.balances.values() for s in b.source_ids]
        facts = [
            fact("buy:price", f"{item} costs about {rupees(price)}" + (f" according to {', '.join(web['sources'])}" if web and web.get("sources") else " (price you gave)"),
                 [], ", ".join(web["sources"]) if web and web.get("sources") else "the user"),
            fact("buy:bank", f"you have {rupees(bank)} across banks", bal_ids, self.L.label(bal_ids)),
            fact("buy:after", (f"after buying you'd have {rupees(after)}, about {months_after:.1f} months of your usual spending ({rupees(monthly)}/month)"
                               if after >= 0 else f"you'd be short by {rupees(-after)}: it costs more than all your bank money"), bal_ids, self.L.label(bal_ids)),
            fact("buy:dues", f"{rupees(due30)} of bills are due in the next 30 days", [s for d in L.dues for s in d.source_ids[:1]][:6], "from your bills"),
            fact("buy:verdict", f"verdict: {verdict} (rule: keep at least 3 months of spending after committed bills)", bal_ids, "Credit Dost's rule"),
        ]
        cf = patterns.cashflow(L)
        if cf.get("income"):
            inc_ids = [i for r in cf["income_items"] for i in r["source_ids"]][:4]
            facts.append(fact("buy:income", f"your regular income is about {rupees(cf['income'])} a month and about {rupees(cf['free'])} is left after fixed costs",
                              inc_ids, self.L.label(inc_ids)))
            if cf["free"] > 0:
                months_to_save = price / cf["free"]
                facts.append(fact("buy:save", f"saving all of that, it would take about {months_to_save:.0f} months to pay for it in cash"
                                  if months_to_save >= 1 else "one month's spare money covers it", inc_ids, self.L.label(inc_ids)))

        await self._evidence(facts[1:], "advice")
        return {"facts": facts, "verdict": verdict,
                "how_to_answer": "Give the verdict; say the price WITH its website ('according to <site>') if looked up; then reason with their monthly income and what is left after fixed costs, and say how many months of saving it takes (buy:save); end with one smarter alternative."}

    async def get_forecast(self, args: Dict) -> Dict:
        fc = patterns.forecast(self.L)
        if not fc.get("series"):
            return {"facts": [], "note": fc.get("note")}
        low, neg = fc["lowest"], fc["first_negative"]
        facts = [fact("fc:low", f"lowest point {rupees(low['balance'])} on {low['date']}", fc["source_ids"], self.L.label(fc["source_ids"])),
                 fact("fc:out", f"{rupees(fc['committed_out'])} of known bills and repeating charges until {fc['end']}", fc["source_ids"], "from your recurring charges and bills")]
        if fc.get("monthly_income"):
            facts.append(fact("fc:in", f"counts your usual income of about {rupees(fc['monthly_income'])} around day {fc['income_day']} of each month",
                              fc["source_ids"], "from your repeat deposits"))
        if neg:
            facts.insert(0, fact("fc:neg", f"balance would go below zero on {neg['date']}", fc["source_ids"], self.L.label(fc["source_ids"])))
        await self._emit({"type": "forecast", "forecast": {k: v for k, v in fc.items() if k != "source_ids"}})
        await self._evidence(facts, "forecast")
        return {"facts": facts, "note": fc["note"]}

    async def get_score_coach(self, args: Dict) -> Dict:
        c = recommend.score_coach(self.L, self.P)
        facts = [fact(f"coach:{i}", f"{st['action']} — {st['why']}", st["source_ids"], self.L.label(st["source_ids"])) for i, st in enumerate(c["steps"])]
        if c["score"]:
            facts.insert(0, fact("coach:score", f"current score {c['score']:.0f}", [], c["score_source"]))
        await self._evidence(facts, "coach")
        return {"facts": facts, "note": c["note"]}

    async def draft_dispute(self, args: Dict) -> Dict:
        dups = self.P["duplicates"]
        if not dups:
            return {"facts": [], "note": "No double charges found in the messages."}
        d = recommend.dispute_draft(self.L, dups[0])
        await self._emit({"type": "dispute", "draft": d})
        await self._evidence([fact("dispute", d["subject"], d["source_ids"], dups[0]["source_label"])], "dispute")
        return {"drafted": True, "subject": d["subject"], "to": d["to"],
                "how_to_answer": "Say the refund email is drafted on screen, for which charge, and that they can copy and send it."}

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
            Tool("assess_purchase", "Should the user buy/spend on something (a watch, phone, trip, car)? Checks affordability against their real "
                 "balance, spending, bills and forecast. Looks the price up on the web if not given.",
                 {"type": "object", "properties": {"item": {"type": "string"}, "price": {"type": "number", "description": "rupees, if the user said it"}},
                  "required": ["item"]}, self.assess_purchase),
            Tool("web_lookup", "Search the web for current prices, interest rates, product or scheme facts in India.",
                 {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}, self.web_lookup),
            Tool("get_forecast", "30-day balance forecast from known bills and repeating charges: lowest point, whether it goes below zero.",
                 {"type": "object", "properties": {}, "required": []}, self.get_forecast),
            Tool("get_score_coach", "How to improve the credit/CIBIL score: concrete rupee-sized steps from the user's data.",
                 {"type": "object", "properties": {}, "required": []}, self.get_score_coach),
            Tool("draft_dispute", "Draft a refund-request email to the bank for a double charge.",
                 {"type": "object", "properties": {}, "required": []}, self.draft_dispute),
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
    "cashflow": r"income|salary|kamai|kamata|aamdani|earn|fixed|receiv|aaya|aaye|mila|mile|credited|deposit|har mahine ka kharcha|monthly expense|cash ?flow|bachat|save|savings|afford",
    "duplicate": r"duplicate|twice|double|do baar|दो बार",
    "recent": r"last|recent|aakhri|pichla|latest|abhi|transaction|txn|len ?den|लेन-देन|लेनदेन|ट्रांज़ैक्शन|payments?|debit|kharche kahan|statement",
}


_MONTHS = {1: r"jan|जनवरी|janvari", 2: r"feb|फ़रवरी|फरवरी|farvari", 3: r"mar(ch)?\b|मार्च", 4: r"apr|अप्रैल|aprail",
           5: r"\bmay\b|मई", 6: r"jun|जून", 7: r"jul|जुलाई|julai", 8: r"aug|अगस्त|agast|agust", 9: r"sep|सितंबर|सितम्बर|sitambar|sitamber",
           10: r"oct|अक्टूबर|aktubar|october", 11: r"nov|नवंबर|navambar", 12: r"dec|दिसंबर|disambar"}


def _month_in(q: str, as_of) -> Optional[str]:
    """'September', 'सितंबर', 'pichle mahine' → '2026-09'."""
    if re.search(r"last month|pichle mahine|pichhle mahine|पिछले महीने", q):
        y, m = (as_of.year, as_of.month - 1) if as_of.month > 1 else (as_of.year - 1, 12)
        return f"{y}-{m:02d}"
    if re.search(r"this month|is mahine|इस महीने", q):
        return f"{as_of.year}-{as_of.month:02d}"
    for m, pat in _MONTHS.items():
        if re.search(pat, q, re.I):
            y = as_of.year if m <= as_of.month else as_of.year - 1
            return f"{y}-{m:02d}"
    return None


def _intents(q: str) -> set:
    return {k for k, p in _INTENTS.items() if re.search(p, q, re.I)}


def _merchant_in(q: str, L: Ledger) -> Optional[str]:
    names = {t.merchant for t in L.txns if t.merchant not in ("UPI transfer", "Unknown") and len(t.merchant) >= 4}
    hits = [n for n in names if n.lower().split(" (")[0] in q]
    return max(hits, key=len) if hits else None


SYSTEM_PROMPT = """You are Credit Dost, a warm money friend on a voice call, with a man's voice: in Hindi use masculine forms for yourself ("मैं देख रहा हूँ", "बता सकता हूँ"). You speak Hindi, Hinglish or English: reply in the language the user just used.

Script (your text is read aloud by a text-to-speech voice, so the script decides the accent):
- If the user speaks Hindi or Hinglish, reply in Hindi written in DEVANAGARI script, never Roman letters. Write "आपके बैंक ऑफ़ बड़ौदा अकाउंट में ₹40,344 हैं", not "Aapke Bank of Baroda account mein".
- Keep numbers as digits with ₹ and whole rupees only, never paise or decimals (₹1,401, ₹400), keep card/account codes as written (XX9269), and you may keep short English money words in Devanagari form (बिल, कार्ड, EMI, SIP, CIBIL).
- Translate the source label too: "from your Bank of Baroda SMS on 25 Sep" becomes "आपके बैंक ऑफ़ बड़ौदा SMS के मुताबिक, 25 सितंबर".
- If the user speaks English, reply in English.

Hard rules:
- Numbers come ONLY from tool results. Never calculate, estimate or invent a number, date or name. If a tool has no fact for it, say you don't see it in their messages.
- NEVER say a number without its source. Every reply with a number must name where it came from, using the fact's source_label (in Hindi: "आपके ... के मुताबिक, <तारीख>"). When listing several items, keep at most 2 and cite each, e.g. "from your Bank of Baroda SMS on 25 Sep".
How the call flows (inbound — the user called you):
- You already greeted them and asked how you can help. Do NOT bring up dues, overdue bills or alerts on your own; wait for what they ask. (Due alerts have their own outgoing call.)
- If the request is vague ("kuch batao", "help", "what can you do"), ask ONE short question offering choices: balance, bills and dues, spending and transactions, credit score, or a purchase decision.
- Each reply: a short acknowledgement, the answer with its source, then (only if natural) one brief offer of a related next step, e.g. "क्या मैं इसका रिमाइंडर लगा दूँ?" or "पिछले महीने से तुलना करूँ?". Never chain several offers.
- Sound like a person on the phone: warm, short, no lists. If they say thanks or bye, close politely and call end_call.

You are a thoughtful financial ADVISOR, not a reader of alerts:
- Answer the question actually asked. Do not repeat the greeting's topic or an earlier point unless the user brings it up.
- For decisions ("should I buy a Rolex", "can I afford a trip", "should I take this loan", "invest in X"), think it through: call assess_purchase (it checks their real money and looks up prices), add web_lookup for rates/facts if useful, then give a clear recommendation, the 1–2 numbers that decide it with their sources, and one smarter alternative. Up to 4 short sentences for advice; 2 for simple lookups.
- For balances, bills, spending, cards, SIPs, CIBIL: answer_question. "What if I pay/prepay X": what_if_prepay. "Will I run out of money", "next month": get_forecast. "Improve my score": get_score_coach. Double charge / refund: draft_dispute. "How am I doing" or tips: get_insights.
- You know the user's monthly income (regular repeat deposits) and what is left after fixed costs, and month-by-month money received. Use them: "how much did I get in September" → answer_question; for any future or affordability question reason with income, fixed costs and the forecast (which already adds expected income).
- Facts from web_lookup are external: say "according to <site>".
- No markdown, no lists, no emojis. Say rupees naturally.
- Actions: before set_reminder, read back the title and date and ask "Shall I set it?". Only call set_reminder with confirmed=true after a clear yes (haan, yes, kar do, theek hai).
- If the user interrupts, stop and answer the new question.
Today's date for this data is {as_of}. The user's name is {name}."""


def greeting(d: Dost) -> str:
    """Inbound call: greet and offer help. Alerts are not pushed here; the outgoing call handles dues."""
    first = (d.L.name.split() or ["there"])[0]
    return (f"नमस्ते {first}, मैं क्रेडिट दोस्त हूँ, आपका पैसों का साथी। "
            f"बताइए, आज मैं आपकी क्या मदद करूँ? बैलेंस, बिल और ड्यूज़, खर्च और ट्रांज़ैक्शन, क्रेडिट स्कोर, "
            f"या किसी बड़ी खरीदारी पर सलाह?")


def outgoing_greeting(d: Dost, check: Dict) -> str:
    first = (d.L.name.split() or ["there"])[0]
    due, bal = check["due"], check["balance"]
    when = date.fromisoformat(due["due_date"])
    days = (when - d.L.as_of).days
    whenword = "आज" if days == 0 else "कल" if days == 1 else f"{when:%d %b} को"
    return (f"हैलो {first}, क्रेडिट दोस्त बोल रहा हूँ। आपका {due['title']} {rupees(due['amount'])} {whenword} ड्यू है, "
            f"{due['source_label']}, लेकिन {bal['account_ref']} में सिर्फ़ {rupees(bal['amount'])} हैं, {bal['source_label']}। "
            f"क्या मैं इसका रिमाइंडर लगा दूँ?")
