import React, { useEffect, useMemo, useRef, useState } from "react";
import { Card, Badge, Icon } from "../atom";
import { SectionHead } from "./Panels.jsx";
import { inr, inrShort, fmtDate } from "../lib/format.js";

const H = 220;
const PAD = { top: 26, right: 16, bottom: 26, left: 52 };

const signed = (n) => `${n >= 0 ? "+" : "−"}${inr(Math.abs(Math.round(n)))}`;
/** ₹ with a leading minus sign for negatives: −₹5,688 */
const money = (n) => `${n < 0 ? "−" : ""}${inr(Math.abs(Math.round(n)))}`;
const moneyShort = (n) => `${n < 0 ? "−" : ""}${inrShort(Math.abs(n))}`;
const shortDate = (d) => fmtDate(d, { year: false });

function useWidth(ref, fallback = 640) {
  const [w, setW] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(260, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return w;
}

/** Round a step to 1/2/5 × 10^n so ticks read as clean rupee amounts. */
function niceStep(span, count) {
  const raw = span / Math.max(1, count);
  const p = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  const m = raw / p;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
}

function Chart({ series, lowest, firstNeg }) {
  const wrap = useRef(null);
  const W = useWidth(wrap);
  const [hover, setHover] = useState(null);

  const g = useMemo(() => {
    const vals = series.map((p) => p.balance);
    const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
    const step = niceStep(hi - lo || 1, 3);
    const yMin = Math.floor(lo / step) * step, yMax = Math.ceil((hi * 1.04) / step) * step || step;
    const iw = W - PAD.left - PAD.right, ih = H - PAD.top - PAD.bottom;
    const x = (i) => PAD.left + (series.length < 2 ? iw / 2 : (i / (series.length - 1)) * iw);
    const y = (v) => PAD.top + (1 - (v - yMin) / (yMax - yMin || 1)) * ih;
    const pts = series.map((p, i) => [x(i), y(p.balance)]);
    const line = pts.map(([a, b], i) => `${i ? "L" : "M"}${a.toFixed(1)},${b.toFixed(1)}`).join("");
    const area = `${line}L${pts[pts.length - 1][0].toFixed(1)},${y(0).toFixed(1)}L${pts[0][0].toFixed(1)},${y(0).toFixed(1)}Z`;
    const ticks = [];
    for (let v = yMin; v <= yMax + 1e-6; v += step) ticks.push(v);
    const idx = (d) => series.findIndex((p) => p.date === d);
    // x labels: start, roughly weekly, end
    const every = Math.max(1, Math.round(series.length / Math.max(2, Math.floor(iw / 90))));
    const xl = series.map((p, i) => i).filter((i) => i % every === 0 && series.length - 1 - i > every * 0.8).concat(series.length - 1);
    return { x, y, pts, line, area, ticks, idx, xl, iw, ih, zero: y(0) };
  }, [series, W]);

  const li = lowest ? g.idx(lowest.date) : -1;
  const ni = firstNeg ? g.idx(firstNeg.date) : -1;

  const onMove = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    const t = (px - PAD.left) / g.iw;
    const i = Math.max(0, Math.min(series.length - 1, Math.round(t * (series.length - 1))));
    setHover(i);
  };

  const hp = hover != null ? series[hover] : null;
  const tipLeft = hover != null ? Math.min(Math.max(g.pts[hover][0], 110), W - 110) : 0;
  const tipY = hover != null ? g.pts[hover][1] : 0;
  const tipBelow = tipY < 110;   // too close to the top: show it under the point

  // Lowest label sits above the dot, anchored so it never runs off the edge.
  const lowLabel = li >= 0 && (() => {
    const [lx, ly] = g.pts[li];
    const anchor = lx < W * 0.2 ? "start" : lx > W * 0.8 ? "end" : "middle";
    const below = H - PAD.bottom - ly >= 22;   // the lowest point has open space under it
    return { lx, ly, anchor, ty: below ? ly + 19 : ly - 11 };
  })();

  return (
    <div className="pd-fc__chart" ref={wrap}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img"
        aria-label={`Projected balance over the next ${series.length} days${lowest ? `, lowest ${money(lowest.balance)} on ${shortDate(lowest.date)}` : ""}`}
        onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        <defs>
          <linearGradient id="pd-fc-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--at-accent)" stopOpacity="0.26" />
            <stop offset="100%" stopColor="var(--at-accent)" stopOpacity="0.02" />
          </linearGradient>
          <clipPath id="pd-fc-above"><rect x="0" y="0" width={W} height={Math.max(0, g.zero)} /></clipPath>
          <clipPath id="pd-fc-below"><rect x="0" y={g.zero} width={W} height={Math.max(0, H - g.zero)} /></clipPath>
        </defs>

        {g.ticks.map((v) => (
          <g key={v} className="pd-fc__tick">
            {v !== 0 && <line x1={PAD.left} x2={W - PAD.right} y1={g.y(v)} y2={g.y(v)} />}
            <text x={PAD.left - 8} y={g.y(v)} dy="0.32em" textAnchor="end">{v === 0 ? "₹0" : moneyShort(v)}</text>
          </g>
        ))}
        {g.xl.map((i) => (
          <text key={i} className="pd-fc__xl" x={g.x(i)} y={H - 6}
            textAnchor={i === 0 ? "start" : i === series.length - 1 ? "end" : "middle"}>{shortDate(series[i].date)}</text>
        ))}

        <path d={g.area} fill="url(#pd-fc-fill)" clipPath="url(#pd-fc-above)" />
        <path d={g.area} className="pd-fc__neg-area" clipPath="url(#pd-fc-below)" />
        <line className="pd-fc__zero" x1={PAD.left} x2={W - PAD.right} y1={g.zero} y2={g.zero} />
        <path d={g.line} className="pd-fc__line" clipPath="url(#pd-fc-above)" />
        <path d={g.line} className="pd-fc__line pd-fc__line--neg" clipPath="url(#pd-fc-below)" />

        {series.map((p, i) => (p.events && p.events.length ? (
          <circle key={p.date} className={`pd-fc__ev${hover === i ? " is-on" : ""}`} cx={g.pts[i][0]} cy={g.pts[i][1]} r={hover === i ? 5 : 3.5} />
        ) : null))}

        {hover != null && (
          <g className="pd-fc__cross">
            <line x1={g.pts[hover][0]} x2={g.pts[hover][0]} y1={PAD.top - 6} y2={H - PAD.bottom} />
            <circle cx={g.pts[hover][0]} cy={g.pts[hover][1]} r="5" />
          </g>
        )}

        {ni >= 0 && (
          <g className="pd-fc__neg">
            <line x1={g.pts[ni][0]} x2={g.pts[ni][0]} y1={PAD.top - 6} y2={H - PAD.bottom} />
            <circle cx={g.pts[ni][0]} cy={g.pts[ni][1]} r="5.5" />
          </g>
        )}

        {lowLabel && (
          <g className={`pd-fc__low${lowest.balance < 0 ? " is-neg" : ""}`}>
            <circle cx={lowLabel.lx} cy={lowLabel.ly} r="5.5" />
            <text x={lowLabel.lx} y={lowLabel.ty} textAnchor={lowLabel.anchor}>
              Lowest {money(lowest.balance)} · {shortDate(lowest.date)}
            </text>
          </g>
        )}
      </svg>

      {hp && (
        <div className="pd-fc__tip" style={{ left: tipLeft, top: tipBelow ? tipY + 14 : tipY - 14, transform: `translate(-50%, ${tipBelow ? "0" : "-100%"})` }} role="tooltip">
          <div className="pd-fc__tip-head"><span>{fmtDate(hp.date)}</span><b>{money(hp.balance)}</b></div>
          {(hp.events || []).length > 0 && (
            <ul>
              {hp.events.map((e, k) => (
                <li key={k}>
                  <span className="pd-fc__tip-what">{e.what}</span>
                  <span className={e.amount >= 0 ? "pd-fc__in" : "pd-fc__out"}>{signed(e.amount)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export default function Forecast({ data, onShow }) {
  const series = (data && data.series) || [];
  const neg = data && data.first_negative;
  const low = data && data.lowest;
  return (
    <section>
      <SectionHead icon="calendar" title="Next 30 days"
        right={neg ? <Badge tone="madder" dot>Goes below ₹0 on {shortDate(neg.date)}</Badge>
          : low ? <span className="pd-dim pd-xs">projected balance</span> : null} />
      <Card className="pd-fc">
        {!data && <div className="pd-fc__skeleton pd-skeleton" />}
        {data && series.length === 0 && <p className="pd-empty">{data.note || "No forecast yet."}</p>}
        {series.length > 0 && <Chart series={series} lowest={low} firstNeg={neg} />}
        {data && series.length > 0 && (
          <div className="pd-fc__foot">
            <span className="pd-dim pd-xs">{data.note}</span>
            <span className="pd-fc__totals pd-xs">
              Committed out <b>{inr(Math.round(data.committed_out || 0))}</b>
              {data.committed_in > 0 && <> · in <b>{inr(Math.round(data.committed_in))}</b></>}
              {data.source_ids && data.source_ids.length > 0 && onShow && (
                <button type="button" className="pd-source-link" onClick={() => onShow(data.source_ids)}>
                  <Icon name="eye" size={13} /> sources
                </button>
              )}
            </span>
          </div>
        )}
      </Card>
    </section>
  );
}
