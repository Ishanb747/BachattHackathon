import { useEffect, useRef } from "react";

// Custom cursor: a dot that tracks exactly, and a ring that lags on a spring.
// Over buttons/links the ring morphs onto the element (magnetic snap); over
// cards it grows; it shrinks on press and hides over text inputs. Also drives
// the card tilt ([data-tilt]). Off on touch devices and reduced motion.

const MAGNET = "button:not(:disabled), a[href], [role='tab'], .at-chip, [data-magnetic]";
const GROW = ".at-card, .at-stat, [data-cursor='grow']";
const TEXT = "input, textarea, select, [contenteditable='true']";

export function cursorEnabled() {
  if (typeof matchMedia === "undefined") return false;
  return matchMedia("(hover: hover) and (pointer: fine)").matches && !matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export default function CursorFollower() {
  const dotRef = useRef(null);
  const ringRef = useRef(null);

  useEffect(() => {
    if (!cursorEnabled()) return;
    const root = document.documentElement;
    root.classList.add("pd-cursor-on");
    const dot = dotRef.current, ring = ringRef.current;
    const p = { x: innerWidth / 2, y: innerHeight / 2 };        // pointer
    const r = { x: p.x, y: p.y, w: 36, h: 36, rad: 18 };         // ring (spring)
    const v = { x: 0, y: 0 };
    let target = null, mode = "free", down = false, hidden = true, raf = 0;
    let magnetEl = null, tiltEl = null;

    const setHidden = (h) => { if (h !== hidden) { hidden = h; root.classList.toggle("pd-cursor-hidden", h); } };

    const resetMagnet = () => {
      if (magnetEl) { magnetEl.style.translate = ""; magnetEl = null; }
    };
    const resetTilt = () => {
      if (tiltEl) {
        tiltEl.classList.remove("pd-tilting");
        tiltEl.style.transform = "";
        tiltEl = null;
      }
    };

    const onMove = (e) => {
      if (e.pointerType && e.pointerType !== "mouse") return;
      p.x = e.clientX; p.y = e.clientY;
      setHidden(false);
      const el = e.target instanceof Element ? e.target : null;
      const text = el && el.closest(TEXT);
      const mag = !text && el && el.closest(MAGNET);
      const grow = !text && !mag && el && el.closest(GROW);
      mode = text ? "text" : mag ? "magnet" : grow ? "grow" : "free";
      target = mag || null;

      if (mag !== magnetEl) resetMagnet();
      if (mag) {
        const b = mag.getBoundingClientRect();
        if (b.width < 320) {
          magnetEl = mag;
          const dx = (p.x - (b.left + b.width / 2)) * 0.18, dy = (p.y - (b.top + b.height / 2)) * 0.22;
          mag.style.translate = `${dx.toFixed(1)}px ${dy.toFixed(1)}px`;
        }
      }

      const t = el && el.closest("[data-tilt]");
      if (t !== tiltEl) resetTilt();
      if (t) {
        tiltEl = t;
        t.classList.add("pd-tilting");
        const b = t.getBoundingClientRect();
        const nx = (p.x - b.left) / b.width - 0.5, ny = (p.y - b.top) / b.height - 0.5;
        const max = Math.min(6, 1400 / Math.max(b.width, b.height));
        t.style.transform = `perspective(900px) rotateX(${(-ny * max).toFixed(2)}deg) rotateY(${(nx * max).toFixed(2)}deg) translateZ(0)`;
      }
    };
    const onDown = () => { down = true; root.classList.add("pd-cursor-down"); };
    const onUp = () => { down = false; root.classList.remove("pd-cursor-down"); };
    const onLeave = () => { setHidden(true); resetMagnet(); resetTilt(); };

    const tick = () => {
      raf = requestAnimationFrame(tick);
      dot.style.transform = `translate3d(${p.x}px, ${p.y}px, 0) translate(-50%, -50%) scale(${mode === "magnet" ? 0.5 : 1})`;
      let tx = p.x, ty = p.y, tw = 36, th = 36, trad = 18;
      if (mode === "magnet" && target && target.isConnected) {
        const b = target.getBoundingClientRect();
        const cx = b.left + b.width / 2, cy = b.top + b.height / 2;
        if (b.width < 320) {
          tx = cx + (p.x - cx) * 0.22; ty = cy + (p.y - cy) * 0.22;
          tw = b.width + 12; th = b.height + 12;
          const br = parseFloat(getComputedStyle(target).borderTopLeftRadius) || 12;
          trad = Math.min(th / 2, br + 6);
        } else { tw = th = 56; trad = 28; }
      } else if (mode === "grow") { tw = th = 60; trad = 30; }
      else if (mode === "text") { tw = th = 8; trad = 4; }
      if (down) { tw *= 0.82; th *= 0.82; trad *= 0.82; }
      // spring for position, lerp for size
      v.x = (v.x + (tx - r.x) * 0.16) * 0.62;
      v.y = (v.y + (ty - r.y) * 0.16) * 0.62;
      r.x += v.x; r.y += v.y;
      r.w += (tw - r.w) * 0.2; r.h += (th - r.h) * 0.2; r.rad += (trad - r.rad) * 0.2;
      ring.style.transform = `translate3d(${r.x - r.w / 2}px, ${r.y - r.h / 2}px, 0)`;
      ring.style.width = `${r.w}px`; ring.style.height = `${r.h}px`; ring.style.borderRadius = `${r.rad}px`;
      ring.dataset.mode = mode;
    };
    raf = requestAnimationFrame(tick);

    addEventListener("pointermove", onMove, { passive: true });
    addEventListener("pointerdown", onDown, { passive: true });
    addEventListener("pointerup", onUp, { passive: true });
    document.addEventListener("pointerleave", onLeave);
    document.documentElement.addEventListener("mouseleave", onLeave);
    return () => {
      cancelAnimationFrame(raf);
      removeEventListener("pointermove", onMove);
      removeEventListener("pointerdown", onDown);
      removeEventListener("pointerup", onUp);
      document.removeEventListener("pointerleave", onLeave);
      document.documentElement.removeEventListener("mouseleave", onLeave);
      resetMagnet(); resetTilt();
      root.classList.remove("pd-cursor-on", "pd-cursor-hidden", "pd-cursor-down");
    };
  }, []);

  if (!cursorEnabled()) return null;
  return (
    <>
      <div ref={ringRef} className="pd-cursor-ring" aria-hidden="true" />
      <div ref={dotRef} className="pd-cursor-dot" aria-hidden="true" />
    </>
  );
}
