import React, { useEffect, useRef, useState } from "react";
import { Card, Badge, Progress } from "../atom";

function useCountUp(target, ms = 1500) {
  const [v, setV] = useState(0);
  const from = useRef(0);
  useEffect(() => {
    if (target == null) return;
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) { setV(target); from.current = target; return; }
    const start = performance.now(), a = from.current;
    let raf;
    const step = (now) => {
      const k = Math.min(1, (now - start) / ms);
      const e = 1 - Math.pow(1 - k, 3);
      const val = a + (target - a) * e;
      setV(val);
      if (k < 1) raf = requestAnimationFrame(step); else from.current = target;
    };
    const delay = setTimeout(() => (raf = requestAnimationFrame(step)), 350);
    return () => { clearTimeout(delay); cancelAnimationFrame(raf); };
  }, [target, ms]);
  return v;
}

export default function HealthRing({ health, onPartClick, glowIds }) {
  const score = health ? health.score : null;
  const v = useCountUp(score ?? 0);
  const R = 54, C = 2 * Math.PI * R;
  const frac = Math.max(0, Math.min(1, v / 100));
  const tone = (score ?? 0) >= 75 ? "accent" : (score ?? 0) >= 50 ? "ochre" : "madder";

  return (
    <Card smoke blur={22} className="pd-health" data-tilt>
      <div className="pd-health__grid">
        <div className="pd-health__ring" aria-label={`Money health ${score ?? "—"} out of 100`}>
          <svg viewBox="0 0 140 140" width="140" height="140">
            <defs>
              <linearGradient id="pdRingGrad" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stopColor="#00e5a0" />
                <stop offset="1" stopColor="#007a4d" />
              </linearGradient>
              <filter id="pdRingGlow" x="-30%" y="-30%" width="160%" height="160%">
                <feGaussianBlur stdDeviation="3" />
              </filter>
            </defs>
            <circle cx="70" cy="70" r={R} fill="rgba(255,255,255,0.55)" stroke="rgba(30,36,51,0.08)" strokeWidth="12" />
            <circle cx="70" cy="70" r={R} fill="none" stroke="url(#pdRingGrad)" strokeWidth="12" strokeLinecap="round"
              strokeDasharray={C} strokeDashoffset={C * (1 - frac)} transform="rotate(-90 70 70)" opacity="0.45" filter="url(#pdRingGlow)" />
            <circle cx="70" cy="70" r={R} fill="none" stroke="url(#pdRingGrad)" strokeWidth="12" strokeLinecap="round"
              strokeDasharray={C} strokeDashoffset={C * (1 - frac)} transform="rotate(-90 70 70)" />
          </svg>
          <div className="pd-health__value">
            <span className="pd-health__num">{score == null ? "–" : Math.round(v)}</span>
            <span className="pd-health__of">/100</span>
          </div>
        </div>
        <div className="pd-health__side">
          <div className="pd-row pd-row--between">
            <span className="at-label">Money health</span>
            {health && health.grade && <Badge tone={tone}>{health.grade}</Badge>}
          </div>
          <ul className="pd-parts">
            {(health ? health.parts : []).map((p) => {
              const lit = glowIds && p.source_ids && p.source_ids.some((s) => glowIds.has(s));
              return (
                <li key={p.name} className={lit ? "pd-part pd-glow" : "pd-part"} title={p.note || undefined}>
                  <button type="button" className="pd-part__btn" onClick={() => onPartClick && onPartClick(p.source_ids || [])}
                    title="Show sources">
                    <span className="pd-part__name">{p.name}</span>
                    <span className="pd-part__score">{p.score}<span className="pd-dim">/{p.max}</span></span>
                  </button>
                  <Progress value={(p.score / Math.max(1, p.max)) * 100} />
                </li>
              );
            })}
            {!health && <li className="pd-dim">Loading…</li>}
          </ul>
        </div>
      </div>
    </Card>
  );
}
