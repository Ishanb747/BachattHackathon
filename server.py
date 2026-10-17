"""Credit Dost server: REST for the dashboard + /ws voice call.

    python server.py            # http://127.0.0.1:8000

Keys in .env: OPENAI_API_KEY, ELEVENLABS_API_KEY, DEMO_PASSWORD, SESSION_SECRET.
API contract: API.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from cascadevoice import BrowserTransport, VoiceSession
from cascadevoice.audio.vad_engines import get_silero_session
from cascadevoice.defaults import MissingKeyError, load_keys
from paisadost import auth
from paisadost.config import DEMO_USER
from paisadost.tools import SYSTEM_PROMPT, Dost, greeting, outgoing_greeting

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for noisy in ("httpx", "websockets", "openai"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
logger = logging.getLogger("server")

ROOT = Path(__file__).parent
DIST = ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        load_keys()
    except MissingKeyError as exc:
        logger.error(str(exc))
        sys.exit(1)
    get_silero_session()
    for uid, _ in PERSONAS:                             # warm every persona's ledger
        await asyncio.to_thread(Dost.for_user, uid)
    yield


app = FastAPI(title="Credit Dost", lifespan=lifespan)


def _user(request) -> str | None:
    return auth.verify(request.cookies.get(auth.COOKIE))


def _deny():
    return JSONResponse({"error": "not signed in"}, status_code=401)


@app.post("/api/login")
async def login(request: Request):
    body = await request.json()
    user = auth.check(body.get("email", ""), body.get("password", ""))
    if not user:
        return JSONResponse({"error": "Wrong email or password"}, status_code=401)
    await asyncio.to_thread(Dost.for_user, user["id"])
    resp = JSONResponse({"user": user})
    resp.set_cookie(auth.COOKIE, auth.sign(user["id"]), httponly=True, samesite="lax", max_age=auth.MAX_AGE)
    return resp


@app.post("/api/logout")
async def logout():
    resp = JSONResponse({})
    resp.delete_cookie(auth.COOKIE)
    return resp


@app.get("/api/me")
async def me(request: Request):
    uid = _user(request)
    return {"user": auth.user_by_id(uid)} if uid else _deny()


# Demo personas: real users from the dataset, each showing a different case.
PERSONAS = [
    ("1749913629362473", "Overdue bills, 7 cards"),
    ("1747824302191779", "Stressed, overdue EMIs"),
    ("1748108541385190", "Many subscriptions"),
    ("1750426955233987", "Healthy saver"),
    ("1750577443897920", "SIP investor, Jio double charge"),
    ("1750389254784005", "Near-zero balance"),
    ("1750471929369018", "Many credit checks"),
]


@app.get("/api/demo-users")
async def demo_users(request: Request):
    if not _user(request):
        return _deny()
    out = []
    for uid, tag in PERSONAS:
        u = auth.user_by_id(uid)
        if u:
            out.append({**u, "tag": tag})
    return {"users": out}


@app.post("/api/switch-user")
async def switch_user(request: Request):
    if not _user(request):
        return _deny()
    uid = (await request.json()).get("user_id", "")
    if uid not in {p[0] for p in PERSONAS}:
        return JSONResponse({"error": "not a demo persona"}, status_code=400)
    await asyncio.to_thread(Dost.for_user, uid)
    resp = JSONResponse({"user": auth.user_by_id(uid)})
    resp.set_cookie(auth.COOKIE, auth.sign(uid), httponly=True, samesite="lax", max_age=auth.MAX_AGE)
    return resp


@app.get("/api/dashboard")
async def dashboard(request: Request):
    uid = _user(request)
    if not uid:
        return _deny()
    d = await asyncio.to_thread(Dost.for_user, uid)
    return {"as_of": d.L.as_of.isoformat(), "health": d.health(), "insights": d.insights()[:3],
            "dues": d.upcoming_dues(), "balances": d.balances(), "reminders": d.reminders()}


@app.get("/api/insights")
async def all_insights(request: Request):
    uid = _user(request)
    return {"insights": Dost.for_user(uid).insights()} if uid else _deny()


@app.get("/api/forecast")
async def forecast_route(request: Request):
    uid = _user(request)
    if not uid:
        return _deny()
    from paisadost import patterns
    return patterns.forecast(Dost.for_user(uid).L)


@app.get("/api/cashflow")
async def cashflow_route(request: Request):
    uid = _user(request)
    if not uid:
        return _deny()
    from paisadost import patterns
    return patterns.cashflow(Dost.for_user(uid).L)


@app.get("/api/income-months")
async def income_months_route(request: Request):
    uid = _user(request)
    if not uid:
        return _deny()
    from paisadost import patterns
    return {"months": patterns.income_by_month(Dost.for_user(uid).L)}


@app.get("/api/coach")
async def coach_route(request: Request):
    uid = _user(request)
    if not uid:
        return _deny()
    from paisadost import recommend
    d = Dost.for_user(uid)
    return recommend.score_coach(d.L, d.P)


@app.get("/api/disputes")
async def disputes_route(request: Request):
    uid = _user(request)
    if not uid:
        return _deny()
    from paisadost import recommend
    d = Dost.for_user(uid)
    return {"disputes": [recommend.dispute_draft(d.L, x) for x in d.P["duplicates"][:5]]}


@app.get("/api/documents")
async def documents_list(request: Request):
    uid = _user(request)
    if not uid:
        return _deny()
    from paisadost import documents
    docs = documents.list_docs(uid)
    return {"documents": [{k: v for k, v in d.items() if k != "facts"} | {"facts": [{"label": f["label"], "value": f["value"]} for f in d["facts"]]} for d in docs]}


@app.post("/api/documents")
async def documents_upload(request: Request, file: UploadFile = File(...), password: str = Form("")):
    uid = _user(request)
    if not uid:
        return _deny()
    from paisadost import documents
    d = Dost.for_user(uid)
    data = await file.read()
    try:
        result = await asyncio.to_thread(documents.ingest, d, data, file.filename or "document", password or None)
    except documents.DocError as exc:
        return JSONResponse({"error": exc.code, "message": exc.message}, status_code=422)
    if d.notify:
        await d.notify({"type": "doc_ingested", "doc": result["doc"], "changes": result["changes"]})
    if d.speak:
        kind = documents.DOC_LABEL.get(result["doc"]["doc_type"], "document")
        cr = getattr(d.L, "credit_report", None)
        line = f"मैंने आपकी {kind} पढ़ ली।"
        if cr and result["doc"]["doc_type"] == "cibil_report":
            line += f" आपका {cr['bureau']} स्कोर {cr['score']:.0f} है, आपकी अपलोड की गई रिपोर्ट के मुताबिक।"
        line += f" आपकी मनी हेल्थ अब {result['health_after']} है, पहले {result['health_before']} थी।"
        asyncio.create_task(d.speak(line))
    return result


@app.get("/api/sources")
async def sources(request: Request, ids: str = ""):
    uid = _user(request)
    if not uid:
        return _deny()
    return {"sources": Dost.for_user(uid).sources([i for i in ids.split(",") if i])}


@app.get("/api/graph")
async def graph(request: Request):
    uid = _user(request)
    if not uid:
        return _deny()
    ids = request.query_params.get("focus", "")
    g = Dost.for_user(uid).graph
    return g.focus([i for i in ids.split(",") if i]) if ids else g.overview()


@app.get("/api/reminders")
async def reminders(request: Request):
    uid = _user(request)
    return {"reminders": Dost.for_user(uid).reminders()} if uid else _deny()


@app.post("/api/check-deadlines")
async def check_deadlines(request: Request):
    uid = _user(request)
    if not uid:
        return _deny()
    sim = request.query_params.get("simulate_balance")
    return Dost.for_user(uid).deadline_check(float(sim) if sim else None)


@app.websocket("/ws")
async def call(websocket: WebSocket) -> None:
    uid = auth.verify(websocket.cookies.get(auth.COOKIE))
    await websocket.accept()
    if not uid:
        await websocket.send_text(json.dumps({"type": "error", "message": "not signed in"}))
        await websocket.close()
        return
    d = Dost.for_user(uid)

    async def notify(payload):
        await websocket.send_text(json.dumps(payload, default=str))
    d.notify = notify

    first = greeting(d)
    if websocket.query_params.get("mode") == "outgoing":
        sim = websocket.query_params.get("simulate_balance")
        check = d.deadline_check(float(sim) if sim else None)
        if check.get("fire"):
            first = outgoing_greeting(d, check)
            await notify({"type": "evidence", "source_ids": check["due"]["source_ids"] + check["balance"]["source_ids"],
                          "text_key": "deadline"})
    prompt = SYSTEM_PROMPT.format(as_of=d.L.as_of.isoformat(), name=d.L.name)
    session = VoiceSession(BrowserTransport(websocket), system_prompt=prompt, greeting=first, tools=d.tools())
    await session.start()
    d.speak = session.say
    await notify({"type": "insights", "insights": d.insights()[:3]})
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
        d.notify = None
        d.speak = None
        await session.close(reason="browser_closed")


if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="app")
else:
    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(ROOT / "web" / "index.html", headers={"Cache-Control": "no-store"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
