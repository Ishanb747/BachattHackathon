"""context.md "DONE WHEN" checks, run on the real dataset (skipped if it is absent)."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from paisadost.config import DATA_DIR

pytestmark = pytest.mark.skipif(not (DATA_DIR / "sms" / "sms.csv").exists(), reason="dataset not present")

LOKESH = "1749913629362473"


@pytest.fixture(scope="module")
def dost():
    from paisadost.tools import Dost
    return Dost.for_user(LOKESH)


def run(coro):
    return asyncio.run(coro)


def test_1_get_insights_ranked_with_sources(dost):
    out = run(dost.get_insights({}))
    insights = [f for f in out["facts"] if f["text_key"].startswith("ins:")]
    assert len(insights) >= 3
    assert all(f["source_ids"] and f["source_label"] for f in insights)


def test_2_balance_with_source_label(dost):
    out = run(dost.answer_question({"q": "Balance kitna hai?"}))
    bal = [f for f in out["facts"] if f["text_key"].startswith("balance:") and f["text_key"] != "balance:total"]
    assert bal and all("SMS" in f["source_label"] and f["source_ids"] for f in bal)


def test_3_barge_in_is_built_in():
    # The interruption path is cascadevoice's; its own tests cover cancel-on-barge-in.
    from cascadevoice import defaults as d
    assert d.BARGE_IN_HARD_MS > 0


def test_4_what_if_prepay_returns_utilisation_and_interest(dost):
    out = run(dost.what_if_prepay({"amount": 20000}))
    keys = {f["text_key"] for f in out["facts"]}
    assert "whatif:saved" in keys and "whatif:util" in keys


def test_5_reminder_needs_confirmation_then_creates_card(dost, tmp_path, monkeypatch):
    monkeypatch.setattr(dost, "reminders_path", tmp_path / "reminders.json")
    events = []

    async def notify(p):
        events.append(p)
    dost.notify = notify
    first = run(dost.set_reminder({"title": "Pay YES card bill", "date": "2026-10-17"}))
    assert first["status"] == "not_set" and not events
    second = run(dost.set_reminder({"title": "Pay YES card bill", "date": "2026-10-17", "confirmed": True}))
    assert second["status"] == "set" and any(e["type"] == "reminder" for e in events)
    dost.notify = None


def test_6_duplicate_across_sms_and_email_merges(dost):
    merged = [t for t in dost.L.txns if {s.split(":")[0] for s in t.source_ids} >= {"sms", "email"}]
    assert merged and all(len(t.source_ids) >= 2 for t in merged)


def test_7_outgoing_call_rule(dost):
    # Real data: nothing both due within 2 days and short of balance → no call.
    assert dost.deadline_check()["fire"] is False
    # Same rule with a balance below the due → the call fires.
    fired = dost.deadline_check(simulate_balance=1)
    assert fired["fire"] is True
    days = (__import__("datetime").date.fromisoformat(fired["due"]["due_date"]) - dost.L.as_of).days
    assert 0 <= days <= 2 and fired["balance"]["amount"] < fired["due"]["amount"]
    # Plenty of money → no call even with a due inside the window.
    assert dost.deadline_check(simulate_balance=10**9)["fire"] is False
