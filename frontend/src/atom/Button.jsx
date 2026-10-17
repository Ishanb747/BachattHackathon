import React, { useState } from "react";
import { AiSmoke, useAtPigment } from "./Aura.jsx";

const VARIANTS = { ghost: "at-btn--ghost", accent: "at-btn--accent", indigo: "at-btn--indigo", danger: "at-btn--danger" };
const SIZES = { sm: "at-btn--sm", md: "", lg: "at-btn--lg" };

/**
 * Button
 * variant: "default" | "primary" | "ghost" | "accent" | "indigo" | "danger"
 * size: "sm" | "md" | "lg"
 *
 * Primary buttons carry the live two-tone smoke by default — a blurred wash
 * on white (appearance="light", default) or pigment in dark glass
 * (appearance="dark"). The wash always flows, bends toward the cursor,
 * quickens on hover, and runs fast with `busy` while the AI works.
 * pigment: preset name (emerald · gold · violet · purple · wine · champagne ·
 * indigo · rose) or hex; defaults to the AtProvider pigment.
 */
export function Button({ variant = "default", size = "md", appearance = "light", pigment, tint, busy = false, blur = 14, className = "", style, children, ...rest }) {
  const [hov, setHov] = useState(false);
  const pig = useAtPigment(pigment || tint);
  const smoke = variant === "primary";
  const dark = appearance === "dark";
  const cls = [
    "at-btn",
    smoke && (dark ? "at-btn--smoke-dark" : "at-btn--smoke-light"),
    VARIANTS[variant] || "",
    SIZES[size] || "",
    className,
  ].filter(Boolean).join(" ");
  const speed = busy ? 0.34 : hov ? 0.22 : 0.09;
  return (
    <button
      className={cls}
      style={smoke ? { ...style, "--at-glow": pig.glow } : style}
      onMouseEnter={smoke ? () => setHov(true) : undefined}
      onMouseLeave={smoke ? () => setHov(false) : undefined}
      {...rest}
    >
      {smoke && <AiSmoke pigment={pigment || tint} light={!dark} speed={speed} blur={blur} />}
      <span className="at-btn__label">{children}</span>
    </button>
  );
}
