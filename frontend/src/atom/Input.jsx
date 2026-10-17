import React, { useId } from "react";

/** Field — label + control + help text */
export function Field({ label, help, error, children }) {
  return (
    <div className="at-field">
      {label && <span className="at-label">{label}</span>}
      {children}
      {(error || help) && (
        <span className={error ? "at-help at-help--error" : "at-help"}>{error || help}</span>
      )}
    </div>
  );
}

export function Input({ error = false, className = "", ...rest }) {
  const cls = ["at-input", error && "at-input--error", className].filter(Boolean).join(" ");
  return <input className={cls} {...rest} />;
}

export function Textarea({ className = "", ...rest }) {
  return <textarea className={["at-textarea", className].filter(Boolean).join(" ")} {...rest} />;
}

export function Switch({ className = "", ...rest }) {
  return (
    <label className={["at-switch", className].filter(Boolean).join(" ")}>
      <input type="checkbox" {...rest} />
      <span className="at-switch__track" />
    </label>
  );
}

export function Checkbox({ label, className = "", ...rest }) {
  const id = useId();
  return (
    <label className={["at-check", className].filter(Boolean).join(" ")} htmlFor={id}>
      <input id={id} type="checkbox" {...rest} /> {label}
    </label>
  );
}

export function Radio({ label, className = "", ...rest }) {
  const id = useId();
  return (
    <label className={["at-check", className].filter(Boolean).join(" ")} htmlFor={id}>
      <input id={id} type="radio" {...rest} /> {label}
    </label>
  );
}
