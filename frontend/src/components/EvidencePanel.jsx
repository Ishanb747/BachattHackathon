import React, { useEffect, useRef } from "react";
import { Icon, Badge } from "../atom";
import { fmtDate } from "../lib/format.js";

const KIND = { sms: { icon: "phone", label: "SMS", tone: "accent" }, email: { icon: "mail", label: "Email", tone: "indigo" }, csv: { icon: "calendar", label: "Statement", tone: "ochre" } };

export default function EvidencePanel({ sources, glowIds, focus, citedKey }) {
  const boxRef = useRef(null);

  // Scroll the first glowing row into view inside the panel (not the page).
  useEffect(() => {
    if (!focus || !boxRef.current) return;
    const box = boxRef.current;
    const raf = requestAnimationFrame(() => {
      const el = box.querySelector(".pd-src.pd-glow");
      if (!el) return;
      const top = el.offsetTop - 12;   // .pd-evidence is position:relative
      box.scrollTo({ top, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    });
    return () => cancelAnimationFrame(raf);
  }, [focus]);

  return (
    <div className="pd-evidence" ref={boxRef}>
      {citedKey && (
        <div className="pd-cited pd-row"><span className="pd-pulse-dot" /> Citing <code>{citedKey}</code></div>
      )}
      {sources.map((s) => {
        const k = KIND[s.kind] || { icon: "info", label: s.kind, tone: "outline" };
        const lit = glowIds.has(s.id);
        return (
          <article key={s.id} data-sid={s.id} className={`pd-src${lit ? " pd-glow" : ""}`}>
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
      })}
      {!sources.length && <p className="pd-empty">Source rows appear here as the agent cites them.</p>}
    </div>
  );
}
