// Feed Credit Dost: documents dropped into the chat. Drag detection, the drop
// overlay, and the two chat bubbles (the user's file, the agent's reading).
import React, { useEffect, useRef, useState } from "react";
import { Badge, Button, Icon, Input } from "../atom";

export const ACCEPT = ".pdf,.txt,.csv,application/pdf,text/plain,text/csv";
const OK_EXT = /\.(pdf|txt|csv)$/i;
export const isSupported = (file) => !!file && OK_EXT.test(file.name || "");

const TYPE = {
  cibil_report: { label: "Credit report", short: "credit report", tone: "accent" },
  bank_statement: { label: "Bank statement", short: "bank statement", tone: "indigo" },
  card_statement: { label: "Card statement", short: "card statement", tone: "ochre" },
  other: { label: "Document", short: "document", tone: "outline" },
};
export const docTypeInfo = (t) => TYPE[t] || TYPE.other;

export const STEPS = [
  "Reading document",
  "Extracting accounts & numbers",
  "Verifying every number against the text",
  "Updating your money graph",
];

const show = (v) => (v == null || v === "" ? "—" : typeof v === "number" ? v.toLocaleString("en-IN") : String(v));
const fileKind = (name = "") => { const m = /\.([a-z0-9]+)$/i.exec(name); return m ? m[1].toUpperCase() : "FILE"; };
const fileSize = (n) => (n == null ? "" : n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

export function DocIcon({ size = 56 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5" />
      <path d="M9 13h6M9 17h4" />
    </svg>
  );
}

/** Window-wide file drag tracking. Returns true while a file is dragged over the app. */
export function useFileDrag(onFile, disabled = false) {
  const [over, setOver] = useState(false);
  const depth = useRef(0);
  const cb = useRef(onFile); cb.current = onFile;
  const off = useRef(disabled); off.current = disabled;
  useEffect(() => {
    const hasFiles = (e) => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");
    const enter = (e) => { if (!hasFiles(e) || off.current) return; e.preventDefault(); depth.current += 1; setOver(true); };
    const leave = (e) => { if (!hasFiles(e)) return; depth.current = Math.max(0, depth.current - 1); if (!depth.current) setOver(false); };
    const overH = (e) => { if (!hasFiles(e)) return; e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = off.current ? "none" : "copy"; };
    const drop = (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault(); depth.current = 0; setOver(false);
      const f = e.dataTransfer.files && e.dataTransfer.files[0];
      if (f && !off.current) cb.current(f);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragleave", leave);
    window.addEventListener("dragover", overH);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("dragover", overH);
      window.removeEventListener("drop", drop);
    };
  }, []);
  return over;
}

/** The frosted "Drop to teach Credit Dost" overlay: full screen, or inside the transcript card. */
export function DropOverlay({ inCard = false }) {
  return (
    <div className={`pd-drop${inCard ? " pd-drop--card" : ""}`} aria-hidden="true">
      <div className="pd-drop__frame">
        <span className="pd-drop__icon"><DocIcon size={inCard ? 48 : 64} /></span>
        <div className="pd-drop__title">Drop to teach Credit Dost</div>
        <div className="pd-drop__sub">CIBIL / Experian report, bank or card statement — PDF, TXT, CSV</div>
      </div>
    </div>
  );
}

function useCount(from, to, ms = 1400) {
  const [v, setV] = useState(from ?? 0);
  useEffect(() => {
    if (to == null) return;
    const a = from ?? 0;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) { setV(to); return; }
    setV(a);
    let raf; const start = performance.now() + 600;
    const step = (now) => {
      const k = Math.max(0, Math.min(1, (now - start) / ms));
      setV(a + (to - a) * (1 - Math.pow(1 - k, 3)));
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [from, to, ms]);
  return v;
}

function HealthDelta({ before, after }) {
  const v = useCount(before, after);
  if (after == null) return null;
  const d = Math.round(after - (before ?? after));
  return (
    <div className="pd-ing__health">
      <span className="at-label">Money health</span>
      <div className="pd-ing__score">
        <span className="pd-ing__score-old">{before ?? "—"}</span>
        <Icon name="arrow-right" size={16} />
        <span className="pd-ing__score-new">{Math.round(v)}</span>
        {d !== 0 && <Badge tone={d > 0 ? "accent" : "madder"}>{d > 0 ? `+${d}` : d}</Badge>}
      </div>
    </div>
  );
}

function Steps({ step }) {
  return (
    <ol className="pd-steps">
      {STEPS.map((s, i) => {
        const st = i < step ? "done" : i === step ? "active" : "todo";
        return (
          <li key={s} className={`pd-step pd-step--${st}`}>
            <span className="pd-step__mark">{st === "done" ? <Icon name="check" size={12} /> : st === "active" ? <span className="pd-step__spin" /> : i + 1}</span>
            <span className="pd-step__label">{s}{st === "active" ? "…" : ""}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** User-side bubble: the file they gave. m: {name, size} */
export function DocUserBubble({ m }) {
  return (
    <div className="pd-bubble pd-bubble--user pd-docmsg">
      <span className="pd-bubble__who">You</span>
      <div className="pd-docmsg__file">
        <span className="pd-docmsg__icon"><DocIcon size={20} /></span>
        <span className="pd-grow">
          <span className="pd-docmsg__name">{m.name}</span>
          <span className="pd-docmsg__meta">{[fileKind(m.name), fileSize(m.size)].filter(Boolean).join(" · ")}</span>
        </span>
      </div>
    </div>
  );
}

/**
 * Agent-side bubble that reads the document.
 * m: {phase: "running"|"done"|"error", step, result, error:{code,message}}
 */
export function DocAgentBubble({ m, onRetry, onSee }) {
  const [pw, setPw] = useState("");
  const { phase, step, result, error } = m;
  const needPw = phase === "error" && error && (error.code === "password_required" || error.code === "password_wrong");
  const doc = result && result.doc;
  const info = docTypeInfo(doc && doc.doc_type);
  const submitPw = (e) => { e.preventDefault(); const p = pw.trim(); if (p) { setPw(""); onRetry(p); } };

  return (
    <div className={`pd-bubble pd-bubble--agent pd-docmsg pd-docmsg--${phase}${needPw ? " pd-docmsg--pw" : ""}`}>
      <span className="pd-bubble__who">Credit Dost</span>

      {phase === "running" && (
        <>
          <div className="pd-docmsg__title">Reading your document</div>
          <Steps step={step} />
        </>
      )}

      {needPw && (
        <form className="pd-ing__pw" onSubmit={submitPw}>
          <p className="pd-ing__msg"><Icon name="lock" size={14} />
            <span>{error.message || (error.code === "password_wrong" ? "That password didn't work. Try again." : "This PDF is password-protected.")}</span></p>
          <div className="pd-ing__pw-row">
            <Input type="password" autoFocus value={pw} onChange={(e) => setPw(e.target.value)} error={error.code === "password_wrong"}
              placeholder="PDF password" aria-label="PDF password" autoComplete="off" />
            <Button type="submit" variant="accent" disabled={!pw.trim()}><Icon name="lock" size={14} /> Unlock</Button>
          </div>
          <span className="pd-dim pd-xs">Bank PDFs often use your DOB or account digits. Used once, not stored.</span>
        </form>
      )}

      {phase === "error" && !needPw && (
        <div className="pd-ing__err">
          <Icon name="alert-triangle" size={16} />
          <div>
            <div className="pd-ing__err-title">{error && error.code === "nothing_found" ? "Nothing to learn from this file" : error && error.code === "unreadable" ? "I couldn't read this file" : error && error.code === "unsupported" ? "Not a file I can read" : "Upload failed"}</div>
            <p className="pd-sm">{(error && error.message) || "Something went wrong. Try another file."}</p>
          </div>
        </div>
      )}

      {phase === "done" && doc && (
        <div className="pd-ing__result">
          <div className="pd-row pd-row--between pd-docmsg__head">
            <Badge tone={info.tone} dot>{info.label}</Badge>
            <span className="pd-dim pd-xs pd-row"><Icon name="shield" size={12} />
              {(doc.facts || []).length ? `${doc.facts.length} numbers verified` : "verified against the text"}</span>
          </div>
          {(doc.summary || []).length > 0 && (
            <ul className="pd-ing__summary">{doc.summary.map((s, i) => <li key={i}>{s}</li>)}</ul>
          )}
          {(result.changes || []).length > 0 && (
            <div className="pd-docmsg__sect">
              <span className="at-label pd-row"><Icon name="sparkles" size={12} /> What changed</span>
              <ul className="pd-changes">
                {result.changes.map((c, i) => (
                  <li key={i} className="pd-change" style={{ "--i": i }}>
                    <span className="pd-change__label">{c.label}</span>
                    <span className="pd-change__vals">
                      {c.before == null || c.before === ""
                        ? <span className="pd-change__before pd-change__before--new">new</span>
                        : <span className="pd-change__before">{show(c.before)}</span>}
                      <Icon name="arrow-right" size={13} />
                      <span className="pd-change__after">{show(c.after)}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <HealthDelta before={result.health_before} after={result.health_after} />
          {onSee && (
            <button type="button" className="pd-source-link pd-docmsg__see" onClick={onSee}>
              See it on your dashboard <Icon name="arrow-right" size={13} />
            </button>
          )}
        </div>
      )}
    </div>
  );
}
