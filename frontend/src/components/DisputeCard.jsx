import React, { useState } from "react";
import { Card, Button, Icon, Modal } from "../atom";
import { SectionHead } from "./Panels.jsx";

export function mailtoHref(d) {
  const to = d.to && d.to.includes("@") ? d.to.trim() : "";
  return `mailto:${encodeURIComponent(to)}?subject=${encodeURIComponent(d.subject || "")}&body=${encodeURIComponent(d.body || "")}`;
}

function DisputeBody({ draft, onShow }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    const text = `Subject: ${draft.subject}\n\n${draft.body}`;
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000); }
    catch { setCopied(false); }
  };
  return (
    <div className="pd-dispute">
      <div className="pd-dispute__subject">{draft.subject}</div>
      {draft.to && <div className="pd-dispute__to"><span className="pd-dim">To</span> {draft.to}</div>}
      <div className="pd-dispute__body">{draft.body}</div>
      <div className="pd-dispute__actions">
        <Button variant="primary" size="sm" onClick={copy}><Icon name={copied ? "check" : "mail"} size={14} /> {copied ? "Copied" : "Copy email"}</Button>
        <a className="at-btn at-btn--ghost at-btn--sm pd-dispute__mailto" href={mailtoHref(draft)}><Icon name="send" size={14} /> Open in mail app</a>
        {onShow && draft.source_ids && draft.source_ids.length > 0 && (
          <button type="button" className="pd-source-link" onClick={() => onShow(draft.source_ids)}>
            <Icon name="eye" size={13} /> {draft.source_ids.length} source{draft.source_ids.length === 1 ? "" : "s"}
          </button>
        )}
      </div>
    </div>
  );
}

export default function DisputeCard({ disputes, onShow }) {
  if (!disputes || !disputes.length) return null;
  return (
    <section>
      <SectionHead icon="mail" title="Refund request drafted"
        right={<span className="pd-dim pd-xs">{disputes.length > 1 ? `${disputes.length} likely double charges` : "likely double charge"}</span>} />
      <div className="pd-stack">
        {disputes.map((d, i) => (
          <Card key={`${d.subject}-${i}`} className="pd-dispute-card pd-pop" style={{ "--i": i }}>
            <DisputeBody draft={d} onShow={onShow} />
          </Card>
        ))}
      </div>
    </section>
  );
}

export function DisputeModal({ draft, onClose, onShow }) {
  return (
    <Modal open={!!draft} onClose={onClose} title="Refund request drafted"
      actions={<Button variant="ghost" size="sm" onClick={onClose}>Close</Button>}>
      {draft && <DisputeBody draft={draft} onShow={onShow ? (ids) => { onClose(); onShow(ids); } : null} />}
    </Modal>
  );
}

export function WebLookup({ data, onClose }) {
  if (!data) return null;
  return (
    <Card className="pd-web">
      <div className="pd-row pd-row--between">
        <span className="at-label pd-row"><Icon name="search" size={14} /> Looked up online</span>
        {onClose && <button type="button" className="pd-icon-btn" onClick={onClose} aria-label="Dismiss"><Icon name="x" size={14} /></button>}
      </div>
      {data.query && <div className="pd-web__q">“{data.query}”</div>}
      {data.answer && <p className="pd-web__a">{data.answer}</p>}
      {data.sources && data.sources.length > 0 && (
        <div className="pd-web__src">
          {data.sources.map((s) => <span key={s} className="pd-web__chip">{s}</span>)}
        </div>
      )}
    </Card>
  );
}
