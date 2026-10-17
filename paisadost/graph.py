"""The user's money as a property graph, stored in SQLite.

    User ─OWNS→ Account | Card | Policy | SIP
    Txn ─FROM→ Account | Card      Txn ─TO→ Merchant
    Due ─ON→ Card | Account | Policy | SIP
    (anything) ─EVIDENCED_BY→ Source
    Insight ─ABOUT→ (anything)     Reminder ─FOR→ Due

One database per user: data/<user_id>/graph.db. Facts point at their proof
through EVIDENCED_BY edges, so "how do you know?" is a one-hop query and
the UI can light up the path from a spoken number to the SMS behind it.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from typing import Dict, Iterable, List, Optional

from paisadost.config import STORE_DIR
from paisadost.loader import Ledger

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (id TEXT PRIMARY KEY, type TEXT NOT NULL, label TEXT, props TEXT);
CREATE TABLE IF NOT EXISTS edges (src TEXT NOT NULL, dst TEXT NOT NULL, rel TEXT NOT NULL, props TEXT,
                                  PRIMARY KEY (src, dst, rel));
CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst);
CREATE INDEX IF NOT EXISTS nodes_type ON nodes(type);
"""


class Graph:
    def __init__(self, user_id: str) -> None:
        self.path = STORE_DIR / user_id / "graph.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.executescript(SCHEMA)

    # ── writes ───────────────────────────────────────────────────────────────
    def node(self, id: str, type: str, label: str, **props) -> str:
        self.db.execute("INSERT OR REPLACE INTO nodes VALUES (?,?,?,?)", (id, type, label, json.dumps(props, default=str)))
        return id

    def edge(self, src: str, dst: str, rel: str, **props) -> None:
        self.db.execute("INSERT OR REPLACE INTO edges VALUES (?,?,?,?)", (src, dst, rel, json.dumps(props, default=str)))

    def evidence(self, node_id: str, source_ids: Iterable[str]) -> None:
        for s in source_ids:
            self.edge(node_id, s, "EVIDENCED_BY")

    def commit(self) -> None:
        self.db.commit()

    def clear(self) -> None:
        self.db.executescript("DELETE FROM nodes; DELETE FROM edges;")

    # ── reads ────────────────────────────────────────────────────────────────
    def get(self, id: str) -> Optional[dict]:
        row = self.db.execute("SELECT id, type, label, props FROM nodes WHERE id=?", (id,)).fetchone()
        return _node(row) if row else None

    def of_type(self, type: str) -> List[dict]:
        return [_node(r) for r in self.db.execute("SELECT id, type, label, props FROM nodes WHERE type=?", (type,))]

    def neighbours(self, id: str, rel: Optional[str] = None) -> List[dict]:
        q = ("SELECT n.id, n.type, n.label, n.props FROM edges e JOIN nodes n ON n.id = "
             "CASE WHEN e.src=? THEN e.dst ELSE e.src END WHERE (e.src=? OR e.dst=?)")
        args = [id, id, id]
        if rel:
            q += " AND e.rel=?"
            args.append(rel)
        return [_node(r) for r in self.db.execute(q, args)]

    def sources_of(self, id: str) -> List[dict]:
        return self.neighbours(id, "EVIDENCED_BY")

    def subgraph(self, max_txns: int = 120) -> Dict[str, list]:
        """What the UI draws: every non-Txn node, the most recent Txns, and their Sources."""
        keep = {r[0] for r in self.db.execute("SELECT id FROM nodes WHERE type NOT IN ('Txn','Source')")}
        keep |= {r[0] for r in self.db.execute(
            "SELECT id FROM nodes WHERE type='Txn' ORDER BY json_extract(props,'$.on') DESC LIMIT ?", (max_txns,))}
        links = []
        for src, dst, rel in self.db.execute("SELECT src, dst, rel FROM edges"):
            if src in keep and (dst in keep or rel == "EVIDENCED_BY"):
                keep.add(dst)
                links.append({"source": src, "target": dst, "rel": rel})
        marks = ",".join("?" * len(keep))
        nodes = [_node(r) for r in self.db.execute(f"SELECT id, type, label, props FROM nodes WHERE id IN ({marks})", list(keep))]
        return {"nodes": nodes, "links": links}


def _node(row) -> dict:
    return {"id": row[0], "type": row[1], "label": row[2], "props": json.loads(row[3] or "{}")}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def build(ledger: Ledger) -> Graph:
    g = Graph(ledger.user_id)
    g.clear()
    user = g.node(f"user:{ledger.user_id}", "User", ledger.name or ledger.user_id, as_of=ledger.as_of.isoformat())

    for s in ledger.sources.values():
        g.node(s.id, "Source", s.label, kind=s.kind, sender=s.sender, at=s.at.isoformat(), text=s.text[:700])

    def account(ref: str) -> Optional[str]:
        if not ref:
            return None
        is_card = " card" in ref
        nid = ("card:" if is_card else "acct:") + _slug(ref)
        if not g.get(nid):
            g.node(nid, "Card" if is_card else "Account", ref)
            g.edge(user, nid, "OWNS")
        return nid

    for ref, b in ledger.balances.items():
        nid = account(ref)
        g.node(nid, "Account", ref, balance=b.amount, balance_at=b.at.isoformat(), source_label=b.source_label)
        g.evidence(nid, b.source_ids)

    for ref, c in ledger.cards.items():
        nid = account(ref)
        g.node(nid, "Card", ref, available=c.available, outstanding=c.outstanding, limit=c.limit,
               source_label=c.source_label)
        g.evidence(nid, c.source_ids)

    for t in ledger.txns:
        tid = g.node(t.id, "Txn", f"₹{t.amount:,.0f} {t.merchant}", amount=t.amount, direction=t.direction,
                     on=t.on.isoformat(), merchant=t.merchant, category=t.category, txn_type=t.type,
                     source_label=t.source_label)
        acct = account(t.account_ref)
        if acct:
            g.edge(tid, acct, "FROM")
        mid = "merchant:" + _slug(t.merchant)
        if not g.get(mid):
            g.node(mid, "Merchant", t.merchant, category=t.category)
        g.edge(tid, mid, "TO")
        g.evidence(tid, t.source_ids)

    for d in ledger.dues:
        did = g.node(d.id, "Due", f"{d.title} ₹{d.amount:,.0f}", amount=d.amount, due_date=d.due_date.isoformat(),
                     kind=d.kind, status=d.status, title=d.title, source_label=d.source_label)
        target = account(d.account_ref) if " card" in d.account_ref else None
        if d.kind == "premium":
            pid = "policy:" + _slug(d.title)
            if not g.get(pid):
                g.node(pid, "Policy", d.title.split(" (")[0] + (" " + d.title.split("(")[1].rstrip(")") if "(" in d.title else ""))
                g.edge(user, pid, "OWNS")
            target = pid
        elif d.kind in ("sip", "mandate"):
            sid = "sip:" + _slug(d.title.split(":")[-1])
            if not g.get(sid):
                g.node(sid, "SIP", d.title.split(":")[-1].strip())
                g.edge(user, sid, "OWNS")
            target = sid
        elif d.account_ref:
            target = account(d.account_ref)
        if target:
            g.edge(did, target, "ON")
        g.evidence(did, d.source_ids)

    g.commit()
    return g
