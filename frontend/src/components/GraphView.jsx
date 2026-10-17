import React, { useEffect, useMemo, useRef, useState } from "react";
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide, forceX, forceY } from "d3-force";
import { Icon, Badge } from "../atom";
import { inr, fmtDate } from "../lib/format.js";

// Node look per type: AtomUI pigments, radius by importance.
export const NODE_STYLE = {
  User:     { c: "#1e2433", r: 15 },
  Account:  { c: "#3e6de0", r: 11 },
  Card:     { c: "#f25c6e", r: 11 },
  Due:      { c: "#c72c40", r: 9 },
  Policy:   { c: "#7fa3f5", r: 9 },
  SIP:      { c: "#00b871", r: 9 },
  Merchant: { c: "#f0a400", r: 8 },
  Insight:  { c: "#a87300", r: 9 },
  Reminder: { c: "#007a4d", r: 8 },
  Txn:      { c: "#8a90a0", r: 5 },
  Source:   { c: "#00b871", r: 5.5 },
};
const styleOf = (t) => NODE_STYLE[t] || { c: "#8a90a0", r: 6 };
const W = 640, H = 440;

const idOf = (x) => (typeof x === "object" && x ? x.id : x);

export default function GraphView({ graph, glowIds, loading }) {
  const svgRef = useRef(null);
  const wrapRef = useRef(null);
  const simRef = useRef(null);
  const [, setFrame] = useState(0);
  const [view, setView] = useState({ k: 1, x: 0, y: 0 });
  const viewRef = useRef(view); viewRef.current = view;
  const [hover, setHover] = useState(null);     // {node, x, y}
  const [selected, setSelected] = useState(null);
  const dragRef = useRef(null);

  const data = useMemo(() => {
    if (!graph) return null;
    const ids = new Set(graph.nodes.map((n) => n.id));
    const nodes = graph.nodes.map((n) => ({ ...n }));
    const links = graph.links.filter((l) => ids.has(idOf(l.source)) && ids.has(idOf(l.target)))
      .map((l) => ({ ...l, source: idOf(l.source), target: idOf(l.target) }));
    const deg = {};
    links.forEach((l) => { deg[l.source] = (deg[l.source] || 0) + 1; deg[l.target] = (deg[l.target] || 0) + 1; });
    nodes.forEach((n) => { n.deg = deg[n.id] || 0; });
    return { nodes, links };
  }, [graph]);

  useEffect(() => {
    if (!data) return;
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const sim = forceSimulation(data.nodes)
      .force("link", forceLink(data.links).id((d) => d.id).distance((l) => {
        const t = l.target.type || "";
        return t === "Source" ? 26 : t === "Txn" ? 38 : 58;
      }).strength(0.7))
      .force("charge", forceManyBody().strength((d) => (d.type === "User" ? -420 : d.type === "Source" || d.type === "Txn" ? -60 : -180)))
      .force("collide", forceCollide().radius((d) => styleOf(d.type).r + 4))
      .force("center", forceCenter(0, 0))
      .force("x", forceX(0).strength(0.04))
      .force("y", forceY(0).strength(0.06));
    simRef.current = sim;
    if (reduced) { sim.stop(); for (let i = 0; i < 300; i++) sim.tick(); setFrame((f) => f + 1); }
    else {
      let raf = 0;
      sim.on("tick", () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; setFrame((f) => f + 1); }); });
    }
    return () => sim.stop();
  }, [data]);

  // Wheel zoom around the pointer (needs a non-passive listener).
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (e) => {
      e.preventDefault();
      const pt = toSvg(e.clientX, e.clientY);
      const v = viewRef.current;
      const k = Math.max(0.4, Math.min(4, v.k * Math.exp(-e.deltaY * 0.0015)));
      // keep the point under the cursor fixed
      const gx = (pt.x - v.x) / v.k, gy = (pt.y - v.y) / v.k;
      setView({ k, x: pt.x - gx * k, y: pt.y - gy * k });
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  });

  const toSvg = (cx, cy) => {
    const svg = svgRef.current;
    const r = svg.getBoundingClientRect();
    return { x: ((cx - r.left) / r.width) * W - W / 2, y: ((cy - r.top) / r.height) * H - H / 2 };
  };
  const toGraph = (cx, cy) => { const p = toSvg(cx, cy), v = viewRef.current; return { x: (p.x - v.x) / v.k, y: (p.y - v.y) / v.k }; };

  const onPointerDown = (e, node) => {
    try { svgRef.current.setPointerCapture(e.pointerId); } catch {}
    if (node) {
      const g = toGraph(e.clientX, e.clientY);
      node.fx = node.x; node.fy = node.y;
      dragRef.current = { kind: "node", node, sx: e.clientX, sy: e.clientY, moved: false, ox: g.x - node.x, oy: g.y - node.y };
      simRef.current && simRef.current.alphaTarget(0.25).restart();
    } else {
      dragRef.current = { kind: "pan", sx: e.clientX, sy: e.clientY, vx: viewRef.current.x, vy: viewRef.current.y, moved: false };
    }
  };
  const onPointerMove = (e) => {
    const d = dragRef.current;
    if (!d) return;
    if (Math.abs(e.clientX - d.sx) + Math.abs(e.clientY - d.sy) > 3) d.moved = true;
    if (d.kind === "node") {
      const g = toGraph(e.clientX, e.clientY);
      d.node.fx = g.x - d.ox; d.node.fy = g.y - d.oy;
    } else {
      const r = svgRef.current.getBoundingClientRect();
      setView((v) => ({ ...v, x: d.vx + ((e.clientX - d.sx) / r.width) * W, y: d.vy + ((e.clientY - d.sy) / r.height) * H }));
    }
  };
  const onPointerUp = () => {
    const d = dragRef.current;
    dragRef.current = null;
    if (!d) return;
    if (d.kind === "node") {
      d.node.fx = null; d.node.fy = null;
      simRef.current && simRef.current.alphaTarget(0);
      if (!d.moved) setSelected((s) => (s && s.id === d.node.id ? null : d.node));
    } else if (!d.moved) setSelected(null);
  };

  const showTip = (e, node) => {
    const r = wrapRef.current.getBoundingClientRect();
    setHover({ node, x: e.clientX - r.left, y: e.clientY - r.top });
  };

  // Evidence highlight: cited nodes, their edges, and the nodes at the other end.
  const lit = useMemo(() => {
    const nodes = new Set(), near = new Set(), links = new Set();
    if (!data || !glowIds || !glowIds.size) return { nodes, near, links };
    data.nodes.forEach((n) => { if (glowIds.has(n.id)) nodes.add(n.id); });
    data.links.forEach((l, i) => {
      const s = idOf(l.source), t = idOf(l.target);
      if (nodes.has(s) || nodes.has(t)) { links.add(i); near.add(s); near.add(t); }
    });
    return { nodes, near, links };
  }, [data, glowIds]);
  const anyLit = lit.nodes.size > 0;

  if (loading && !data) return <div className="pd-graph pd-graph--empty"><span className="pd-dim">Loading graph…</span></div>;
  if (!data) return <div className="pd-graph pd-graph--empty"><span className="pd-dim">No graph yet.</span></div>;

  const types = [...new Set(data.nodes.map((n) => n.type))];
  return (
    <div className="pd-graph" ref={wrapRef}>
      <svg
        ref={svgRef}
        className={`pd-graph__svg${anyLit ? " pd-graph__svg--lit" : ""}`}
        viewBox={`${-W / 2} ${-H / 2} ${W} ${H}`}
        onPointerDown={(e) => onPointerDown(e, null)}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        role="img"
        aria-label="Money graph"
      >
        <defs>
          <radialGradient id="pdNodeGlow">
            <stop offset="0" stopColor="#00e5a0" stopOpacity="0.85" />
            <stop offset="1" stopColor="#00b871" stopOpacity="0" />
          </radialGradient>
        </defs>
        <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
          <g className="pd-graph__links">
            {data.links.map((l, i) => {
              const s = l.source, t = l.target;
              if (typeof s !== "object" || s.x == null) return null;
              const on = lit.links.has(i);
              return <line key={i} x1={s.x} y1={s.y} x2={t.x} y2={t.y} className={on ? "pd-link pd-link--lit" : "pd-link"} />;
            })}
          </g>
          <g className="pd-graph__nodes">
            {data.nodes.map((n) => {
              if (n.x == null) return null;
              const st = styleOf(n.type);
              const on = lit.nodes.has(n.id), near = lit.near.has(n.id);
              const sel = selected && selected.id === n.id;
              const showLabel = st.r >= 8 || on || sel;
              return (
                <g key={n.id} transform={`translate(${n.x} ${n.y})`}
                  className={`pd-node${on ? " pd-node--lit" : near ? " pd-node--near" : ""}${sel ? " pd-node--sel" : ""}`}
                  onPointerDown={(e) => { e.stopPropagation(); onPointerDown(e, n); }}
                  onPointerEnter={(e) => showTip(e, n)}
                  onPointerMove={(e) => showTip(e, n)}
                  onPointerLeave={() => setHover(null)}
                  data-magnetic-off
                >
                  {(on || sel) && <circle r={st.r * 2.6} fill="url(#pdNodeGlow)" className="pd-node__halo" />}
                  <circle r={st.r + 3} fill={st.c} opacity="0.16" />
                  <circle r={st.r} fill="#fff" stroke={on ? "#00b871" : st.c} strokeWidth={on ? 3 : 2} />
                  {n.type === "User" && <circle r={st.r * 0.45} fill={st.c} />}
                  {n.type === "Source" && <circle r={1.8} fill={st.c} />}
                  {showLabel && (
                    <text y={st.r + 11} textAnchor="middle" className="pd-node__label">
                      {String(n.label).length > 22 ? String(n.label).slice(0, 21) + "…" : n.label}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        </g>
      </svg>

      {hover && (
        <div className="pd-graph__tip" style={{ left: hover.x, top: hover.y }}>
          <span className="pd-graph__tip-type" style={{ color: styleOf(hover.node.type).c }}>{hover.node.type}</span>
          <span>{hover.node.label}</span>
          {hover.node.props && hover.node.props.amount != null && <span className="pd-dim">{inr(hover.node.props.amount)}</span>}
        </div>
      )}

      <div className="pd-graph__legend">
        {types.map((t) => (
          <span key={t} className="pd-legend"><i style={{ background: styleOf(t).c }} />{t}</span>
        ))}
      </div>
      <div className="pd-graph__tools">
        <button type="button" className="pd-icon-btn" aria-label="Zoom in" onClick={() => setView((v) => ({ ...v, k: Math.min(4, v.k * 1.25) }))}><Icon name="search" size={14} /></button>
        <button type="button" className="pd-icon-btn" aria-label="Reset view" onClick={() => setView({ k: 1, x: 0, y: 0 })}><Icon name="refresh" size={14} /></button>
      </div>

      {selected && <NodeDetail node={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function NodeDetail({ node, onClose }) {
  const p = node.props || {};
  const entries = Object.entries(p).filter(([k, v]) => k !== "text" && (typeof v === "string" || typeof v === "number"));
  return (
    <div className="pd-graph__detail pd-pop">
      <div className="pd-row pd-row--between">
        <span className="pd-row"><Badge tone={node.type === "Source" ? "accent" : "outline"}>{node.type}</Badge> <b className="pd-sm">{node.label}</b></span>
        <button type="button" className="pd-icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" size={14} /></button>
      </div>
      {p.text && <p className="pd-src__text">{p.text}</p>}
      {entries.length > 0 && (
        <dl className="pd-kv">
          {entries.map(([k, v]) => (
            <React.Fragment key={k}>
              <dt>{k.replace(/_/g, " ")}</dt>
              <dd>{k === "at" || k === "due_date" || k === "date" ? fmtDate(String(v)) : typeof v === "number" && /amount|balance|limit|premium|impact/.test(k) ? inr(v) : String(v)}</dd>
            </React.Fragment>
          ))}
        </dl>
      )}
      <code className="pd-src__id">{node.id}</code>
    </div>
  );
}
