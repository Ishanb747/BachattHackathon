"""Demo server: the browser voice console.

    python server.py            # http://127.0.0.1:8000

``GET /`` serves web/index.html; ``/ws`` is one call.
  client → server: binary = PCM-16 16 kHz mono, 20 ms (640-byte) frames, sent
                   continuously (also while the agent speaks — that is barge-in);
                   text = {"type": "user_text", "text"} | {"type": "interrupt"}
  server → client: the events in cascadevoice.events; binary = PCM-16 agent
                   audio between audio_begin (carrying the rate) and audio_end.

Keys come from .env (OPENAI_API_KEY, ELEVENLABS_API_KEY); the server refuses
to start without them. No auth — this is a local demo: anyone who can reach
the port spends your quota.
"""

from __future__ import annotations

import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from cascadevoice import BrowserTransport, VoiceSession
from cascadevoice.audio.vad_engines import get_silero_session
from cascadevoice.defaults import MissingKeyError, load_keys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for noisy in ("httpx", "websockets", "openai"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
logger = logging.getLogger("server")

WEB = Path(__file__).parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        load_keys()
    except MissingKeyError as exc:
        logger.error(str(exc))
        sys.exit(1)
    get_silero_session()   # load (or fetch once) the VAD model before the first call
    yield


app = FastAPI(title="cascadevoice demo", lifespan=lifespan)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.websocket("/ws")
async def call(websocket: WebSocket) -> None:
    await websocket.accept()
    session = VoiceSession(BrowserTransport(websocket))
    await session.start()
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes"):
                await session.feed_pcm(message["bytes"])
            elif message.get("text"):
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "user_text":
                    await session.submit_text(data.get("text", ""))
                elif data.get("type") == "interrupt":
                    await session.interrupt()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await session.close(reason="browser_closed")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
