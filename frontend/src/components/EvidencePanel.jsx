import React, { useEffect, useRef } from "react";
import { Icon, Badge } from "../atom";
import { fmtDate } from "../lib/format.js";

const KIND = { sms: { icon: "phone", label: "SMS", tone: "accent" }, email: { icon: "mail", label: "Email", tone: "indigo" }, csv: { icon: "calendar", label: "Statement", tone: "ochre" } };

export default function EvidencePanel({ sources, glowIds, focus, citedKey }) {
  const boxRef = useRef(null);

  // Cited rows are pinned to the top; bring the panel (and its scrolling card) back to them.
  useEffect(() => {
    if (!focus || !boxRef.current) return;
    const box = boxRef.current;
    const raf = requestAnimationFrame(() => {
      box.scrollTo({ top: 0, behavior: "smooth" });
      const card = box.closest(".pd-proof");
      if (card) card.scrollTo({ top: 0, behavior: "smooth" });
    });
    return () => cancelAnimationFrame(raf);
  }, [focus, sources.length]);

  const lit = sources.filter((s) => glowIds.has(s.id));
  const rest = sources.filter((s) => !glowIds.has(s.id));
  const row = (s) => {
    const k = KIND[s.kind] || { icon: "info", label: s.kind, tone: "outline" };
    const on = glowIds.has(s.id);
    return (
      <article key={s.id} data-sid={s.id} className={`pd-src${on ? " pd-glow pd-src--cited" : ""}`}>
        <header className="pd-src__head">
          <span className={`pd-src__icon pd-src__icon--${s.kind}`}><Icon name={k.icon} size={14} /></span>
          <span className="pd-src__sender">{s.sender}</span>
          <Badge tone={k.tone}>{k.label}</Badge>
          <span className="pd-src__date">{fmtDate(s.at, { year: false })}</span>
        </header>
        <p className="pd-src__text">{s.text}</p>
        <footer className="pd-src__foot">
          <span>{s.label}</span>
          <code className="pd-src__id">{s.id}</code>
        </footer>
      </article>
    );
  };

  return (
    <div className="pd-evidence" ref={boxRef}>
      {lit.length > 0 && (
        <div className="pd-cited pd-row"><span className="pd-pulse-dot" /> Cited just now · {lit.length} source{lit.length > 1 ? "s" : ""}</div>
      )}
      {lit.map(row)}
      {lit.length > 0 && rest.length > 0 && <div className="pd-cited pd-cited--rest">All sources</div>}
      {rest.map(row)}
      {!sources.length && <p className="pd-empty">Source rows appear here as the agent cites them.</p>}
    </div>
  );
}
