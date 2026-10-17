import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AiOrb, Button, Card, Input, Icon, Badge, Tabs, Navbar, Avatar, Toast, Tooltip, Switch } from "../atom";
import RupeeOrb from "./RupeeOrb";
import CashFlow from "./CashFlow.jsx";
import { get, post, getMode, onMode, uploadDocument } from "../lib/api.js";
import { VoiceClient } from "../lib/voice.js";
import { MockVoice } from "../lib/mockVoice.js";
import { initials, fmtDate } from "../lib/format.js";
import HealthRing from "./HealthRing.jsx";
import { Insights, InsightList, Reminders, Dues, Balances, WhatIf, SectionHead } from "./Panels.jsx";
import EvidencePanel from "./EvidencePanel.jsx";
import GraphView from "./GraphView.jsx";
import IncomingCall from "./IncomingCall.jsx";
import Transcript from "./Transcript.jsx";
import { useFileDrag, DropOverlay, docTypeInfo, isSupported, STEPS, ACCEPT } from "./Documents.jsx";
import Forecast from "./Forecast.jsx";
import ScoreCoach from "./ScoreCoach.jsx";
import DisputeCard, { DisputeModal, WebLookup } from "./DisputeCard.jsx";

const STEP_MS = 1100;     // pace of the ingestion steps while the request runs
const MIN_INGEST_MS = 2200;

const GLOW_MS = 12000;   // a cited row stays lit while the answer is spoken
const ORB_STATE = { idle: "idle", listening: "listening", transcribing: "thinking", thinking: "thinking", speaking: "thinking" };
const STATUS_TEXT = { idle: "Ready", listening: "Listening", transcribing: "Transcribing", thinking: "Thinking", speaking: "Speaking" };

let uid = 0;
const nextId = () => `m${++uid}`;

function collectIds(dash) {
  const ids = new Set();
  const add = (arr) => (arr || []).forEach((x) => (x.source_ids || []).forEach((s) => ids.add(s)));
  if (!dash) return [];
  add(dash.dues); add(dash.balances); add(dash.insights); add(dash.reminders);
  add(dash.health && dash.health.parts);
  return [...ids];
}

export default function Dashboard({ user, onLogout }) {
  const [mode, setMode] = useState(getMode());
  useEffect(() => onMode(setMode), []);

  const [dash, setDash] = useState(null);
  const [insights, setInsights] = useState(null);
  const [reminders, setReminders] = useState(null);
  const [fresh, setFresh] = useState(new Set());
  const [sources, setSources] = useState(() => new Map());
  const [glow, setGlow] = useState({ ids: new Set(), seq: 0, key: null });
  const [graph, setGraph] = useState(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [tab, setTab] = useState("evidence");
  const [whatif, setWhatif] = useState(null);
  // forecast, coach, dispute, web lookup
  const [forecast, setForecast] = useState(null);
  const [coach, setCoach] = useState(null);
  const [disputes, setDisputes] = useState(null);
  const [disputeDraft, setDisputeDraft] = useState(null);
  const [web, setWeb] = useState(null);
  const pageRef = useRef("overview");
  const loadExtras = useCallback(() => {
    get("/api/forecast").then((r) => r && setForecast(r)).catch(() => {});
    get("/api/coach").then((r) => r && setCoach(r)).catch(() => {});
    get("/api/disputes").then((r) => r && setDisputes(r.disputes || [])).catch(() => {});
  }, []);
  useEffect(() => { loadExtras(); }, [loadExtras]);

  const [status, setStatus] = useState("idle");
  const [inCall, setInCall] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [items, setItems] = useState([]);
  const [text, setText] = useState("");
  const [incoming, setIncoming] = useState(null);
  const [checking, setChecking] = useState(false);
  const [simLow, setSimLow] = useState(false);
  const [toasts, setToasts] = useState([]);

  const clientRef = useRef(null);
  const agentOpenRef = useRef(null);
  const glowTimer = useRef(0);
  const sourcesRef = useRef(sources); sourcesRef.current = sources;

  const toast = useCallback((msg, tone = "info") => {
    const id = nextId();
    setToasts((t) => [...t, { id, msg, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200);
  }, []);

  const handleAuth = useCallback((err) => {
    if (err && err.name === "AuthError") { onLogout(true); return true; }
    return false;
  }, [onLogout]);

  // ── sources ──
  const ensureSources = useCallback(async (ids) => {
    const missing = ids.filter((id) => !sourcesRef.current.has(id));
    if (!missing.length) return;
    try {
      const r = await get(`/api/sources?ids=${encodeURIComponent(missing.join(","))}`);
      setSources((prev) => {
        const m = new Map(prev);
        (r.sources || []).forEach((s) => m.set(s.id, s));
        return m;
      });
    } catch (err) { if (!handleAuth(err)) console.warn(err); }
  }, [handleAuth]);

  const highlight = useCallback((ids, key = null, { switchTab = false } = {}) => {
    if (!ids || !ids.length) return;
    ensureSources(ids);
    setGlow((g) => ({ ids: new Set(ids), seq: g.seq + 1, key }));
    if (switchTab) setTab("evidence");
    clearTimeout(glowTimer.current);
    glowTimer.current = setTimeout(() => setGlow((g) => ({ ids: new Set(), seq: g.seq, key: null })), GLOW_MS);
  }, [ensureSources]);

  const showSources = useCallback((ids) => highlight(ids, null, { switchTab: true }), [highlight]);

  // ── initial load ──
  const load = useCallback(async () => {
    try {
      const d = await get("/api/dashboard");
      setDash(d);
      setInsights(d.insights || []);
      setReminders(d.reminders || []);
      ensureSources(collectIds(d));
    } catch (err) { if (!handleAuth(err)) toast(`Could not load dashboard: ${err.message}`, "error"); }
    setGraphLoading(true);
    try { setGraph(await get("/api/graph")); }
    catch (err) { if (!handleAuth(err)) console.warn(err); }
    finally { setGraphLoading(false); }
  }, [ensureSources, handleAuth, toast]);

  useEffect(() => { load(); }, [load]);

  // ── documents ──
  const [allInsights, setAllInsights] = useState(null);
  const uploadedDocs = useRef(new Set());   // doc ids read via this tab's upload (skip the duplicate WS toast)
  const reloadAll = useCallback(() => {
    load();
    get("/api/insights").then((r) => r && setAllInsights(r.insights)).catch(() => {});
    loadExtras();
  }, [load, loadExtras]);

  // ── call events ──
  const pushNote = (t, error = false) => setItems((xs) => [...xs, { id: nextId(), role: "note", text: t, error }]);

  const onEvent = useCallback((msg) => {
    switch (msg.type) {
      case "connected": break;
      case "transcript":
        if (msg.role === "user") {
          agentOpenRef.current = null;
          setItems((xs) => [...xs, { id: nextId(), role: "user", text: msg.text }]);
        } else {
          const open = agentOpenRef.current;
          if (open) setItems((xs) => xs.map((m) => (m.id === open ? { ...m, text: `${m.text} ${msg.text}` } : m)));
          else {
            const id = nextId();
            agentOpenRef.current = id;
            setItems((xs) => [...xs, { id, role: "agent", text: msg.text }]);
          }
        }
        break;
      case "turn_complete": agentOpenRef.current = null; break;
      case "evidence": highlight(msg.source_ids || [], msg.text_key || null); break;
      case "insights": if (Array.isArray(msg.insights)) { setInsights(msg.insights); ensureSources(msg.insights.flatMap((i) => i.source_ids || [])); } break;
      case "reminder": {
        const r = msg.reminder;
        if (!r) break;
        setReminders((rs) => [r, ...(rs || []).filter((x) => x.id !== r.id)]);
        setFresh((f) => new Set(f).add(r.id));
        setTimeout(() => setFresh((f) => { const n = new Set(f); n.delete(r.id); return n; }), 8000);
        toast(`Reminder set: ${r.title}`, "success");
        break;
      }
      case "whatif": setWhatif(msg.result || null); if (msg.result && msg.result.source_ids) ensureSources(msg.result.source_ids); break;
      case "control": if (msg.action === "hangup") pushNote("Credit Dost ended the call"); break;
      case "error": pushNote(msg.message || "Error", true); break;
      case "_note": pushNote(msg.text); break;
      case "doc_ingested": {
        const d = msg.doc || {};
        if (!(d.id && uploadedDocs.current.has(d.id))) toast(`Credit Dost read your ${docTypeInfo(d.doc_type).short}`, "success");
        agentOpenRef.current = null;   // the spoken summary starts a fresh bubble
        reloadAll();
        break;
      }
      case "forecast":
        if (msg.forecast) {
          setForecast(msg.forecast);
          if (pageRef.current !== "talk") toast(msg.forecast.first_negative ? "Forecast updated: balance dips below ₹0" : "Forecast updated", "info");
        } else get("/api/forecast").then((r) => r && setForecast(r)).catch(() => {});
        break;
      case "dispute":
        if (msg.draft) {
          setDisputeDraft(msg.draft);
          setDisputes((ds) => [msg.draft, ...(ds || []).filter((x) => x.subject !== msg.draft.subject)]);
        }
        break;
      case "web": setWeb({ query: msg.query, answer: msg.answer, sources: msg.sources || [], at: Date.now() }); break;
      default: break;
    }
  }, [highlight, ensureSources, toast, reloadAll]);

  const startCall = useCallback(async (path = "/ws") => {
    if (clientRef.current) return;
    const Client = getMode().mockWs ? MockVoice : VoiceClient;
    const client = new Client({
      onEvent,
      onStatus: setStatus,
      onEnd: () => {
        clientRef.current = null; agentOpenRef.current = null;
        setInCall(false); setStatus("idle");
        pushNote("Call ended");
        get("/api/reminders").then((r) => r && r.reminders && setReminders(r.reminders)).catch(() => {});
      },
    });
    clientRef.current = client;
    setConnecting(true);
    pushNote(path.includes("outgoing") ? "Credit Dost is calling you" : "Call started");
    try {
      await client.start(path);
      if (clientRef.current === client) setInCall(true);
    } catch (err) {
      clientRef.current = null;
      toast(err && err.name === "NotAllowedError" ? "Microphone permission denied" : `Could not start call: ${err.message || err}`, "error");
    } finally { setConnecting(false); }
  }, [onEvent, toast]);

  const hangup = () => { clientRef.current && clientRef.current.hangup("user"); };
  const interrupt = () => { clientRef.current && clientRef.current.interrupt(); };
  useEffect(() => () => { clientRef.current && clientRef.current.hangup("unmount"); }, []);

  const send = (e) => {
    e.preventDefault();
    const t = text.trim();
    if (!t || !clientRef.current) return;
    if (clientRef.current.sendText(t)) setText("");
  };

  // ── deadlines ──
  const checkDeadlines = async (forceSim = false) => {
    setChecking(true);
    try {
      const sim = forceSim === true || simLow;
      if (forceSim === true) setSimLow(true);
      const r = await post(sim ? "/api/check-deadlines?simulate_balance=100" : "/api/check-deadlines");
      if (r.fire) {
        const bal = r.balance ? { ...r.balance } : null;
        if (bal && !bal.source_label && dash) {
          const m = (dash.balances || []).find((b) => b.account_ref === bal.account_ref);
          if (m) bal.source_label = m.source_label;
        }
        setIncoming({ ...r, balance: bal });
        if (r.due && r.due.source_ids) highlight([...(r.due.source_ids || []), ...((bal && bal.source_ids) || [])], "deadline");
      } else toast(r.reason || "Nothing urgent right now.", "info");
    } catch (err) { if (!handleAuth(err)) toast(`Check failed: ${err.message}`, "error"); }
    finally { setChecking(false); }
  };
  // Demo trigger: make Credit Dost "call" now or in a few seconds (simulated low balance, same rule).
  const [ringIn, setRingIn] = useState(0);
  const ring = (delay = 0) => {
    if (inCall) { toast("Hang up first, then Credit Dost can call you.", "info"); return; }
    if (!delay) { checkDeadlines(true); return; }
    setRingIn(delay);
  };
  useEffect(() => {
    if (!ringIn) return;
    const t = setTimeout(() => { if (ringIn <= 1) { setRingIn(0); checkDeadlines(true); } else setRingIn(ringIn - 1); }, 1000);
    return () => clearTimeout(t);
  }, [ringIn]);
  useEffect(() => {
    const onKey = (e) => {
      if (e.shiftKey && (e.key === "R" || e.key === "r") && !/input|textarea|select/i.test(e.target.tagName)) { e.preventDefault(); ring(0); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const acceptCall = () => {
    const due = incoming && incoming.due;
    setIncoming(null);
    if (clientRef.current) clientRef.current.hangup("switch");
    const sim = incoming && incoming.simulated ? "&simulate_balance=100" : simLow ? "&simulate_balance=100" : "";
    startCall(`/ws?mode=outgoing${due ? `&due_id=${encodeURIComponent(due.id)}` : ""}${sim}`);
  };

  useEffect(() => { get("/api/insights").then((r) => r && setAllInsights(r.insights)).catch(() => {}); }, []);
  const [personas, setPersonas] = useState([]);
  useEffect(() => { get("/api/demo-users").then((r) => setPersonas((r && r.users) || [])).catch(() => {}); }, []);
  const switchUser = async (id) => {
    if (id === user.id) return;
    hangup();
    try { await post("/api/switch-user", { user_id: id }); window.location.reload(); }
    catch (err) { toast(`Could not switch: ${err.message}`, "error"); }
  };

  const logout = async () => {
    hangup();
    try { await post("/api/logout"); } catch {}
    onLogout();
  };

  const sourceList = useMemo(() => [...sources.values()].sort((a, b) => String(b.at).localeCompare(String(a.at))), [sources]);
  const busy = status === "thinking" || status === "transcribing" || status === "speaking";

  // What the call is about right now: the cited sources, their facts and what those touch.
  const [focusGraph, setFocusGraph] = useState(null);
  useEffect(() => {
    if (!glow.ids.size) { setFocusGraph(null); return; }
    get(`/api/graph?focus=${encodeURIComponent([...glow.ids].join(","))}`).then(setFocusGraph).catch(() => {});
  }, [glow.seq, glow.ids.size]);

  const [dark, setDark] = useState(() => document.documentElement.dataset.theme === "dark");
  const setTheme = (t) => {
    document.documentElement.dataset.theme = t;
    setDark(t === "dark");
    try { localStorage.setItem("cd-theme", t); } catch {}
  };

  const [page, setPage] = useState("overview");
  pageRef.current = page;
  const go = (p) => { setPage(p); const m = document.querySelector(".pd-main"); if (m) m.scrollTo({ top: 0 }); window.scrollTo({ top: 0 }); };
  const showEvidence = (ids) => { highlight(ids, null, { switchTab: true }); if (page !== "talk") go("evidence"); };
  // ── document ingestion (in the chat) ──
  const fileInput = useRef(null);
  const patchItem = (id, f) => setItems((xs) => xs.map((m) => (m.id === id ? { ...m, ...f(m) } : m)));
  const ingest = useCallback(async (file, password = "", retryId = null) => {
    if (!file) return;
    if (page !== "talk") go("talk");
    agentOpenRef.current = null;
    let id = retryId;
    if (!id) {
      id = nextId();
      setItems((xs) => [...xs,
        { id: nextId(), role: "doc-user", name: file.name, size: file.size },
        { id, role: "doc", file, phase: "running", step: 0 }]);
    } else patchItem(id, () => ({ phase: "running", step: 0, error: null }));
    if (!isSupported(file)) {
      patchItem(id, () => ({ phase: "error", error: { code: "unsupported", message: "I read PDF, TXT and CSV files. Try a CIBIL / Experian report or a statement export." } }));
      return;
    }
    const timer = setInterval(() => {
      patchItem(id, (m) => (m.phase === "running" && m.step < STEPS.length - 1 ? { step: m.step + 1 } : {}));
    }, STEP_MS);
    const started = Date.now();
    try {
      const result = await uploadDocument(file, password);
      const wait = MIN_INGEST_MS - (Date.now() - started);
      if (wait > 0) await new Promise((r) => setTimeout(r, wait));
      clearInterval(timer);
      patchItem(id, () => ({ step: STEPS.length }));          // tick the last step
      await new Promise((r) => setTimeout(r, 450));
      if (result && result.doc && result.doc.id) uploadedDocs.current.add(result.doc.id);
      patchItem(id, () => ({ phase: "done", result }));
      reloadAll();
    } catch (err) {
      clearInterval(timer);
      if (handleAuth(err)) return;
      patchItem(id, () => ({ phase: "error", error: { code: err.code || "failed", message: err.message } }));
    }
  }, [handleAuth, reloadAll, page]);
  const dragging = useFileDrag((f) => ingest(f));
  const pickFile = (e) => { const f = e.target.files && e.target.files[0]; if (f) ingest(f); e.target.value = ""; };

  const firstName = (user.name || "").split(" ")[0];
  const overdue = ((dash && dash.dues) || []).filter((d) => d.status === "overdue").length;

  const NAV = [
    { id: "overview", label: "Overview", icon: "sparkles" },
    { id: "talk", label: "Talk", icon: "mic", badge: inCall ? STATUS_TEXT[status] : null },
    { id: "dues", label: "Dues & reminders", icon: "calendar", badge: overdue ? String(overdue) : null, tone: "madder" },
    { id: "insights", label: "Insights", icon: "bolt" },
    { id: "evidence", label: "Evidence", icon: "eye", dot: glow.ids.size > 0 && page !== "evidence" && page !== "talk" },
  ];
  const TITLES = {
    overview: [`Namaste, ${firstName}`, dash ? `Your money at a glance · data as of ${fmtDate(dash.as_of)}` : "Loading your money…"],
    talk: ["Talk to Credit Dost", "Ask in Hindi, Hinglish or English. Every number comes with its source."],
    dues: ["Dues & reminders", "What's due, what's late, and reminders you set by voice."],
    insights: ["Insights", "Ranked by rupee impact, each backed by your own messages."],
    evidence: ["Evidence & graph", "The SMS, emails and records behind every number."],
  };

  const callCard = (
    <Card className="pd-callcard">
      <div className="pd-orb-wrap">
        <RupeeOrb state={ORB_STATE[status] || "idle"} size={150} />
        <div className={`pd-status pd-status--${status}`}>
          <span className="pd-status__dot" />{connecting && !inCall ? "Connecting" : inCall ? STATUS_TEXT[status] || status : "Not in a call"}
        </div>
      </div>
      <div className="pd-call-actions">
        {!inCall ? (
          <Button variant="primary" size="lg" className="pd-wide" onClick={() => startCall("/ws")} disabled={connecting} busy={connecting}>
            <Icon name="phone" size={18} /> {connecting ? "Connecting…" : "Start call"}
          </Button>
        ) : (
          <>
            <Button variant="danger" size="lg" className="pd-wide" onClick={hangup}><Icon name="x" size={18} /> Hang up</Button>
            <Button variant="ghost" className="pd-wide" onClick={interrupt} disabled={status !== "speaking"}>Stop talking</Button>
          </>
        )}
      </div>
      <div className="pd-hints">
        <span className="at-label">Try saying</span>
        {["Balance kitna hai?", "Agar 20 hazaar prepay karun?", "Mera CIBIL kaisa hai?", "Reminder laga do"].map((h) => (
          <span key={h} className="pd-hint">“{h}”</span>
        ))}
      </div>
    </Card>
  );

  const transcriptCard = (
    <Card className="pd-transcript-card">
      {dragging && <DropOverlay inCard />}
      <SectionHead icon="mic" title="Live transcript" right={busy ? <Badge tone="accent" dot>{STATUS_TEXT[status]}</Badge> : null} />
      <Transcript items={items} status={status} onDocRetry={(m, pw) => ingest(m.file, pw, m.id)} onDocSee={() => { reloadAll(); go("overview"); }} />
      <form className="pd-send" onSubmit={send}>
        <Input value={text} onChange={(e) => setText(e.target.value)} disabled={!inCall}
          placeholder={inCall ? "Type instead of speaking…" : "Start a call to type a message"} aria-label="Message" />
        <input ref={fileInput} type="file" accept={ACCEPT} hidden onChange={pickFile} />
        <Tooltip label="Attach a credit report or statement">
          <Button type="button" variant="ghost" className="pd-attach" onClick={() => fileInput.current && fileInput.current.click()} aria-label="Attach document"><Icon name="mail" size={16} /></Button>
        </Tooltip>
        <Button type="submit" variant="accent" disabled={!inCall || !text.trim()} aria-label="Send"><Icon name="send" size={16} /></Button>
      </form>
    </Card>
  );

  const proofCard = (compact) => (
    <Card className={`pd-proof${compact ? " pd-proof--compact" : ""}`}>
      <div className="pd-row pd-row--between pd-proof__head">
        <Tabs value={tab} onChange={setTab} items={[
          { id: "evidence", label: <span className="pd-row">Evidence{glow.ids.size > 0 && tab !== "evidence" && <span className="pd-pulse-dot" />}</span> },
          { id: "graph", label: <span className="pd-row">Graph{glow.ids.size > 0 && tab !== "graph" && <span className="pd-pulse-dot" />}</span> },
        ]} />
        <span className="pd-dim pd-xs">{tab === "evidence" ? `${sourceList.length} source rows` : graph ? `${graph.nodes.length} nodes · ${graph.links.length} edges` : ""}</span>
      </div>
      {tab === "evidence"
        ? <EvidencePanel sources={sourceList} glowIds={glow.ids} focus={glow.seq} citedKey={glow.key} />
        : <GraphView graph={focusGraph && glow.ids.size ? focusGraph : graph} glowIds={glow.ids} loading={graphLoading} />}
    </Card>
  );

  const deadlineCard = (
    <Card className="pd-deadline">
      <div className="pd-deadline__text">
        <div className="pd-deadline__title"><Icon name="alert-triangle" size={18} /> Deadline check</div>
        <p className="pd-dim pd-sm">Credit Dost calls you when a bill is due within 2 days and your balance is lower than the amount.</p>
        <label className="pd-sim">
          <Switch checked={simLow} onChange={(e) => setSimLow(e.target.checked)} aria-label="Simulate low balance" />
          <span className="pd-sm">Simulate low balance <span className="pd-dim pd-xs">(₹100, demo)</span></span>
        </label>
      </div>
      <Button variant="primary" size="lg" onClick={() => checkDeadlines()} disabled={checking || inCall}>
        <Icon name="phone" size={16} /> {checking ? "Checking…" : "Check deadlines"}
      </Button>
    </Card>
  );

  return (
    <div className="pd-layout">
      <aside className="pd-side at-sidebar">
        <div className="pd-side__brand"><span className="pd-brand__dot" />Credit Dost</div>
        {(mode.mockRest || mode.partial) && <Badge tone="ochre" dot className="pd-mode">{mode.mockWs ? "Mock mode" : "Mock data"}</Badge>}
        <nav className="pd-side__nav">
          {NAV.map((n) => (
            <button key={n.id} type="button" onClick={() => go(n.id)}
              className={`at-sidebar__item pd-side__item${page === n.id ? " at-sidebar__item--active" : ""}`}>
              <Icon name={n.icon} size={17} /><span className="pd-grow">{n.label}</span>
              {n.badge && <Badge tone={n.tone || "accent"} dot={n.id === "talk"}>{n.badge}</Badge>}
              {n.dot && <span className="pd-pulse-dot" />}
            </button>
          ))}
        </nav>
        <div className="pd-demo">
          <div className="at-label">Demo · Credit Dost calls you</div>
          <div className="pd-demo__row">
            <Button variant="accent" size="sm" onClick={() => ring(0)} disabled={inCall || checking}><Icon name="phone" size={14} /> Ring me now</Button>
            <Button variant="ghost" size="sm" onClick={() => (ringIn ? setRingIn(0) : ring(10))} disabled={inCall}>
              {ringIn ? `Cancel (${ringIn}s)` : "Ring in 10s"}
            </Button>
          </div>
          <span className="pd-dim pd-xs">Shift + R · uses a simulated low balance</span>
        </div>
        {inCall && page !== "talk" && (
          <button type="button" className="pd-side__live" onClick={() => go("talk")}>
            <span className="pd-status__dot" /> In call · {STATUS_TEXT[status]}
          </button>
        )}
        <div className="pd-side__foot">
          <label className="pd-theme">
            <span>Dark mode</span>
            <Switch checked={dark} onChange={(e) => setTheme(e.target.checked ? "dark" : "light")} aria-label="Dark mode" />
          </label>
          <div className="at-label">Demo user</div>
          {personas.length > 0 ? (
            <select className="pd-persona" value={user.id} onChange={(e) => switchUser(e.target.value)} aria-label="Switch demo user">
              {personas.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.tag}</option>)}
            </select>
          ) : <div className="pd-user__name">{user.name}</div>}
          <div className="pd-row pd-row--between">
            <span className="pd-user"><Avatar size="sm">{initials(user.name)}</Avatar><span className="pd-sm">{user.name}</span></span>
            <Button variant="ghost" size="sm" onClick={logout}>Log out</Button>
          </div>
        </div>
      </aside>

      <main className="pd-main" key={page}>
        <header className="pd-page-head pd-reveal" style={{ "--i": 0 }}>
          <div>
            <h1 className="pd-h1">{TITLES[page][0]}</h1>
            <p className="pd-dim">{TITLES[page][1]}</p>
          </div>
          {page === "overview" && !inCall && (
            <Button variant="primary" onClick={() => { go("talk"); startCall("/ws"); }}><Icon name="phone" size={16} /> Talk now</Button>
          )}
        </header>

        {page === "overview" && (
          <div className="pd-page">
            <div className="pd-row-2-1 pd-reveal" style={{ "--i": 1 }}>
              <section><SectionHead icon="bolt" title="Money health" right={<span className="pd-dim pd-xs">out of 100</span>} />
                <HealthRing health={dash && dash.health} glowIds={glow.ids} onPartClick={showEvidence} /></section>
              <Balances balances={dash && dash.balances} glow={glow.ids} onShow={showEvidence} />
            </div>
            <div className="pd-reveal" style={{ "--i": 2 }}><CashFlow onShow={showEvidence} reloadKey={dash} /></div>
            <div className="pd-reveal" style={{ "--i": 2 }}><Forecast data={forecast} onShow={showEvidence} /></div>
            <div className="pd-reveal" style={{ "--i": 2 }}><Insights insights={insights} glow={glow.ids} onShow={showEvidence} /></div>
            <div className="pd-reveal" style={{ "--i": 3 }}>
              <Dues dues={dash && (dash.dues || []).slice(0, 4)} asOf={dash && dash.as_of} glow={glow.ids} onShow={showEvidence} />
            </div>
          </div>
        )}

        {page === "talk" && (
          <div className="pd-talk">
            <div className="pd-stack pd-reveal" style={{ "--i": 1 }}>{callCard}</div>
            <div className="pd-reveal" style={{ "--i": 2 }}>{transcriptCard}</div>
            <div className="pd-stack pd-reveal" style={{ "--i": 3 }}>
              {focusGraph && glow.ids.size > 0 && (
                <Card className="pd-topic">
                  <SectionHead icon="sparkles" title="Talking about" />
                  <ul className="pd-topic__list">
                    {focusGraph.nodes
                      .filter((n) => ["Due", "Card", "Account", "Policy", "SIP", "Merchant", "Txn"].includes(n.type))
                      .sort((a, b) => ["Due", "Card", "Account", "Policy", "SIP", "Txn", "Merchant"].indexOf(a.type) - ["Due", "Card", "Account", "Policy", "SIP", "Txn", "Merchant"].indexOf(b.type))
                      .slice(0, 4)
                      .map((n) => {
                        const p = n.props || {};
                        const amt = p.amount ?? p.balance ?? p.outstanding;
                        const status = p.status || (p.balance != null ? "balance" : p.available != null ? `₹${Math.round(p.available).toLocaleString("en-IN")} free` : "");
                        return (
                          <li key={n.id} className={`pd-topic__item pd-topic__item--${n.type.toLowerCase()}`}>
                            <span className="pd-topic__type">{n.type === "Txn" ? "Payment" : n.type}</span>
                            <span className="pd-topic__label">{n.type === "Due" ? (p.title || n.label) : n.type === "Txn" ? p.merchant || n.label : n.label}</span>
                            <span className="pd-topic__amt">{amt != null ? `₹${Math.round(amt).toLocaleString("en-IN")}` : ""}</span>
                            {status && <span className={`pd-topic__status pd-topic__status--${status}`}>{status}</span>}
                          </li>
                        );
                      })}
                  </ul>
                </Card>
              )}
              {whatif && <WhatIf result={whatif} onShow={showEvidence} onClose={() => setWhatif(null)} />}
              {web && <WebLookup key={web.at} data={web} onClose={() => setWeb(null)} />}
              {proofCard(true)}
            </div>
          </div>
        )}

        {page === "dues" && (
          <div className="pd-page">
            <div className="pd-reveal" style={{ "--i": 1 }}>{deadlineCard}</div>
            <div className="pd-two pd-reveal" style={{ "--i": 2 }}>
              <Dues dues={dash && dash.dues} asOf={dash && dash.as_of} glow={glow.ids} onShow={showEvidence} />
              <Reminders reminders={reminders} glow={glow.ids} onShow={showEvidence} freshIds={fresh} />
            </div>
          </div>
        )}

        {page === "insights" && (
          <div className="pd-page">
            <div className="pd-reveal" style={{ "--i": 1 }}><ScoreCoach data={coach} onShow={showEvidence} /></div>
            {disputes && disputes.length > 0 && <div className="pd-reveal" style={{ "--i": 1 }}><DisputeCard disputes={disputes} onShow={showEvidence} /></div>}
            {whatif && <div className="pd-reveal" style={{ "--i": 1 }}><WhatIf result={whatif} onShow={showEvidence} onClose={() => setWhatif(null)} /></div>}
            <div className="pd-reveal" style={{ "--i": 1 }}><Insights insights={allInsights || insights} glow={glow.ids} onShow={showEvidence} limit={12} /></div>
          </div>
        )}

        {page === "evidence" && <div className="pd-page pd-reveal" style={{ "--i": 1 }}>{proofCard(false)}</div>}
      </main>

      {dragging && page !== "talk" && <DropOverlay />}

      <DisputeModal draft={disputeDraft} onClose={() => setDisputeDraft(null)} onShow={showEvidence} />

      <IncomingCall data={incoming} onAccept={() => { go("talk"); acceptCall(); }} onDecline={() => { setIncoming(null); toast("Call declined", "info"); }} />

      <div className="pd-toasts">
        {toasts.map((t) => <Toast key={t.id} tone={t.tone}>{t.msg}</Toast>)}
      </div>
    </div>
  );
}
