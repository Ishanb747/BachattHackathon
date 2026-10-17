// Mock REST backend: same shapes as API.md. Used with ?mock=1, when the
// backend is unreachable, or per route when a route 404s.
import { MOCK_USER, SOURCES, DUES, BALANCES, INSIGHTS, HEALTH, INITIAL_REMINDERS, buildGraph } from "./mockData.js";
import { AuthError } from "./errors.js";

const KEY = "pd_mock_session";
const store = {
  get() { try { return sessionStorage.getItem(KEY) === "1"; } catch { return mem.session; } },
  set(v) { mem.session = v; try { v ? sessionStorage.setItem(KEY, "1") : sessionStorage.removeItem(KEY); } catch {} },
};
const mem = { session: false, reminders: [...INITIAL_REMINDERS], checks: 0 };

const delay = (ms) => new Promise((r) => setTimeout(r, ms));

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
