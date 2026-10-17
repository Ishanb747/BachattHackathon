import React, { useEffect, useState } from "react";
import { Card, Badge } from "../atom";
import { get } from "../lib/api.js";
import { SectionHead } from "./Panels.jsx";

const inr = (x) => `₹${Math.round(x || 0).toLocaleString("en-IN")}`;
const KIND_TONE = { EMI: "madder", Premium: "indigo", SIP: "accent", Repeating: "ochre" };

// Monthly money in (repeat large deposits) vs fixed money out (EMIs, premiums, SIPs, repeating bills).
export default function CashFlow({ onShow, reloadKey }) {
  const [c, setC] = useState(null);
  useEffect(() => { get("/api/cashflow").then(setC).catch(() => {}); }, [reloadKey]);
  if (!c || !c.months) return null;
  const inc = Math.max(c.income, 1);
  const fixedPct = Math.min(100, (c.fixed / inc) * 100);
  const tight = c.fixed_ratio_pct != null && c.fixed_ratio_pct >= 50;
  return (
    <section>
      <SectionHead icon="bolt" title="Monthly money" right={<span className="pd-dim pd-xs">avg over {c.months} months</span>} />
      <Card className="pd-cash">
        <div className="pd-cash__kpis">
          <button type="button" className="pd-cash__kpi" onClick={() => onShow(c.income_items.flatMap((r) => r.source_ids))}>
            <span className="at-label">Income</span><b>{inr(c.income)}</b><span className="pd-dim pd-xs">repeat deposits ₹5k+</span>
          </button>
          <button type="button" className="pd-cash__kpi" onClick={() => onShow(c.fixed_items.flatMap((r) => r.source_ids))}>
            <span className="at-label">Fixed spend</span><b>{inr(c.fixed)}</b>
            <span className={`pd-xs ${tight ? "pd-cash__warn" : "pd-dim"}`}>{c.fixed_ratio_pct}% of income</span>
          </button>
          <div className="pd-cash__kpi pd-cash__kpi--free">
            <span className="at-label">Left each month</span><b className={c.free < 0 ? "pd-cash__neg" : ""}>{inr(c.free)}</b>
            <span className="pd-dim pd-xs">before day-to-day spending</span>
          </div>
        </div>
        <div className="pd-cash__bar" aria-label={`Fixed spend is ${c.fixed_ratio_pct}% of income`}>
          <span className={`pd-cash__fill${tight ? " pd-cash__fill--tight" : ""}`} style={{ width: `${fixedPct}%` }} />
          <span className="pd-cash__mark" style={{ left: "50%" }} title="50% of income" />
        </div>
        <div className="pd-cash__cols">
          <div>
            <div className="at-label pd-cash__sub">Biggest fixed costs</div>
            <ul className="pd-cash__list">
              {c.fixed_items.slice(0, 5).map((r) => (
                <li key={r.what} onClick={() => onShow(r.source_ids)}>
                  <Badge tone={KIND_TONE[r.kind] || "outline"}>{r.kind}</Badge>
                  <span className="pd-grow pd-cash__name">{r.what}</span>
                  <b>{inr(r.per_month)}<span className="pd-dim pd-xs">/mo</span></b>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <div className="at-label pd-cash__sub">Where income comes from</div>
            <ul className="pd-cash__list">
              {c.income_items.slice(0, 3).map((r) => (
                <li key={r.from} onClick={() => onShow(r.source_ids)}>
                  <Badge tone="accent">{r.times}×</Badge>
                  <span className="pd-grow pd-cash__name">{r.from}</span>
                  <b>{inr(r.per_month)}<span className="pd-dim pd-xs">/mo</span></b>
                </li>
              ))}
              {c.one_off_deposits > 0 && (
                <li className="pd-dim" onClick={() => onShow((c.one_off_items || []).flatMap((r) => r.source_ids))}>
                  <Badge tone="outline">one-off</Badge>
                  <span className="pd-grow pd-cash__name">Big single deposits (not counted)</span>
                  <b>{inr(c.one_off_deposits)}</b>
                </li>
              )}
            </ul>
          </div>
        </div>
        <p className="pd-dim pd-xs pd-cash__note">{c.note}</p>
      </Card>
    </section>
  );
}
