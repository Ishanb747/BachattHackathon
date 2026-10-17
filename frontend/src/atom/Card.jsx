import React from "react";
import { AiSmoke, useAtPigment } from "./Aura.jsx";

/**
 * Card — frosted glass panel.
 * hover: lift on hover
 * smoke: true → blurred two-tone pigment fill that follows the cursor.
 *        Light wash by default; appearance="dark" for pigment in dark glass.
 *        `busy` speeds the drift while processing; `pigment` picks the
 *        preset (or hex); `blur` (px) controls softness.
 */
export function Card({ hover = false, smoke = false, appearance = "light", busy = false, pigment, tint, blur = 18, className = "", style, children, ...rest }) {
  const pig = useAtPigment(pigment || tint);
  const dark = appearance === "dark";
  const cls = [
    "at-card",
    hover && "at-card--hover",
    smoke && "at-card--smoke",
    smoke && dark && "at-card--smoke-dark",
    className,
  ].filter(Boolean).join(" ");
  return (
    <div className={cls} style={smoke ? { ...style, "--at-glow": pig.glow } : style} {...rest}>
      {smoke && <AiSmoke pigment={pigment || tint} light={!dark} speed={busy ? 0.26 : 0.08} blur={blur} />}
      {smoke ? <div className="at-card__inner">{children}</div> : children}
    </div>
  );
}

export function CardTitle({ children, ...rest }) { return <h3 className="at-card__title" {...rest}>{children}</h3>; }
export function CardBody({ children, ...rest }) { return <p className="at-card__body" {...rest}>{children}</p>; }
