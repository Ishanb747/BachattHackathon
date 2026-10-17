// Atomberg UI pigment presets (from list_pigments): two-tone pairs + glow.
export const PIGMENTS = {
  emerald:   { a: "#00b871", b: "#00e5a0", glow: "rgba(0,184,113,0.5)" },
  gold:      { a: "#f0a400", b: "#ffd35c", glow: "rgba(240,164,0,0.5)" },
  violet:    { a: "#7a4df0", b: "#b388ff", glow: "rgba(122,77,240,0.5)" },
  purple:    { a: "#9c27b0", b: "#d05ce3", glow: "rgba(156,39,176,0.5)" },
  wine:      { a: "#b0184e", b: "#e04a7a", glow: "rgba(176,24,78,0.5)" },
  champagne: { a: "#e2ab4f", b: "#f7dfa8", glow: "rgba(226,171,79,0.48)" },
  indigo:    { a: "#3e6de0", b: "#7fa3f5", glow: "rgba(62,109,224,0.5)" },
  rose:      { a: "#f25c6e", b: "#ff9fb0", glow: "rgba(242,92,110,0.5)" },
};

export function hexToRgb(hex) {
  let h = String(hex).replace("#", "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  const n = parseInt(h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Resolve a preset name or raw hex into {a, b, glow}. */
export function resolvePigment(p) {
  if (!p) return PIGMENTS.emerald;
  if (PIGMENTS[p]) return PIGMENTS[p];
  if (typeof p === "string" && p.startsWith("#")) {
    const [r, g, b] = hexToRgb(p);
    const lift = (v) => Math.min(255, Math.round(v + (255 - v) * 0.45));
    const b2 = "#" + [lift(r), lift(g), lift(b)].map((v) => v.toString(16).padStart(2, "0")).join("");
    return { a: p, b: b2, glow: `rgba(${r},${g},${b},0.5)` };
  }
  return PIGMENTS.emerald;
}
