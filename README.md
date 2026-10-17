# cascadevoice

A full-duplex voice layer, distilled from the Vaani cascade: one fixed pipeline, browser only.

```
mic (16 kHz PCM, 20 ms) → Silero VAD → ElevenLabs Scribe realtime (batch Scribe fallback)
   → [your hook] → OpenAI gpt-4o, streamed → sentence chunks → ElevenLabs Flash TTS, streamed → browser
```

The mic is listened to while the agent speaks. An onset over the agent is only an interruption once it earns it:
450 ms of sustained speech, or a transcript that reads as a real answer (on the question's tail) or a real
interruption. Backchannels ("hmm", "haan") and noise leave the agent talking. On a real barge-in the model stream,
synthesis and queued audio are cancelled, the browser fades out, and the history keeps only the sentences the user
actually heard (playout clock). Tuned values live in `cascadevoice/defaults.py` with the reasons for each.

## Run

```
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python server.py          # http://127.0.0.1:8000
.venv/bin/python -m pytest          # offline, no keys
.venv/bin/python scripts/latency_harness.py --calls 1 10 50   # stub vendors: what the pipeline adds
```

Keys: `.env` at the project root (gitignored) with `OPENAI_API_KEY` and `ELEVENLABS_API_KEY` (see `.env.example`).
The server refuses to start, naming the key, if either is missing. The Silero model is loaded from
`models/silero_vad.onnx` (downloaded there on first use if absent; webrtcvad is the fallback).

## Plug it into your project

```python
session = VoiceSession(BrowserTransport(ws), system_prompt="You are …", greeting="Hi …",
                       hook=MyHook(), tools=[Tool("find_order", "…", schema, fn)])
await session.start(); await session.feed_pcm(pcm); await session.submit_text("typed turn")
```

A hook's `async before_reply(transcript, *, language, history)` returns `None` (the model answers),
`TurnPlan(reply="fixed line")` (no model call; cached), `TurnPlan(instructions="context for this turn")`, and/or
`end_call=True`. The model can also hang up via its built-in `end_call` tool. See `examples/custom_hook.py`.

Left out (still in the original repo): SOP/flows, CRM tools, telephony, call logs, scoring, Langfuse, accounts, fillers.
