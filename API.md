# Paisa Dost — API contract (backend ⇄ frontend)

Served by `server.py` (FastAPI) on `http://127.0.0.1:8000`. The built frontend (`frontend/dist`) is served at `/`.
In dev, Vite runs on `:5173` and proxies `/api` and `/ws` to `:8000`.
Auth is a signed session cookie. Every `/api/*` route except `/api/login` returns 401 without it.

Money is a number in rupees. Dates are `YYYY-MM-DD`. Datetimes are ISO in IST.

## Common shapes

```ts
type Source = { id: string; kind: "sms" | "email" | "csv"; at: string; sender: string; text: string; label: string }
type Fact   = { text_key: string; value: number | string; source_ids: string[]; source_label: string }
type Insight = { id: string; title: string; detail: string; impact_inr: number; kind: string; source_ids: string[]; source_label: string }
type Reminder = { id: string; title: string; date: string; due_id?: string; created_at: string; source_ids: string[] }
type Due = { id: string; title: string; amount: number; due_date: string; kind: string; account_ref: string; status: string; source_ids: string[]; source_label: string }
```

## REST

| Method / path | Request | Response |
|---|---|---|
| `POST /api/login` | `{email, password}` | `200 {user: {id, name, email}}` and sets the cookie; `401 {error}` |
| `POST /api/logout` | none | `200 {}` |
| `GET /api/me` | none | `{user: {id, name, email}}` or 401 |
| `GET /api/dashboard` | none | `{ as_of, health: {score, grade, parts: [{name, score, max, source_ids}]}, insights: Insight[] (top 3, ranked by ₹ impact), dues: Due[] (upcoming, by date), balances: [{account_ref, amount, at, source_ids, source_label}], reminders: Reminder[] }` |
| `GET /api/sources?ids=a,b,c` | none | `{sources: Source[]}` (feeds the evidence panel) |
| `GET /api/graph` | none | `{nodes: [{id, type, label, props}], links: [{source, target, rel}]}`. Node types: User, Account, Card, Merchant, Txn, Due, Policy, SIP, Source, Insight, Reminder |
| `GET /api/reminders` | none | `{reminders: Reminder[]}` |
| `POST /api/check-deadlines` | none | `{fire: boolean, due?: Due, balance?: {account_ref, amount, source_ids}, reason: string}`. When `fire` is true, the UI shows the incoming-call screen. Accepting opens `/ws?mode=outgoing&due_id=<id>` |

## WebSocket `/ws` (or `/ws?mode=outgoing&due_id=...`)

The voice protocol is the same as `web/index.html` today:

* **Client → server:**
  * binary 20 ms PCM-16 mono 16 kHz frames
  * `{"type":"user_text","text":...}`
  * `{"type":"interrupt"}`
* **Server → client (existing):**
  * `connected`
  * `status{status: idle|listening|transcribing|thinking|speaking}`
  * `transcript{role: user|agent, text}`
  * `turn_complete`
  * `metrics`
  * `audio_begin{sample_rate}`, then binary PCM-16 chunks, then `audio_end`
  * `control{action: stop_playback|hangup, fade_ms}`
  * `error`
* **Server → client (new):**
  * `{"type":"evidence","source_ids":[...],"text_key":...}`: glow these rows and graph nodes while the agent speaks the fact.
  * `{"type":"reminder","reminder": Reminder}`: add a reminder card (sent after the user confirmed by voice).
  * `{"type":"insights","insights": Insight[]}`: sent after the session-start `get_insights` call.
  * `{"type":"whatif","result": {...}}`: the paydown result card for "what if I prepay 20k".
