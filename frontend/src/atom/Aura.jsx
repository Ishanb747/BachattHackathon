import React, { createContext, useContext, useEffect, useRef } from "react";
import { startSmoke } from "./smoke.js";
import { resolvePigment } from "./pigments.js";

/* Drift speed per state — pigment moves faster the harder the AI works */
const ORB_SPEEDS = { idle: 0.06, listening: 0.16, thinking: 0.3 };

/* ---- App-wide primary pigment ------------------------------------------- */
const PigmentContext = createContext("emerald");

/**
 * AtProvider — sets the primary pigment for every smoke element below it.
 * <AtProvider pigment="wine"><App /></AtProvider>
 * Pigments: emerald · gold · violet · purple · wine · champagne · indigo · rose
 * (or any raw hex).
 */
export function AtProvider({ pigment = "emerald", children }) {
  return <PigmentContext.Provider value={pigment}>{children}</PigmentContext.Provider>;
}
export function useAtPigment(override) {
  const ctx = useContext(PigmentContext);
  return resolvePigment(override || ctx);
}

/* Wire pointer tracking on an element: the clouds bend toward the cursor */
function usePointer(fxRef, canvasRef, getTarget) {
  useEffect(() => {
    const canvas = canvasRef.current;
    const el = getTarget(canvas);
    if (!el) return;
    const move = (e) => {
      const r = canvas.getBoundingClientRect();
      fxRef.current && fxRef.current.setMouse(e.clientX - r.left, e.clientY - r.top, 1);
    };
    const leave = () => {
      const r = canvas.getBoundingClientRect();
      fxRef.current && fxRef.current.setMouse(r.width / 2, r.height / 2, 0);
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerleave", leave);
    return () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerleave", leave);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

/**
 * AiOrb — glassy sphere with two-tone pigment clouds drifting inside
 * (WebGL fbm shader). Move the cursor over it — the clouds follow.
 *
 * <AiOrb state="idle" pigment="violet" size={240} />
 * state: "idle" | "listening" | "thinking"
 * pigment: preset name or hex · light: pastel sphere on white
 */
export function AiOrb({ state = "idle", pigment, tint, light = false, deep, size = 220, blur = 0, className = "", style, children, ...rest }) {
  const pig = useAtPigment(pigment || tint);
  const canvasRef = useRef(null);
  const fxRef = useRef(null);
  const base = deep || (light ? "#ffffff" : "#04140d");

  useEffect(() => {
    const fx = startSmoke(canvasRef.current, {
      tint: pig.a, tint2: pig.b, deep: base,
      speed: ORB_SPEEDS[state] ?? ORB_SPEEDS.idle, orb: true, light,
    });
    fxRef.current = fx;
    return () => fx.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, light]);

  useEffect(() => { fxRef.current && fxRef.current.setSpeed(ORB_SPEEDS[state] ?? ORB_SPEEDS.idle); }, [state]);
  useEffect(() => { fxRef.current && fxRef.current.setTints(pig.a, pig.b); }, [pig.a, pig.b]);
  usePointer(fxRef, canvasRef, (c) => c && c.parentElement);

  return (
    <div
      className={["at-orb", className].filter(Boolean).join(" ")}
      role="status"
      aria-label={state === "idle" ? "Assistant idle" : `Assistant ${state}`}
      style={{ ...style, width: size, height: size, "--at-glow": pig.glow }}
      {...rest}
    >
      <canvas
        ref={canvasRef}
        className="at-orb__canvas"
        style={blur ? { filter: `blur(${blur}px)`, transform: `scale(${1 + (blur * 2) / size + 0.02})` } : undefined}
      />
      {children && <div className="at-orb__content" style={{ fontSize: size / 8 }}>{children}</div>}
    </div>
  );
}

/**
 * AiSmoke — the drifting pigment as a fill layer inside any component.
 * Place inside a position:relative, overflow:hidden parent; it covers it and
 * reacts to the cursor moving over that parent.
 *
 * pigment: preset name or hex · light: pastel on white · blur: softness (px)
 */
export function AiSmoke({ pigment, tint, light = false, deep, speed = 0.12, blur = 0, className = "", style, ...rest }) {
  const pig = useAtPigment(pigment || tint);
  const canvasRef = useRef(null);
  const fxRef = useRef(null);
  const base = deep || (light ? "#ffffff" : "#04140d");

  useEffect(() => {
    const fx = startSmoke(canvasRef.current, { tint: pig.a, tint2: pig.b, deep: base, speed, orb: false, light });
    fxRef.current = fx;
    return () => fx.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, light]);
  useEffect(() => { fxRef.current && fxRef.current.setSpeed(speed); }, [speed]);
  useEffect(() => { fxRef.current && fxRef.current.setTints(pig.a, pig.b); }, [pig.a, pig.b]);
  usePointer(fxRef, canvasRef, (c) => c && c.closest(".at-smoke") && c.closest(".at-smoke").parentElement);

  return (
    <div
      className={["at-smoke", className].filter(Boolean).join(" ")}
      style={{ ...style, "--at-glow": pig.glow }}
      aria-hidden="true"
      {...rest}
    >
      <canvas
        ref={canvasRef}
        className="at-smoke__canvas"
        style={blur ? { filter: `blur(${blur}px)`, transform: "scale(1.3)" } : undefined}
      />
    </div>
  );
}
