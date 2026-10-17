import React, { useEffect, useRef } from "react";
import { Dots } from "../atom";

export default function Transcript({ items, status }) {
  const boxRef = useRef(null);
  useEffect(() => {
    const box = boxRef.current;
    if (box) box.scrollTo({ top: box.scrollHeight, behavior: "smooth" });
  }, [items, status]);
  const thinking = status === "thinking" || status === "transcribing";
  return (
    <div className="pd-transcript" ref={boxRef} aria-live="polite">
      {!items.length && (
        <div className="pd-transcript__empty">
          <p>Start a call and speak in Hindi, Hinglish or English.</p>
          <p className="pd-dim pd-xs">Try “Balance kitna hai?”, “Agar 20 hazaar prepay karun?” or “Reminder laga do”.</p>
        </div>
      )}
      {items.map((m) =>
        m.role === "note" ? (
          <div key={m.id} className={`pd-note${m.error ? " pd-note--error" : ""}`}>{m.text}</div>
        ) : (
          <div key={m.id} className={`pd-bubble pd-bubble--${m.role}`}>
            <span className="pd-bubble__who">{m.role === "user" ? "You" : "Paisa Dost"}</span>
            {m.text}
          </div>
        )
      )}
      {thinking && (
        <div className="pd-bubble pd-bubble--agent pd-bubble--typing">
          <Dots />
        </div>
      )}
    </div>
  );
}
