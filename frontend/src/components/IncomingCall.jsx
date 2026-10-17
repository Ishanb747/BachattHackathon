import React, { useEffect } from "react";
import { Modal, AiOrb, Button, Icon, Badge } from "../atom";
import RupeeOrb from "./RupeeOrb";
import { inr, fmtDate } from "../lib/format.js";

// Soft two-tone ring via WebAudio; returns stop(). Closed before the call's own
// AudioContext is created.
function startRing() {
  let ctx;
  try { ctx = new AudioContext(); } catch { return () => {}; }
  const out = ctx.createGain(); out.gain.value = 0.05; out.connect(ctx.destination);
  let alive = true;
  const burst = (t0) => {
    [0, 0.42].forEach((off) => {
      [660, 880].forEach((f) => {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.frequency.value = f; o.type = "sine";
        g.gain.setValueAtTime(0, t0 + off);
        g.gain.linearRampToValueAtTime(1, t0 + off + 0.03);
        g.gain.setValueAtTime(1, t0 + off + 0.3);
        g.gain.linearRampToValueAtTime(0, t0 + off + 0.36);
        o.connect(g); g.connect(out);
        o.start(t0 + off); o.stop(t0 + off + 0.4);
      });
    });
  };
  const loop = () => { if (!alive) return; burst(ctx.currentTime + 0.05); };
  loop();
  const iv = setInterval(loop, 2600);
  return () => { alive = false; clearInterval(iv); try { ctx.close(); } catch {} };
}

export default function IncomingCall({ data, onAccept, onDecline }) {
  const open = !!data;
  useEffect(() => {
    if (!open) return;
    const stop = startRing();
    return stop;
  }, [open]);

  const due = data && data.due;
  const bal = data && data.balance;
  return (
    <Modal open={open} onClose={onDecline}>
      {open && (
        <div className="pd-call">
          <div className="pd-call__ring">
            <span className="pd-call__wave" style={{ "--d": "0s" }} />
            <span className="pd-call__wave" style={{ "--d": "0.8s" }} />
            <span className="pd-call__wave" style={{ "--d": "1.6s" }} />
            <RupeeOrb state="listening" size={120} />
          </div>
          <div className="at-label pd-call__label"><span className="pd-pulse-dot" /> Incoming call</div>
          <h2 className="pd-call__name">Paisa Dost</h2>
          <p className="pd-dim pd-sm pd-call__sub">Payment alert {data.simulated && <Badge tone="ochre" dot>simulated</Badge>}</p>

          {due && (
            <div className="pd-call__info">
              <div className="pd-row pd-row--between">
                <span className="pd-call__due-title">{due.title}</span>
                <Badge tone="madder" dot>due {fmtDate(due.due_date, { year: false })}</Badge>
              </div>
              <div className="pd-call__amt">{inr(due.amount)}</div>
              <div className="pd-dim pd-xs">{due.account_ref} · {due.source_label}</div>
              {bal && (
                <div className="pd-call__bal">
                  <span className="pd-dim pd-xs">Balance {bal.account_ref}</span>
                  <b>{inr(bal.amount)}</b>
                  <span className="pd-dim pd-xs">{bal.source_label || (bal.source_ids || []).join(", ")}</span>
                </div>
              )}
            </div>
          )}
          {data.reason && <p className="pd-xs pd-dim pd-call__reason">{data.reason}</p>}

          <div className="pd-call__actions">
            <div className="pd-call__action">
              <Button variant="danger" size="lg" className="pd-call__btn" onClick={onDecline} aria-label="Decline">
                <Icon name="x" size={22} />
              </Button>
              <span className="pd-xs pd-dim">Decline</span>
            </div>
            <div className="pd-call__action">
              <Button variant="primary" size="lg" className="pd-call__btn pd-call__btn--accept" onClick={onAccept} aria-label="Accept">
                <Icon name="phone" size={22} />
              </Button>
              <span className="pd-xs pd-dim">Accept</span>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
