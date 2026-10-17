// Mock REST backend: same shapes as API.md. Used with ?mock=1, when the
// backend is unreachable, or per route when a route 404s.
import { MOCK_USER, SOURCES, DUES, BALANCES, INSIGHTS, HEALTH, INITIAL_REMINDERS, buildGraph } from "./mockData.js";
import { AuthError } from "./errors.js";

const KEY = "pd_mock_session";
const store = {
  get() { try { return sessionStorage.getItem(KEY) === "1"; } catch { return mem.session; } },
  set(v) { mem.session = v; try { v ? sessionStorage.setItem(KEY, "1") : sessionStorage.removeItem(KEY); } catch {} },
};
const mem = { session: false, reminders: [...INITIAL_REMINDERS], checks: 0, docs: [] };

const delay = (ms) => new Promise((r) => setTimeout(r, ms));

// SAMPLE DATA for ?mock=1 only. A file name containing "locked" asks for a
// password (any password works); "empty" finds nothing.
const docErr = (code, message) => { const e = new Error(message); e.code = code; return e; };
function mockIngest({ name = "sample.pdf", password = "" }) {
  const n = name.toLowerCase();
  if (n.includes("locked") && !password) throw docErr("password_required", "This PDF is password-protected. Enter its password to continue (sample: any password).");
  if (n.includes("empty")) throw docErr("nothing_found", "We read the file but found no accounts or amounts in it.");
  const id = `doc_mock_${Date.now()}`;
  if (n.includes("bank") || n.endsWith(".csv")) {
    return {
      doc: { id, name, doc_type: "bank_statement", pages: 3, at: new Date().toISOString(),
        summary: ["Sample: HDFC savings ••4421, Sep 2026", "Closing balance ₹48,210 after 37 transactions"],
        facts: [
          { label: "Closing balance", value: "₹48,210", source_label: "Page 3 · Closing Balance" },
          { label: "Salary credit", value: "₹92,000", source_label: "Page 1 · NEFT ACME PVT LTD" },
        ] },
      changes: [{ label: "HDFC ••4421 balance", before: "₹31,540", after: "₹48,210" }],
      health_before: 62, health_after: 66,
    };
  }
  return {
    doc: { id, name, doc_type: "cibil_report", pages: 6, at: new Date().toISOString(),
      summary: ["Sample: CIBIL score 742 (as of 30 Sep 2026)", "4 active accounts, 1 card at 78% utilisation", "No missed payments in 24 months"],
      facts: [
        { label: "CIBIL score", value: "742", source_label: "Page 1 · Score summary" },
        { label: "SBI Card limit", value: "₹1,20,000", source_label: "Page 3 · Account 2" },
        { label: "SBI Card balance", value: "₹93,600", source_label: "Page 3 · Current balance" },
        { label: "Home loan outstanding", value: "₹18,42,000", source_label: "Page 4 · Account 3" },
      ] },
    changes: [
      { label: "Credit score", before: null, after: "742" },
      { label: "SBI Card utilisation", before: "54%", after: "78%" },
      { label: "Home loan outstanding", before: "₹18,90,000", after: "₹18,42,000" },
    ],
    health_before: 62, health_after: 71,
  };
}

// SAMPLE forecast / coach / dispute for ?mock=1 only.
const MOCK_EVENTS = {
  1: [{ what: "Netflix", amount: -649, kind: "recurring" }],
  3: [{ what: "SBI Card bill", amount: -18450, kind: "due" }],
  7: [{ what: "Swiggy One", amount: -299, kind: "recurring" }, { what: "Rent", amount: -22000, kind: "recurring" }],
  12: [{ what: "LIC premium", amount: -12500, kind: "due" }],
  15: [{ what: "Salary credit", amount: 92000, kind: "recurring" }],
  20: [{ what: "Home loan EMI", amount: -31200, kind: "due" }],
  26: [{ what: "Airtel postpaid", amount: -799, kind: "recurring" }],
};
export function mockForecast() {
  const start = new Date("2026-10-16T00:00:00");
  let bal = 48210;
  const series = [];
  for (let i = 1; i <= 30; i++) {
    const d = new Date(start); d.setDate(d.getDate() + i);
    const events = (MOCK_EVENTS[i] || []).map((e) => ({ ...e, source_ids: ["sms:bob-0922"] }));
    events.forEach((e) => { bal += e.amount; });
    series.push({ date: d.toISOString().slice(0, 10), balance: bal, events });
  }
  const lowest = series.reduce((a, p) => (p.balance < a.balance ? p : a), series[0]);
  const neg = series.find((p) => p.balance < 0) || null;
  const all = series.flatMap((p) => p.events);
  return {
    start: "2026-10-16", start_balance: 48210, end: series[series.length - 1].date, series,
    lowest: { date: lowest.date, balance: lowest.balance },
    first_negative: neg && { date: neg.date, balance: neg.balance },
    committed_out: all.filter((e) => e.amount < 0).reduce((s, e) => s - e.amount, 0),
    committed_in: all.filter((e) => e.amount > 0).reduce((s, e) => s + e.amount, 0),
    source_ids: ["sms:bob-0922"],
    note: "Sample data. Only recurring charges, recurring credits and dated dues; one-off spending is not guessed.",
  };
}
const MOCK_COACH = {
  score: 742, score_source: "Sample CIBIL report, 30 Sep 2026",
  steps: [
    { lever: "Pay late bills", action: "Clear 1 past-due bill (₹12,500)", why: "Late payments weigh most on the score.", amount: 12500, source_ids: ["sms:bob-0922"] },
    { lever: "Card use under 30%", action: "Pay ₹57,600 on SBI Card to bring it from 78% to 30%", why: "High utilisation reads as credit stress.", amount: 57600, source_ids: ["sms:bob-0922"] },
    { lever: "Fewer credit checks", action: "Pause new loan/card applications: 4 checks in 60 days", why: "Each hard enquiry dents the score for months.", amount: 0, source_ids: [] },
  ],
  note: "Sample. The bureau's formula is not public; these are the standard levers.",
};
const MOCK_DISPUTES = [{
  to: "HDFC Bank", subject: "Refund request: duplicate charge of ₹1,299 by Amazon on 12 Oct 2026",
  body: "Dear HDFC Bank team,\n\nMy card ••4421 was charged twice for the same purchase (sample data):\n  • SMS 12 Oct 10:02: \"Rs 1,299 spent at AMAZON\"\n  • SMS 12 Oct 10:03: \"Rs 1,299 spent at AMAZON\"\n\nPlease reverse the duplicate charge.\n\nThank you.",
  source_ids: ["sms:bob-0922"],
}];

export function addMockReminder(r) {
  if (!mem.reminders.some((x) => x.id === r.id)) mem.reminders = [r, ...mem.reminders];
}

export async function mockHandle(method, path, body) {
  await delay(120 + Math.random() * 180);
  const url = new URL(path, "http://x");
  const p = url.pathname;
  if (p === "/api/login") {
    if (!body || !body.email || !body.password) throw new AuthError("Email and password are required");
    store.set(true);
    return { user: { ...MOCK_USER, email: body.email.includes("@") ? body.email : MOCK_USER.email } };
  }
  if (p === "/api/logout") { store.set(false); return {}; }
  if (!store.get()) throw new AuthError("Not signed in");
  switch (p) {
    case "/api/me": return { user: MOCK_USER };
    case "/api/dashboard":
      return { as_of: "2026-10-16", health: HEALTH, insights: INSIGHTS, dues: DUES, balances: BALANCES, reminders: mem.reminders };
    case "/api/sources": {
      const ids = (url.searchParams.get("ids") || "").split(",").filter(Boolean);
      return { sources: SOURCES.filter((s) => ids.includes(s.id)) };
    }
    case "/api/graph": return buildGraph();
    case "/api/reminders": return { reminders: mem.reminders };
    case "/api/forecast": return mockForecast();
    case "/api/coach": return MOCK_COACH;
    case "/api/disputes": return { disputes: MOCK_DISPUTES };
    case "/api/documents": {
      if (method === "GET") return { documents: mem.docs };
      await delay(2600);   // let the ingestion steps play
      const r = mockIngest(body || {});
      mem.docs = [r.doc, ...mem.docs];
      return r;
    }
    case "/api/check-deadlines": {
      mem.checks += 1;
      const sim = url.searchParams.get("simulate_balance");
      if (sim || mem.checks % 2 === 1) {
        const due = DUES[2];
        return { fire: true, due, balance: { account_ref: BALANCES[0].account_ref, amount: sim ? Number(sim) : BALANCES[0].amount, source_ids: BALANCES[0].source_ids }, simulated: !!sim,
          reason: "Mock: LIC premium is due within 2 days (demo fires regardless of balance)." };
      }
      return { fire: false, reason: "Nothing due within 2 days that your balance can't cover." };
    }
    default: {
      const e = new Error(`mock: no route ${method} ${p}`);
      e.status = 404;
      throw e;
    }
  }
}
