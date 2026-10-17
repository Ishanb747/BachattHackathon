// Simulated call for mock mode: emits the same WS events as the real server
// (status, transcript, turn_complete, evidence, insights, reminder, whatif).
// No mic, no audio; type into the text box to talk to it.
import { INSIGHTS, WHATIF } from "./mockData.js";
import { addMockReminder } from "./mock.js";

const SCRIPTS = {
  greeting: [
    { say: "Namaste Lokesh! Main Credit Dost hoon.", ev: null },
    { event: { type: "insights", insights: INSIGHTS } },
    { say: "Sabse zaroori baat: aapka IndusInd card 78% utilised hai, from your IndusInd statement for Sep.",
      ev: { source_ids: ["csv:indus-stmt-0930", "sms:indus-1012"], text_key: "card_utilisation" } },
  ],
  outgoing: [
    { say: "Lokesh ji, Credit Dost bol raha hoon. Aapka LIC premium ₹1,401 18 Oct ko due hai, from your LIC SMS on 30 Sep.",
      ev: { source_ids: ["sms:lic-0930"], text_key: "due_amount" } },
    { say: "Aapke BOB account mein ₹30,375.54 hain, from your BOB SMS on 22 Sep. Kya main reminder laga doon?",
      ev: { source_ids: ["sms:bob-0922"], text_key: "balance" } },
  ],
  balance: [
    { say: "Aapke Bank of Baroda XX1626 mein ₹30,375.54 hain, from your BOB SMS on 22 Sep.",
      ev: { source_ids: ["sms:bob-0922"], text_key: "balance" } },
  ],
  whatif: [
    { say: "Agar aap ₹20,000 IndusInd card par prepay karein, utilisation 78% se 38% ho jayega.",
      ev: { source_ids: ["csv:indus-stmt-0930"], text_key: "whatif" }, event: { type: "whatif", result: WHATIF } },
    { say: "Isse har mahine lagbhag ₹590 interest bachega, from your IndusInd statement for Sep." },
  ],
  confirm: [{ say: "Main 17 Oct ke liye 'Pay YES Bank card bill ₹399.97' ka reminder laga doon? Haan ya na boliye." }],
  reminder: [
    { say: "Ho gaya! Reminder set hai 17 Oct ke liye.", reminder: true },
  ],
  dup: [
    { say: "Swiggy ka ₹642 do baar charge hua hai, 3 aur 4 Oct ko, from your IndusInd statement for Oct.",
      ev: { source_ids: ["sms:swiggy-1003a", "csv:swiggy-1003b", "email:swiggy-1003"], text_key: "duplicate" } },
  ],
  dues: [
    { say: "YES Bank card ka ₹399.97 bill 10 Oct ko due tha, from your YES Bank SMS on 26 Sep.",
      ev: { source_ids: ["sms:yes-0926", "email:yes-0926"], text_key: "due_amount" } },
    { say: "Airtel ka ₹195.88 15 Oct ko, from your Airtel SMS on 1 Oct.", ev: { source_ids: ["sms:airtel-1001"], text_key: "due_amount" } },
  ],
  fallback: [
    { say: "Main aapke balance, bills, card aur kharche ke baare mein bata sakta hoon. Jaise: 'Balance kitna hai?' ya 'Agar 20 hazaar prepay karun?'" },
  ],
};

function pick(text, awaitingConfirm) {
  const t = text.toLowerCase();
  if (awaitingConfirm && /\b(haan|ha|yes|ok|theek|kar do|laga do|sure)\b/.test(t)) return "reminder";
  if (/balance|kitna hai|paisa kitna|bal\b/.test(t)) return "balance";
  if (/prepay|20 ?k|20,?000|hazaar|what if|agar/.test(t)) return "whatif";
  if (/remind|yaad|reminder/.test(t)) return "confirm";
  if (/duplicate|double|twice|do baar|swiggy/.test(t)) return "dup";
  if (/due|bill|emi|deadline/.test(t)) return "dues";
  return "fallback";
}

export class MockVoice {
  constructor({ onEvent, onStatus, onEnd } = {}) {
    this.onEvent = onEvent || (() => {});
    this.onStatus = onStatus || (() => {});
    this.onEnd = onEnd || (() => {});
    this.timers = []; this.active = false; this.awaitingConfirm = false; this.status = "idle";
  }
  setStatus(s) { this.status = s; this.onStatus(s); }
  later(ms, f) { this.timers.push(setTimeout(() => this.active && f(), ms)); }

  async start(path = "/ws") {
    this.active = true;
    this.onEvent({ type: "connected", llm: "mock", vad: "mock" });
    this.setStatus("thinking");
    const outgoing = path.includes("mode=outgoing");
    this.play(outgoing ? "outgoing" : "greeting", 500);
    if (outgoing) this.awaitingConfirm = true;
  }

  play(key, startDelay = 700) {
    let t = startDelay;
    const steps = SCRIPTS[key];
    this.later(t - 300, () => this.setStatus("thinking"));
    steps.forEach((s) => {
      this.later(t, () => {
        if (s.event) this.onEvent(s.event);
        if (s.say) {
          this.setStatus("speaking");
          if (s.ev) this.onEvent({ type: "evidence", ...s.ev });
          this.onEvent({ type: "transcript", role: "agent", text: s.say });
        }
        if (s.reminder) {
          const r = { id: `rem:mock-${Date.now()}`, title: "Pay YES Bank card bill ₹399.97", date: "2026-10-17",
            due_id: "due:yes-xx9269-2610", created_at: new Date().toISOString(), source_ids: ["sms:yes-0926"] };
          addMockReminder(r);
          this.onEvent({ type: "reminder", reminder: r });
          this.onEvent({ type: "evidence", source_ids: r.source_ids, text_key: "reminder" });
        }
      });
      t += s.say ? Math.max(1400, s.say.length * 45) : 200;
    });
    this.later(t, () => { this.onEvent({ type: "turn_complete" }); this.setStatus("listening"); });
    this.awaitingConfirm = key === "confirm" || (key === "outgoing");
  }

  sendText(text) {
    if (!this.active) return false;
    this.clear();
    this.onEvent({ type: "transcript", role: "user", text });
    this.setStatus("thinking");
    const key = pick(text, this.awaitingConfirm);
    this.play(key, 900);
    return true;
  }

  interrupt() { this.clear(); this.onEvent({ type: "control", action: "stop_playback", fade_ms: 90 }); this.setStatus("listening"); }
  clear() { this.timers.forEach(clearTimeout); this.timers = []; }
  hangup(reason = "user") {
    const was = this.active;
    this.active = false; this.clear(); this.setStatus("idle");
    if (was) this.onEnd(reason);
  }
}
