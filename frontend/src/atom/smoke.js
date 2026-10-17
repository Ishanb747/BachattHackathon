// Atomberg UI smoke: drifting two-tone pigment (WebGL domain-warped fbm).
// startSmoke(canvas, {tint, tint2, deep, speed, orb, light}) ->
//   { stop, setSpeed, setTints, setMouse }
// One WebGL context per call; keep the page to ~12 of these.
import { hexToRgb } from "./pigments.js";

const VERT = `attribute vec2 a; void main(){ gl_Position = vec4(a, 0.0, 1.0); }`;

const FRAG = `
precision mediump float;
uniform vec2 r;
uniform float t;
uniform vec3 m;
uniform vec3 c1, c2, bg;
uniform float orb, light;
float h(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float n(vec2 p){
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(h(i), h(i + vec2(1.0, 0.0)), u.x), mix(h(i + vec2(0.0, 1.0)), h(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fbm(vec2 p){
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 5; i++){ v += a * n(p); p = p * 2.02 + vec2(1.7, 9.2); a *= 0.5; }
  return v;
}
void main(){
  float s = min(r.x, r.y);
  vec2 p = (gl_FragCoord.xy - 0.5 * r) / s;
  vec2 mm = (m.xy - 0.5 * r) / s;
  // clouds bend toward the cursor
  p += (mm - p) * 0.22 * m.z * exp(-length(p - mm) * 2.2);
  vec2 q = vec2(fbm(p * 1.5 + vec2(0.0, t * 0.9)), fbm(p * 1.5 + vec2(5.2, -t * 0.7)));
  vec2 w = vec2(fbm(p * 1.3 + q * 1.9 + vec2(1.7, 9.2) + t * 0.45), fbm(p * 1.3 + q * 1.9 + vec2(8.3, 2.8) - t * 0.38));
  float f = fbm(p * 1.15 + w * 1.7);
  float a1 = smoothstep(0.38, 0.82, f);
  float a2 = smoothstep(0.42, 0.9, w.x * 0.6 + q.y * 0.5);
  vec3 col = bg;
  if (light > 0.5) {
    col = mix(col, c2, a2 * 0.72);
    col = mix(col, c1, a1 * 0.82);
  } else {
    col = mix(col, c1 * 0.95, a1 * 0.95);
    col = mix(col, c2, a2 * a1 * 0.75);
    col += c2 * 0.06 * a2;
  }
  if (orb > 0.5) {
    float d = length(p) * 2.0;
    float spec = smoothstep(0.42, 0.0, length(p - vec2(-0.17, 0.2))) * (light > 0.5 ? 0.25 : 0.32);
    float rim = smoothstep(0.7, 1.0, d);
    col += spec;
    col = mix(col, mix(c2, vec3(1.0), 0.55), rim * 0.32);
    col *= 1.0 - smoothstep(0.88, 1.0, d) * (light > 0.5 ? 0.0 : 0.25);
  }
  gl_FragColor = vec4(col, 1.0);
}`;

const rgb01 = (hex) => hexToRgb(hex).map((v) => v / 255);
const reduced = () => typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

function fallback(canvas, opts) {
  // No WebGL: a static CSS bloom on the canvas itself.
  const paint = (a, b) => {
    canvas.style.background = `radial-gradient(60% 70% at 30% 30%, ${a}, transparent 70%), radial-gradient(60% 70% at 75% 70%, ${b}, transparent 70%), ${opts.deep}`;
  };
  paint(opts.tint, opts.tint2);
  return { stop() {}, setSpeed() {}, setMouse() {}, setTints: paint };
}

export function startSmoke(canvas, opts) {
  const o = { tint: "#00b871", tint2: "#00e5a0", deep: "#04140d", speed: 0.1, orb: false, light: false, ...opts };
  const gl = canvas.getContext("webgl", { antialias: false, premultipliedAlpha: false, alpha: false, powerPreference: "low-power" });
  if (!gl) return fallback(canvas, o);

  const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s; };
  const prog = gl.createProgram();
  gl.attachShader(prog, sh(gl.VERTEX_SHADER, VERT));
  gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FRAG));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return fallback(canvas, o);
  gl.useProgram(prog);
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, "a");
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const U = {};
  ["r", "t", "m", "c1", "c2", "bg", "orb", "light"].forEach((k) => (U[k] = gl.getUniformLocation(prog, k)));

  let c1 = rgb01(o.tint), c2 = rgb01(o.tint2);
  const bg = rgb01(o.deep);
  let speed = o.speed, t = Math.random() * 40, last = performance.now(), raf = 0, alive = true, visible = true;
  let w = 1, h = 1;
  const mouse = { x: 0, y: 0, k: 0, tx: 0, ty: 0, tk: 0 };
  const slow = reduced() ? 0.25 : 1;

  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    const rect = canvas.getBoundingClientRect();
    w = Math.max(1, Math.round(rect.width * dpr));
    h = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    gl.viewport(0, 0, w, h);
    if (!mouse.tk) { mouse.x = mouse.tx = w / 2; mouse.y = mouse.ty = h / 2; }
  };
  resize();
  const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
  ro && ro.observe(canvas);
  const io = typeof IntersectionObserver !== "undefined"
    ? new IntersectionObserver((es) => { visible = es[0] ? es[0].isIntersecting : true; })
    : null;
  io && io.observe(canvas);

  const frame = (now) => {
    if (!alive) return;
    raf = requestAnimationFrame(frame);
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    if (!visible || document.hidden) return;
    t += dt * speed * 3.2 * slow;
    mouse.x += (mouse.tx - mouse.x) * 0.08;
    mouse.y += (mouse.ty - mouse.y) * 0.08;
    mouse.k += (mouse.tk - mouse.k) * 0.06;
    gl.uniform2f(U.r, w, h);
    gl.uniform1f(U.t, t);
    gl.uniform3f(U.m, mouse.x, mouse.y, mouse.k);
    gl.uniform3f(U.c1, c1[0], c1[1], c1[2]);
    gl.uniform3f(U.c2, c2[0], c2[1], c2[2]);
    gl.uniform3f(U.bg, bg[0], bg[1], bg[2]);
    gl.uniform1f(U.orb, o.orb ? 1 : 0);
    gl.uniform1f(U.light, o.light ? 1 : 0);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  };
  raf = requestAnimationFrame(frame);

  return {
    stop() {
      alive = false;
      cancelAnimationFrame(raf);
      ro && ro.disconnect();
      io && io.disconnect();
      const lose = gl.getExtension("WEBGL_lose_context");
      lose && lose.loseContext();
    },
    setSpeed(s) { speed = s; },
    setTints(a, b) { c1 = rgb01(a); c2 = rgb01(b); },
    setMouse(x, y, k) {
      const rect = canvas.getBoundingClientRect();
      const sx = w / Math.max(1, rect.width), sy = h / Math.max(1, rect.height);
      mouse.tx = x * sx; mouse.ty = h - y * sy; mouse.tk = k;
    },
  };
}
