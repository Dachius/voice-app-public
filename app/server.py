"""Voice-app server: token-gated PWA + websocket chat over subscription-backed CLI harnesses."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from backends.claude_backend import ClaudeBackend
from backends.codex_backend import CodexBackend
from media import STT, TTS
from memory import Memory
from store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("voice-app")

HERE = Path(__file__).parent
CFG = json.loads((HERE / "config.json").read_text())
DATA = (HERE / CFG["data_dir"]).resolve()
DATA.mkdir(parents=True, exist_ok=True)
TOKEN = (HERE / "token").read_text().strip()
if len(TOKEN) < 20:
    raise SystemExit("token file missing or too short")
COOKIE = "va_auth"

store = Store(DATA)
memory = Memory(Path(CFG["memory_dir"]))
backends: dict[str, Any] = {
    "claude": ClaudeBackend(CFG["claude_cli"], CFG["work_dir"], CFG.get("tool_permission_policy", "ask"),
                            idle_close_s=CFG.get("claude_idle_close_s", 1800), max_warm=CFG.get("claude_max_warm", 4)),
    "codex": CodexBackend(CFG["work_dir"], DATA / "codex-instructions", CFG.get("codex_extra_args", [])),
}
stt = STT(CFG.get("stt", {}))
tts = TTS(CFG.get("tts", {}))
turn_locks: dict[str, asyncio.Lock] = {}
pending_permissions: dict[str, asyncio.Future] = {}

app = FastAPI(title="voice-app")


@app.on_event("shutdown")
async def _shutdown():
    await backends["claude"].close_all()  # warm `claude` processes die with the service anyway; this is the polite version


# ---------- auth ----------
def _authed(req: Request | WebSocket) -> bool:
    if req.cookies.get(COOKIE) and secrets.compare_digest(req.cookies.get(COOKIE, ""), TOKEN):
        return True
    auth = req.headers.get("authorization", "")
    return auth.startswith("Bearer ") and secrets.compare_digest(auth[7:].strip(), TOKEN)


@app.middleware("http")
async def gate(request: Request, call_next):
    path = request.url.path
    if path in ("/login", "/health", "/manifest.webmanifest") or _authed(request):
        resp = await call_next(request)
        if path.startswith("/static/"):
            resp.headers["Cache-Control"] = "no-cache"  # always revalidate; sw.js keeps an offline copy
        return resp
    return Response("unauthorized. open /login?t=<token> once on this device.", status_code=401)


@app.get("/login")
async def login(t: str = ""):
    if not secrets.compare_digest(t, TOKEN):
        raise HTTPException(403, "bad token")
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(COOKIE, TOKEN, max_age=365 * 86400, httponly=True, secure=True, samesite="lax", path="/")
    return resp


@app.get("/health")
async def health():
    return {"ok": True}


# ---------- static / PWA ----------
STATIC = HERE / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/sw.js")
async def sw():
    return FileResponse(STATIC / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


# ---------- REST ----------
@app.get("/api/config")
async def api_config():
    t = CFG.get("tts", {})
    return {"backends": CFG["backends"], "default_backend": CFG["default_backend"], "voice": CFG.get("voice", {}),
            "tts": {"voice": t.get("voice"), "voices": t.get("voices", []), "speed": t.get("speed", 1.0)}}


# ---------- speech ----------
def _add_media_usage(cid: str | None, stt_s: float = 0.0, tts_chars: int = 0) -> None:
    """Accumulate pay-per-use speech usage on the conversation (rates from config, for the cost readout)."""
    if not cid:
        return
    c = store.load(cid)
    if not c:
        return
    m = c.setdefault("media", {"stt_s": 0.0, "tts_chars": 0, "usd": 0.0})
    m["stt_s"] = round(m.get("stt_s", 0.0) + stt_s, 2)
    m["tts_chars"] = m.get("tts_chars", 0) + tts_chars
    m["usd"] = round(m["stt_s"] / 60 * CFG.get("stt", {}).get("usd_per_min", 0) + m["tts_chars"] / 1000 * CFG.get("tts", {}).get("usd_per_1k_chars", 0), 4)
    store.save(c)


@app.post("/api/stt")
async def api_stt(request: Request, cid: str = ""):
    """Body: one utterance of audio (audio/wav from the browser VAD). Returns its transcript."""
    audio = await request.body()
    if len(audio) < 1000:
        raise HTTPException(400, "audio too short")
    try:
        res = await stt.transcribe(audio, request.headers.get("content-type", "audio/wav"))
    except Exception as e:
        log.warning("stt failed: %s", e)
        raise HTTPException(502, str(e)[:300])
    _add_media_usage(cid, stt_s=float(res.get("duration") or 0))
    return res


@app.post("/api/tts")
async def api_tts(body: dict, cid: str = ""):
    """Body: {text, voice?, speed?}. Returns synthesized audio (format from config.tts)."""
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "empty text")
    voice = body.get("voice") or None
    if voice and voice not in CFG.get("tts", {}).get("voices", [voice]):
        raise HTTPException(400, "unknown voice")
    speed = body.get("speed")
    try:
        speed = float(speed) if speed else None
        if speed is not None and not (0.25 <= speed <= 4.0):
            speed = None
    except (TypeError, ValueError):
        speed = None
    try:
        audio = await tts.synthesize(text, voice=voice, speed=speed)
    except Exception as e:
        log.warning("tts failed: %s", e)
        raise HTTPException(502, str(e)[:300])
    _add_media_usage(cid, tts_chars=len(text))
    return Response(audio, media_type=tts.media_type, headers={"Cache-Control": "no-store"})


@app.get("/api/conversations")
async def api_list():
    return store.list()


@app.post("/api/conversations")
async def api_create(body: dict):
    backend = body.get("backend") or CFG["default_backend"]
    if backend not in CFG["backends"]:
        raise HTTPException(400, "unknown backend")
    model = body.get("model") or CFG["backends"][backend]["default_model"]
    mode = body.get("mode") or "text"
    return store.create(backend, model, mode)


@app.get("/api/conversations/{cid}")
async def api_get(cid: str):
    c = store.load(cid)
    if not c:
        raise HTTPException(404)
    return c


@app.patch("/api/conversations/{cid}")
async def api_patch(cid: str, body: dict):
    c = store.load(cid)
    if not c:
        raise HTTPException(404)
    for k in ("title", "model", "mode"):
        if k in body:
            c[k] = body[k]
    store.save(c)
    return c


@app.delete("/api/conversations/{cid}")
async def api_delete(cid: str):
    if not store.delete(cid):
        raise HTTPException(404)
    return {"ok": True}


# ---------- prompt assembly ----------
def build_system_prompt(conv: dict) -> str:
    tpl = (HERE / "prompts" / "system.md").read_text()
    style = (HERE / "prompts" / f"style_{'voice' if conv.get('mode') == 'voice' else 'text'}.md").read_text().strip()
    return tpl.format(
        date=dt.date.today().isoformat(),
        style_section=style,
        work_dir=CFG["work_dir"],
        memory_dir=CFG["memory_dir"],
        memory_index=memory.index(),
    )


# ---------- websocket chat ----------
@app.websocket("/ws/{cid}")
async def ws_chat(ws: WebSocket, cid: str):
    if not _authed(ws):
        await ws.close(code=4401)
        return
    conv = store.load(cid)
    if not conv:
        await ws.close(code=4404)
        return
    await ws.accept()
    await ws.send_json({"type": "ready", "conversation": conv})
    lock = turn_locks.setdefault(cid, asyncio.Lock())
    backend = backends[conv["backend"]]

    async def emit(ev: dict):
        try:
            await ws.send_json(ev)
        except Exception:
            pass

    async def ask(tool_name: str, tool_input: dict) -> bool:
        """Forward a tool-permission prompt to the UI and wait for the answer (deny on timeout/disconnect)."""
        pid = secrets.token_hex(6)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        pending_permissions[pid] = fut
        await emit({"type": "permission_request", "id": pid, "tool": tool_name, "input": tool_input})
        try:
            return bool(await asyncio.wait_for(fut, CFG.get("permission_prompt_timeout_s", 180)))
        except asyncio.TimeoutError:
            await emit({"type": "status", "text": f"permission prompt for {tool_name} timed out → denied"})
            return False
        finally:
            pending_permissions.pop(pid, None)

    # Messages that must be handled even while a turn is running are read by a side task.
    inbox: asyncio.Queue = asyncio.Queue()

    async def reader():
        try:
            while True:
                m = await ws.receive_json()
                if m.get("type") == "permission_response":
                    fut = pending_permissions.get(m.get("id", ""))
                    if fut and not fut.done():
                        fut.set_result(bool(m.get("allow")))
                elif m.get("type") == "interrupt":
                    ok = await backend.interrupt(cid)
                    await emit({"type": "status", "text": "interrupt sent" if ok else "nothing to interrupt"})
                else:
                    await inbox.put(m)
        except WebSocketDisconnect:
            await inbox.put({"type": "_closed"})
        except Exception:
            await inbox.put({"type": "_closed"})

    reader_task = asyncio.create_task(reader())
    try:
        while True:
            msg = await inbox.get()
            t = msg.get("type")
            if t == "_closed":
                break
            if t == "interrupt":
                ok = await backend.interrupt(cid)
                await emit({"type": "status", "text": "interrupt sent" if ok else "nothing to interrupt"})
                continue
            if t != "user":
                continue
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            if lock.locked():
                await emit({"type": "error", "message": "a turn is already running"})
                continue
            async with lock:
                conv = store.load(cid) or conv
                if msg.get("mode") in ("text", "voice"):
                    conv["mode"] = msg["mode"]
                conv["messages"].append({"role": "user", "text": text, "ts": dt.datetime.now().isoformat(timespec="seconds")})
                if conv["title"] == "New conversation":
                    conv["title"] = text[:60] + ("…" if len(text) > 60 else "")
                store.save(conv)
                await emit({"type": "turn_start"})
                await memory.pull()
                sp = build_system_prompt(conv)
                res = await backend.run_turn(conv, text, sp, emit, ask)
                amsg = {"role": "assistant", "parts": res["parts"], "ts": dt.datetime.now().isoformat(timespec="seconds"),
                        "model": conv["model"], "cost": res.get("cost"), "usage": res.get("usage"), "error": res.get("error")}
                conv["messages"].append(amsg)
                if res.get("session_id"):
                    conv["session_id"] = res["session_id"]
                if res.get("cost"):
                    conv["total_cost_usd"] = (conv.get("total_cost_usd") or 0) + res["cost"]
                store.save(conv)
                asyncio.create_task(memory.commit_leftovers(f"voice-app: {conv['title'][:40]}"))
                await emit({"type": "turn_end", "message": amsg, "session_id": conv["session_id"], "total_cost_usd": conv["total_cost_usd"],
                            "media": (store.load(cid) or conv).get("media")})
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("ws error")
        try:
            await ws.close()
        except Exception:
            pass
    finally:
        reader_task.cancel()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=CFG["port"], log_level="info")
