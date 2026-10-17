import React from "react";
import { AiSmoke } from "./Aura.jsx";

/** Stat — KPI tile. delta: "+12.4%"; trend: "up" | "down";
    smoke: blurred pigment fill (hero metric); pigment: preset name or hex */
export function Stat({ label, value, delta, trend, smoke = false, pigment, tint, blur = 18, className = "", ...rest }) {
  const inner = (
    <>
      <span className="at-label">{label}</span>
      <span className="at-stat__value">{value}</span>
      {delta && (
        <span className={`at-stat__delta ${trend === "down" ? "at-stat__delta--down" : "at-stat__delta--up"}`}>
          {trend === "down" ? "▼" : "▲"} {delta}
        </span>
      )}
    </>
  );
  return (
    <div className={["at-stat", smoke && "at-stat--smoke", className].filter(Boolean).join(" ")} {...rest}>
      {smoke && <AiSmoke pigment={pigment || tint} light speed={0.07} blur={blur} />}
      {smoke ? <div className="at-stat__inner">{inner}</div> : inner}
    </div>
  );
}

/** Avatar — initials or src image. size: "sm" | "md" | "lg" */
export function Avatar({ src, alt = "", size = "md", className = "", style, children, ...rest }) {
  const cls = ["at-avatar", size === "sm" && "at-avatar--sm", size === "lg" && "at-avatar--lg", className].filter(Boolean).join(" ");
  return (
    <span className={cls} style={style} {...rest}>
      {src ? <img src={src} alt={alt} /> : children}
    </span>
  );
}
export function AvatarGroup({ children, ...rest }) {
  return <span className="at-avatar-group" {...rest}>{children}</span>;
}

/** Timeline — items: [{time, title, desc, tone?: "indigo"|"viridian"|"ochre"}] */
export function Timeline({ items = [], className = "", ...rest }) {
  return (
    <ul className={["at-timeline", className].filter(Boolean).join(" ")} {...rest}>
      {items.map((it, i) => (
        <li key={i} className={`at-timeline__item${it.tone && it.tone !== "accent" ? ` at-timeline__item--${it.tone}` : ""}`}>
          <span className="at-timeline__dot" />
          {it.time && <div className="at-timeline__time">{it.time}</div>}
          <div className="at-timeline__title">{it.title}</div>
          {it.desc && <p className="at-timeline__desc">{it.desc}</p>}
        </li>
      ))}
    </ul>
  );
}
