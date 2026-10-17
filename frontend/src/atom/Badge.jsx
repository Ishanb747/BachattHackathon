import React from "react";

// "accent" added: the stylesheet defines .at-badge--accent and the usage
// snippet uses tone="accent", but the shipped map only had "viridian".
const TONES = { accent: "at-badge--accent", indigo: "at-badge--indigo", viridian: "at-badge--accent", ochre: "at-badge--ochre", madder: "at-badge--madder", outline: "at-badge--outline" };

/** Badge — tone: "neutral" | "accent" | "indigo" | "ochre" | "madder" | "outline"; dot: show status dot */
export function Badge({ tone = "neutral", dot = false, className = "", children, ...rest }) {
  const cls = ["at-badge", TONES[tone] || "", className].filter(Boolean).join(" ");
  return (
    <span className={cls} {...rest}>
      {dot && <span className="at-badge__dot" />}
      {children}
    </span>
  );
}

/** Chip — selectable pill; active: selected state */
export function Chip({ active = false, className = "", children, ...rest }) {
  const cls = ["at-chip", active && "at-chip--active", className].filter(Boolean).join(" ");
  return <button type="button" className={cls} aria-pressed={active} {...rest}>{children}</button>;
}
