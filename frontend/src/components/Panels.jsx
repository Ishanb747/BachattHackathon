import React from "react";
import { Card, Badge, Icon, Tooltip } from "../atom";
import { inr, inrShort, fmtDate, daysUntil, pct } from "../lib/format.js";

const hasGlow = (ids, glow) => !!(glow && ids && ids.some((s) => glow.has(s)));

function SourceLink({ ids, label, onShow }) {
  if (!label && !(ids && ids.length)) return null;
  return (
    <button type="button" className="pd-source-link" onClick={() => onShow && onShow(ids || [])}>
      <Icon name="eye" size={13} /> {label || `${ids.length} source${ids.length === 1 ? "" : "s"}`}
    </button>
  );
}

export function SectionHead({ icon, title, right }) {
  return (
    <div className="pd-section-head">
      <span className="at-label pd-row"><Icon name={icon} size={14} /> {title}</span>
      {right}
    </div>
  );
}

export function Insights({ insights, glow, onShow, limit = 3 }) {
  return (
    <section>
      <SectionHead icon="sparkles" title={limit > 3 ? "All insights" : "Top insights"} right={<span className="pd-dim pd-xs">ranked by ₹ impact</span>} />
      <div className="pd-insights">
        {(insights || []).slice(0, limit).map((it, i) => (
          <Card key={it.id} hover data-tilt className={`pd-insight pd-pop${hasGlow(it.source_ids, glow) ? " pd-glow" : ""}`}
            style={{ "--i": i }}>
            <div className="pd-row pd-row--between pd-insight__top">
              <span className="pd-rank">{i + 1}</span>
              <Badge tone="accent" dot>{it.headline ? `${it.headline} ${it.headline_note}` : `${inrShort(it.impact_inr)} impact`}</Badge>
            </div>
            <h3 className="pd-insight__title">{it.title}</h3>
            <p className="pd-insight__detail">{it.detail}</p>
            <SourceLink ids={it.source_ids} label={it.source_label} onShow={onShow} />
          </Card>
        ))}
        {!insights && [0, 1, 2].map((i) => <Card key={i} className="pd-insight pd-skeleton" />)}
        {insights && !insights.length && <p className="pd-dim pd-sm">No insights yet.</p>}
      </div>
    </section>
  );
}

export function Reminders({ reminders, glow, onShow, freshIds }) {
  return (
    <section>
      <SectionHead icon="bell" title="Reminders" right={reminders && reminders.length ? <Badge>{reminders.length}</Badge> : null} />
      <div className="pd-reminders">
        {(reminders || []).map((r) => (
          <Card key={r.id} data-tilt className={`pd-reminder${freshIds && freshIds.has(r.id) ? " pd-reminder--fresh" : ""}${hasGlow(r.source_ids, glow) ? " pd-glow" : ""}`}>
            <div className="pd-reminder__icon"><Icon name="bell" size={18} /></div>
            <div className="pd-grow">
              <div className="pd-reminder__title">{r.title}</div>
              <div className="pd-dim pd-xs pd-row">
                <Icon name="calendar" size={12} /> {fmtDate(r.date)}
                {freshIds && freshIds.has(r.id) && <Badge tone="accent" className="pd-new">set by voice</Badge>}
              </div>
            </div>
            {r.source_ids && r.source_ids.length > 0 && (
              <Tooltip label="Show source">
                <button type="button" className="pd-icon-btn" onClick={() => onShow(r.source_ids)} aria-label="Show source">
                  <Icon name="eye" size={15} />
                </button>
              </Tooltip>
            )}
          </Card>
        ))}
        {reminders && !reminders.length && (
          <p className="pd-empty">Say “Reminder laga do” during a call and it lands here.</p>
        )}
      </div>
    </section>
  );
}

export function Balances({ balances, glow, onShow }) {
  const total = (balances || []).reduce((a, b) => a + (b.amount || 0), 0);
  return (
    <section>
      <SectionHead icon="shield" title="Bank balance" right={balances && balances.length > 1 ? <span className="pd-dim pd-xs">total {inr(total)}</span> : null} />
      <Card className="pd-list-card">
        <ul className="pd-due-list">
          {(balances || []).map((b) => (
            <li key={b.account_ref} className={`pd-due${hasGlow(b.source_ids, glow) ? " pd-glow" : ""}`}>
              <button type="button" className="pd-due__btn" onClick={() => onShow(b.source_ids)}>
                <div className="pd-grow">
                  <div className="pd-due__title">{b.account_ref}</div>
                  <div className="pd-dim pd-xs">{b.source_label}</div>
                </div>
                <div className="pd-due__amt">{inr(b.amount)}</div>
              </button>
            </li>
          ))}
          {balances && !balances.length && <li className="pd-empty">No bank balance in the messages.</li>}
        </ul>
      </Card>
    </section>
  );
}

export function Dues({ dues, asOf, glow, onShow }) {
  return (
    <section>
      <SectionHead icon="calendar" title="Upcoming dues" right={asOf ? <span className="pd-dim pd-xs">as of {fmtDate(asOf)}</span> : null} />
      <Card className="pd-list-card">
        <ul className="pd-due-list">
          {(dues || []).map((d) => {
            const days = daysUntil(d.due_date, asOf);
            const tone = days < 0 ? "madder" : days <= 2 ? "ochre" : "outline";
            const when = days < 0 ? `${-days}d overdue` : days === 0 ? "today" : `in ${days}d`;
            return (
              <li key={d.id} className={`pd-due${hasGlow(d.source_ids, glow) ? " pd-glow" : ""}`}>
                <button type="button" className="pd-due__btn" onClick={() => onShow(d.source_ids)}>
                  <div className="pd-grow">
                    <div className="pd-due__title">{d.title}</div>
                    <div className="pd-dim pd-xs">{[d.account_ref, fmtDate(d.due_date)].filter(Boolean).join(" · ")}</div>
                  </div>
                  <div className="pd-due__right">
                    <div className="pd-due__amt">{inr(d.amount)}</div>
                    <Badge tone={tone}>{when}</Badge>
                  </div>
                </button>
              </li>
            );
          })}
          {dues && !dues.length && <li className="pd-empty">Nothing due.</li>}
        </ul>
      </Card>
    </section>
  );
}

// The whatif result shape is open ({...}); render the fields we know, and any
// other plain values as a key/value list.
const KNOWN = new Set(["amount", "card", "utilisation_before", "utilisation_after", "new_utilisation", "util_before", "util_after",
  "interest_saved_per_month", "interest_saved", "plan", "source_ids", "source_label", "text"]);

export function WhatIf({ result, onShow, onClose }) {
  if (!result) return null;
  const before = result.utilisation_before ?? result.util_before;
  const after = result.utilisation_after ?? result.new_utilisation ?? result.util_after;
  const saved = result.interest_saved_per_month ?? result.interest_saved;
  const toPct = (x) => { const n = Number(x); return n <= 1.0001 ? n * 100 : n; };
  const extras = Object.entries(result).filter(([k, v]) => !KNOWN.has(k) && (typeof v === "number" || typeof v === "string"));
  return (
    <Card className="pd-whatif pd-pop" data-tilt>
      <div className="pd-row pd-row--between">
        <span className="at-label pd-row"><Icon name="bolt" size={14} /> What if</span>
        <button type="button" className="pd-icon-btn" onClick={onClose} aria-label="Dismiss"><Icon name="x" size={14} /></button>
      </div>
      <h3 className="at-card__title">
        {result.amount != null ? `Prepay ${inr(result.amount)}` : "Prepayment plan"}{result.card ? ` on ${result.card}` : ""}
      </h3>
      {before != null && after != null && (
        <div className="pd-util">
          <div className="pd-util__labels"><span>Utilisation</span><span><b>{pct(before)}</b> → <b className="pd-accent">{pct(after)}</b></span></div>
          <div className="pd-util__bar">
            <div className="pd-util__before" style={{ width: `${Math.min(100, toPct(before))}%` }} />
            <div className="pd-util__after" style={{ width: `${Math.min(100, toPct(after))}%` }} />
            <div className="pd-util__mark" style={{ left: "30%" }} title="30% target" />
          </div>
        </div>
      )}
      {saved != null && (
        <div className="pd-whatif__saved"><span className="pd-whatif__big">{inr(saved)}</span><span className="pd-dim"> interest saved / month</span></div>
      )}
      {Array.isArray(result.plan) && result.plan.length > 0 && (
        <ul className="pd-plan">
          {result.plan.map((p, i) => (
            <li key={i}>
              <span>{p.card || p.account_ref || `Card ${i + 1}`}</span>
              <span>{p.pay != null ? inr(p.pay) : ""}{p.util_after != null ? ` → ${pct(p.util_after)}` : ""}</span>
            </li>
          ))}
        </ul>
      )}
      {extras.length > 0 && (
        <ul className="pd-plan">
          {extras.map(([k, v]) => <li key={k}><span>{k.replace(/_/g, " ")}</span><span>{typeof v === "number" ? v.toLocaleString("en-IN") : v}</span></li>)}
        </ul>
      )}
      {result.text && <p className="at-card__body">{result.text}</p>}
      <SourceLink ids={result.source_ids} label={result.source_label} onShow={onShow} />
    </Card>
  );
}

const KIND = {
  due:       { label: "Late bill",       tone: "madder", icon: "alert-triangle", action: "Pay it today" },
  upcoming:  { label: "Due soon",        tone: "ochre",  icon: "calendar",       action: "Keep the money ready" },
  credit:    { label: "Credit health",   tone: "indigo", icon: "shield",         action: "Protect your CIBIL" },
  recurring: { label: "Subscription",    tone: "ochre",  icon: "refresh",        action: "Review this plan" },
  duplicate: { label: "Double charge",   tone: "madder", icon: "info",           action: "Ask for a refund" },
  spend:     { label: "Spending",        tone: "ochre",  icon: "bolt",           action: "Check this category" },
};

// Full-page insight list: what it is, how much, why it matters, what to do, and the proof.
export function InsightList({ insights, glow, onShow }) {
  const list = insights || [];
  const groups = Object.keys(KIND).map((k) => ({ k, n: list.filter((i) => i.kind === k).length })).filter((g) => g.n);
  return (
    <section className="pd-ilist">
      {groups.length > 0 && (
        <div className="pd-ilist__summary">
          {groups.map((g) => (
            <span key={g.k} className={`pd-ichip pd-ichip--${KIND[g.k].tone}`}>
              <Icon name={KIND[g.k].icon} size={14} /> {g.n} {KIND[g.k].label.toLowerCase()}{g.n > 1 ? "s" : ""}
            </span>
          ))}
        </div>
      )}
      {list.map((it, i) => {
        const k = KIND[it.kind] || { label: it.kind, tone: "outline", icon: "info", action: "" };
        return (
          <Card key={it.id} className={`pd-irow pd-irow--${k.tone} pd-pop${hasGlow(it.source_ids, glow) ? " pd-glow" : ""}`} style={{ "--i": i }}>
            <div className="pd-irow__rank">{i + 1}</div>
            <div className="pd-irow__body">
              <div className="pd-irow__meta">
                <span className={`pd-ichip pd-ichip--${k.tone}`}><Icon name={k.icon} size={13} /> {k.label}</span>
                <span className="pd-dim pd-xs">{it.detail}</span>
              </div>
              <h3 className="pd-irow__title">{it.title}</h3>
              <p className="pd-irow__say">{it.say}</p>
              <div className="pd-irow__foot">
                {k.action && <span className="pd-irow__action"><Icon name="arrow-right" size={13} /> {k.action}</span>}
                <SourceLink ids={it.source_ids} label={it.source_label} onShow={onShow} />
              </div>
            </div>
            <div className="pd-irow__impact">
              <div className="pd-irow__amt">{it.headline || inr(it.impact_inr)}</div>
              <div className="pd-dim pd-xs">{it.headline_note || "at stake"}</div>
            </div>
          </Card>
        );
      })}
      {insights && !insights.length && <p className="pd-empty">No insights for this user.</p>}
    </section>
  );
}
