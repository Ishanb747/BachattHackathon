import React from "react";
import { Card, Badge, Icon } from "../atom";
import { SectionHead } from "./Panels.jsx";
import { inr } from "../lib/format.js";

export default function ScoreCoach({ data, onShow }) {
  const steps = (data && data.steps) || [];
  return (
    <section>
      <SectionHead icon="shield" title="Improve your credit score" right={<span className="pd-dim pd-xs">from your own numbers</span>} />
      <Card className="pd-coach">
        {data && data.score != null && (
          <div className="pd-coach__score">
            <span className="pd-coach__big">{data.score}</span>
            <span className="pd-dim pd-xs">{data.score_source ? `Credit score · ${data.score_source}` : "Credit score"}</span>
          </div>
        )}
        {!data && <div className="pd-coach__skeleton pd-skeleton" />}
        {data && !steps.length && <p className="pd-empty">{data.note || "Nothing to fix right now."}</p>}
        {steps.length > 0 && (
          <ol className="pd-coach__steps">
            {steps.map((s, i) => (
              <li key={i} className="pd-pop" style={{ "--i": i }}>
                <button type="button" className="pd-coach__row" onClick={() => onShow && onShow(s.source_ids || [])}
                  title={s.source_ids && s.source_ids.length ? "Show the messages behind this" : undefined}>
                  <span className="pd-rank">{i + 1}</span>
                  <span className="pd-coach__text">
                    <span className="pd-coach__lever">{s.lever}</span>
                    <b className="pd-coach__action">{s.action}</b>
                    {s.why && <span className="pd-coach__why">{s.why}</span>}
                  </span>
                  {s.amount > 0 && <Badge tone="accent">{inr(Math.round(s.amount))}</Badge>}
                  <Icon name="arrow-right" size={14} />
                </button>
              </li>
            ))}
          </ol>
        )}
        {data && data.note && steps.length > 0 && <p className="pd-dim pd-xs pd-coach__note">{data.note}</p>}
      </Card>
    </section>
  );
}
