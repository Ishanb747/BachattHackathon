"""Plugging the voice layer into another project: your prompt, your greeting,
a per-turn hook, and a tool.

The hook sees every transcript before the model does. Here it answers
opening-hours questions with a fixed line (cached after the first time, so it
plays in ~0 ms, and the model is never asked), and adds the caller's account
context to every other turn. The tool lets the model look up a booking; its
result goes back to the model, which then speaks it.

    python examples/custom_hook.py      # http://127.0.0.1:8001
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from cascadevoice import BrowserTransport, Tool, TurnPlan, VoiceSession

PROMPT = """You are Mira, the host at Lantern, a small restaurant, answering the phone.
Be warm and brief. You can look up existing bookings with the find_booking tool."""

HOURS = "We're open every day from noon to eleven at night, and the kitchen closes at ten thirty."


class LanternHook:
    """Fixed answers for fixed questions; context for everything else."""

    async def before_reply(self, transcript, *, language, history):
        if re.search(r"\b(open|close|closing|hours)\b", transcript, re.I):
            return TurnPlan(reply=HOURS)
        if re.search(r"\b(bye|goodbye|that's all)\b", transcript, re.I):
            return TurnPlan(reply="Thanks for calling Lantern — see you soon!", end_call=True)
        return TurnPlan(instructions="The caller's number matches a regular guest named Sam.")


BOOKINGS = {"L-1042": {"name": "Sam", "party": 4, "time": "7:30 pm Friday"}}

find_booking = Tool(
    name="find_booking",
    description="Find a booking by its reference, like L-1042.",
    parameters={"type": "object", "properties": {"reference": {"type": "string"}}, "required": ["reference"]},
    fn=lambda args: BOOKINGS.get(args.get("reference", "").upper().replace(" ", ""), {"error": "not found"}),
)

app = FastAPI()


@app.get("/")
async def index():
    return FileResponse(Path(__file__).resolve().parents[1] / "web" / "index.html")


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    session = VoiceSession(
        BrowserTransport(websocket),
        system_prompt=PROMPT,
        greeting="Hello, Lantern, this is Mira — how can I help?",
        hook=LanternHook(),
        tools=[find_booking],
    )
    await session.start()
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes"):
                await session.feed_pcm(message["bytes"])
            elif message.get("text"):
                data = json.loads(message["text"])
                if data.get("type") == "user_text":
                    await session.submit_text(data.get("text", ""))
                elif data.get("type") == "interrupt":
                    await session.interrupt()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await session.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8001)
