# Paisa Dost — plan

## The voice agent we already have (`cascadevoice/`, `server.py`)

* **Entry point:** `server.py` (FastAPI) serves `web/index.html` and opens one `VoiceSession` per `/ws` socket.
* **Pipeline:** mic PCM 16 kHz → Silero VAD → STT → OpenAI `gpt-4o`, streamed (`llm.py`) → sentence chunks → ElevenLabs Flash TTS, streamed (`elevenlabs.py`) → browser.
* **STT:** `STT_PROVIDER` in `defaults.py`. It is currently `"openai"` (`gpt-transcribe`, batch). `"scribe"` is ElevenLabs realtime.
* **Barge-in:** already built. It cancels the LLM, TTS and queued audio, and keeps only the heard part in history (done-check 3 is mostly free).
* **Extension points:**
  * `VoiceSession(transport, system_prompt, greeting, hook, tools=[Tool(name, desc, schema, fn)])`
  * `hook.before_reply()` can force a fixed reply, add instructions, or end the call.
  * The model has an `end_call` tool built in.
* **Missing vs context.md:** finance data, every finance tool, the citation rule, outgoing calls, the dashboard UI, auth and per-user storage.

## What we reuse

* The whole of `cascadevoice/`, unchanged except `defaults.py` (prompt, STT provider) and `Tool` registration.
* `server.py`: same app, plus new routes.
* The Safari audio fixes in `web/index.html`, ported into the new frontend's audio module.

## What we add, file by file

```
paisadost/                      # new package, plain Python, all math lives here
  sources.py      readers per file; regex parsers for SMS/email (bank debit, Avl Bal, card stmt, due notices)
  loader.py       P1  -> Txn/Due/Balance/Card lists, deduped across SMS/email/statement, source_ids kept
  graph.py        SQLite property graph (nodes/edges), build from loader output, neighbourhood queries
  patterns.py     P2  category spend, spend vs usual, recurring, dues vs balance, card utilisation, duplicates
  recommend.py    P3  ranked one-liners by ₹ impact, health_score(/100), card_paydown_plan(cards, cash)
  facts.py        Fact(text_key, value, source_ids, source_label) + rupee/date formatting for speech
  tools.py        P4  get_insights, answer_question(q), what_if_prepay(amount), set_reminder(title, date)
  agent.py        builds VoiceSession: system prompt, tools, greeting; outgoing-call variant (P6)
  auth.py         basic auth (below)
server.py         + /api/login, /api/me, /api/dashboard, /api/graph, /api/reminders, /api/check-deadlines; /ws gets the user
frontend/         Vite + React, AtomUI (emerald), see UI below; built to frontend/dist, served by server.py
tests/test_paisadost_*.py   done-checks 1, 2, 4, 5, 6, 7 as pytest on the real data
README.md         setup, .env keys, run commands
```

## Rules carried into the code

* **No LLM math:** the LLM never does arithmetic. Every number reaches it as a `Fact` from a tool. The system prompt says: only numbers from tools, cite the source label, max 2 short sentences, no lists, confirm before `set_reminder`, call `get_insights` at session start.
* **Parsing:** regex first. The LLM (`gpt-4o-mini`) only labels leftover finance SMS that no regex matches, and its result is cached to disk.
* **Dedupe:** `(amount, date ±1 day, fuzzy merchant)` across SMS, email and statements. The merged fact keeps every `source_id` (done-check 6).

## UI: AtomUI, emerald pigment (green), via the AtomUI MCP

**Layout:** `AtProvider pigment="emerald"` on a light frosted-glass ground. I pull components from the MCP (`get_component`) into `frontend/src/atom/`. This replaces "Tailwind + shadcn" from context.md: AtomUI forbids both, and you picked AtomUI.

**Left column:**
* `AiOrb` is the call orb. Its state follows the session: idle, listening (user speaking), thinking (LLM/TTS busy).
* A primary `Button` "Check deadlines" opens a fake incoming-call `Modal` (accept/decline), which starts the outgoing session.
* A live transcript (`Timeline`) is always shown as the text fallback for Hindi STT errors, plus a type-a-message `Input`.

**Right column:**
* Health score ring: a `Stat` with smoke and a hand-built SVG ring.
* Top 3 insights (`Card` + `Badge` for ₹ impact).
* Reminder cards that slide in after a voice confirm.
* Evidence panel: the source rows (SMS/email text), which glow when their `source_id` is cited.

**Graph view** (a tab next to the evidence panel):
* Force-directed graph of the user's money graph: User → accounts/cards → dues/txns → sources.
* Layout uses `d3-force` (physics only); the drawing is hand-built SVG in AtomUI style, since AtomUI bans external UI kits.
* Cited `source_ids` and their paths light up in emerald as the agent speaks. You can click a node to see its source row.

**Motion:**
* A custom circular cursor: a small dot plus a lagging ring on a spring. The ring grows and snaps (magnetic) over buttons and cards, shrinks on press, and hides over inputs. It's hand-built with `requestAnimationFrame` and turns off on touch devices and with `prefers-reduced-motion`.
* On load: a staggered fade-up of panels, and the health ring counts up.
* Cards tilt slightly toward the cursor. The orb and the primary button are already cursor-reactive (AtomUI smoke).

**Basic auth:**
* Login screen: email + password. Users are the 24 in `users_data.csv`, and the password is one shared `DEMO_PASSWORD` from `.env`.
* A signed session cookie (Starlette `SessionMiddleware`, `SESSION_SECRET` in `.env`) protects `/api/*` and `/ws`. The session picks which user's graph and data the agent sees.
* No sign-up, no roles, no OAuth.

## Phases (after "go", one at a time, each shown on real data)

| Phase | Work | Output shown |
|---|---|---|
| P1 | Loader, dedupe, graph build | counts per type, 10 sample Txns/Dues for Lokesh, a merged duplicate with 2 source ids |
| P2 | Patterns | each pattern's output for Lokesh |
| P3 | Recommendations, health score, `card_paydown_plan` | ranked list, score, plan for a ₹20k what-if |
| P4 | Tools + prompt wired into the agent | tool outputs, plus a text-mode session answering "Balance kitna hai?" |
| P5 | Frontend (AtomUI, cursor, graph, auth) | running app at `/`, screenshots |
| P6 | Outgoing call | trigger fires / does not fire on the rule, agent speaks first with the source |

If we run behind: drop call-screen polish, then graph animations, then the health score. We never drop the evidence trail or the recommendation.

## Open questions (my default in brackets)

1. **Encrypted PDFs (Experian credit reports, card and bank statements).** The dataset README says to open these with the password hinted in the email, built from the user's PAN, DOB and mobile. My permission layer blocked me from doing that. Without them, card limits come from SMS "Avl Lmt" and dues come from statement alerts. There is **no APR and no full credit report**. [Ask you to allow `pdftotext -upw` on `buildathon/emails/attachments`. Otherwise use SMS and email only, and take APR from the loan data or the card issuer's published rate with that label.]
2. **STT.** context.md says ElevenLabs. We're on OpenAI `gpt-transcribe` now. [Switch back to ElevenLabs Scribe realtime for Hindi/Hinglish, and keep `gpt-transcribe` as the fallback.]
3. **"Today".** The data ends 16 Oct. Due-within-2-days needs a fixed as-of date. [`AS_OF=2026-10-16` in `.env`. For P6 I pick a real due that meets the rule, and a demo toggle can move as-of.]
4. **Repo.** `buildathon/` is 4.1 GB. [Keep it gitignored. The loader reads it in place, and per-user graph databases go in `data/` (also gitignored).]
