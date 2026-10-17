const inrFmt2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const inrFmt0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

/** ₹ amount in Indian grouping; paise only when present. */
export function inr(n) {
  if (n == null || n === "" || isNaN(Number(n))) return String(n ?? "");
  const v = Number(n);
  const s = Number.isInteger(v) ? inrFmt0.format(v) : inrFmt2.format(v);
  return `₹${s}`;
}

export function inrShort(n) {
  const v = Number(n);
  if (!isFinite(v)) return String(n);
  if (Math.abs(v) >= 1e5) return `₹${(v / 1e5).toFixed(v >= 1e6 ? 1 : 2).replace(/\.0+$/, "")}L`;
  if (Math.abs(v) >= 1e3) return `₹${(v / 1e3).toFixed(1).replace(/\.0$/, "")}k`;
  return inr(Math.round(v));
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-10-10" → "10 Oct 2026"; datetime → "22 Sep, 09:14". */
export function fmtDate(s, { year = true } = {}) {
  if (!s) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(s);
  if (!m) return s;
  const [, y, mo, d, hh, mm] = m;
  const base = `${Number(d)} ${MONTHS[Number(mo) - 1]}`;
  if (hh) return `${base}${year ? " " + y : ""}, ${hh}:${mm}`;
  return year ? `${base} ${y}` : base;
}

/** Days from as_of (or today) to a YYYY-MM-DD date. */
export function daysUntil(date, asOf) {
  const a = asOf ? new Date(asOf.slice(0, 10) + "T00:00:00") : new Date(new Date().toDateString());
  const b = new Date(date.slice(0, 10) + "T00:00:00");
  return Math.round((b - a) / 86400000);
}

export function pct(v) {
  const n = Number(v);
  if (!isFinite(n)) return String(v);
  return `${Math.round(n <= 1.0001 && n >= -1 ? n * 100 : n)}%`;
}

export const initials = (name = "") =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("") || "PD";
