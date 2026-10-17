import React, { useState } from "react";
import { AiOrb, Button, Card, Field, Input, Icon, Badge } from "../atom";
import RupeeOrb from "./RupeeOrb";
import { post } from "../lib/api.js";

export default function Login({ onLogin, mock }) {
  const [email, setEmail] = useState(mock ? "lokesh.m993@gmail.com" : "");
  const [password, setPassword] = useState(mock ? "demo" : "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      const r = await post("/api/login", { email: email.trim(), password });
      onLogin(r.user);
    } catch (err) {
      setError(err.status === 401 || err.name === "AuthError" ? (err.message && err.message !== "Not signed in" ? err.message : "Wrong email or password") : err.message || "Sign-in failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="pd-login">
      <div className="pd-login__hero pd-reveal" style={{ "--i": 0 }}>
        <RupeeOrb state={busy ? "thinking" : "idle"} size={190} />
        <h1 className="at-h1 pd-login__title">
          Paisa Dost, <span className="at-serif-accent">aapki awaaz mein.</span>
        </h1>
        <p className="at-muted pd-login__sub">
          Ask about your money in Hindi, Hinglish or English. Every number comes with its source.
        </p>
      </div>
      <Card className="pd-login__card pd-reveal" style={{ "--i": 1 }}>
        <form onSubmit={submit} className="pd-login__form">
          <div className="pd-row pd-row--between">
            <span className="at-label">Sign in</span>
            {mock && <Badge tone="ochre" dot>Mock data</Badge>}
          </div>
          <Field label="Email">
            <Input type="email" autoComplete="username" placeholder="you@example.com" value={email}
              onChange={(e) => setEmail(e.target.value)} required />
          </Field>
          <Field label="Password" error={error || undefined}>
            <Input type="password" autoComplete="current-password" placeholder="Demo password" value={password}
              onChange={(e) => setPassword(e.target.value)} error={!!error} required />
          </Field>
          <Button variant="primary" size="lg" type="submit" busy={busy} disabled={busy} style={{ width: "100%" }}>
            <Icon name="lock" size={17} /> {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
