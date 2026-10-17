import React from "react";
import { ICONS } from "./icons.js";
import { AiSmoke, useAtPigment } from "./Aura.jsx";

/**
 * Icon — hand-drawn stroke icon (24×24 grid, SF Symbols flavor).
 * <Icon name="fan" /> · size (px) · strokeWidth (default 1.8)
 * Colors with `currentColor`, so it inherits the text color.
 * Unknown names render nothing (and warn in dev).
 */
export function Icon({ name, size = 20, strokeWidth = 1.8, className = "", style, ...rest }) {
  const svg = ICONS[name];
  if (!svg) {
    if (typeof console !== "undefined") console.warn(`[atomberg-ui] unknown icon: ${name}`);
    return null;
  }
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={rest["aria-label"] ? undefined : true}
      className={["at-icon", className].filter(Boolean).join(" ")}
      style={style}
      dangerouslySetInnerHTML={{ __html: svg }}
      {...rest}
    />
  );
}

/**
 * IconButton — round icon-only button.
 * <IconButton icon="bell" label="Notifications" />
 * variant: "default" | "primary" (smoke) | "ghost"
 * size: "sm" | "md" | "lg" · label is required (accessibility)
 */
export function IconButton({ icon, label, variant = "default", size = "md", pigment, busy = false, className = "", style, ...rest }) {
  const pig = useAtPigment(pigment);
  const smoke = variant === "primary";
  const px = size === "sm" ? 32 : size === "lg" ? 52 : 42;
  const cls = [
    "at-btn", "at-btn--icon",
    smoke && "at-btn--smoke-light",
    variant === "ghost" && "at-btn--ghost",
    className,
  ].filter(Boolean).join(" ");
  return (
    <button
      className={cls}
      aria-label={label}
      title={label}
      style={{ ...style, width: px, height: px, minHeight: px, ...(smoke ? { "--at-glow": pig.glow } : {}) }}
      {...rest}
    >
      {smoke && <AiSmoke pigment={pigment} light speed={busy ? 0.3 : 0.09} blur={12} />}
      <span className="at-btn__label">
        <Icon name={icon} size={size === "sm" ? 16 : size === "lg" ? 24 : 20} />
      </span>
    </button>
  );
}
