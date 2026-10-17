import React, { useEffect } from "react";

/** Modal — controlled: open, onClose. Escape and backdrop click close it. */
export function Modal({ open, onClose, title, actions, children }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => e.key === "Escape" && onClose && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="at-modal-backdrop" onClick={(e) => e.target === e.currentTarget && onClose && onClose()}>
      <div className="at-modal" role="dialog" aria-modal="true">
        {title && <h3 className="at-modal__title">{title}</h3>}
        <div className="at-modal__body">{children}</div>
        {actions && <div className="at-modal__actions">{actions}</div>}
      </div>
    </div>
  );
}

/** Toast — tone: "success" | "error" | "info" */
export function Toast({ tone = "info", className = "", children, ...rest }) {
  const cls = ["at-toast", `at-toast--${tone}`, className].filter(Boolean).join(" ");
  return (
    <div className={cls} role="status" {...rest}>
      <span className="at-toast__icon" />
      {children}
    </div>
  );
}

/** Tooltip — wraps its child; label shows above on hover/focus */
export function Tooltip({ label, children }) {
  return (
    <span className="at-tooltip" tabIndex={0}>
      {children}
      <span className="at-tooltip__bubble" role="tooltip">{label}</span>
    </span>
  );
}

export function Spinner(props) { return <div className="at-spinner" role="status" aria-label="Loading" {...props} />; }

export function Dots(props) {
  return (
    <div className="at-dots" role="status" aria-label="Loading" {...props}>
      <span /><span /><span />
    </div>
  );
}

/** Progress — value: 0–100 */
export function Progress({ value = 0, className = "", ...rest }) {
  return (
    <div className={["at-progress", className].filter(Boolean).join(" ")}
      role="progressbar" aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100} {...rest}>
      <div className="at-progress__bar" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}
