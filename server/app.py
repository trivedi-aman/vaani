"""
The web server: call sessions, WebRTC signalling, text mode, the live event
stream, scenarios, and the built frontend.

Security and cost controls, all on by default:
  - optional access code for starting calls (required in production)
  - per-call bearer tokens; the WebRTC peer is bound to the call that created it
  - rate limits per IP and per call, caps on open calls, concurrent voice
    calls, and a daily call budget
  - call length, idle and turn limits
  - request size limits, strict security headers and CSP, trusted hosts
  - no stack traces or internal details in responses; masked logs; audit trail
"""
import asyncio
import contextlib
import hmac
import logging
from contextlib import asynccontextmanager
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from agent.graph import Agent
from agent.prompts import GREETING
from core import audit
from core.config import ROOT, Settings, get_settings
from core.session import CallSession, SessionError, SessionManager
from core.store import Store

from . import logs
from .ratelimit import DailyBudget, SlidingWindow

log = logging.getLogger("vaani.server")
WEB_DIST = ROOT / "web" / "dist"


# ---- request bodies --------------------------------------------------------------

class NewCall(BaseModel):
    line: str = Field(..., pattern="^(customer|staff)$")
    scenario_id: str | None = Field(None, pattern="^[CS][0-9]{2}$")


class TextTurn(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


class Offer(BaseModel):
    sdp: str = Field(..., max_length=20_000)
    type: str = Field(..., pattern="^offer$")
    pc_id: str | None = Field(None, max_length=100)
    restart_pc: bool | None = None
    request_data: Any | None = None


class Candidate(BaseModel):
    candidate: str = Field("", max_length=1000)
    sdp_mid: str = Field("", max_length=50)
    sdp_mline_index: int = Field(0, ge=0, le=16)


class CandidatePatch(BaseModel):
    pc_id: str = Field(..., max_length=100)
    candidates: list[Candidate] = Field(..., max_length=30)


# ---- the app -----------------------------------------------------------------------

def create_app(settings: Settings | None = None, model: Any = None, store: Store | None = None) -> FastAPI:
    """`model` and `store` are injectable so tests run without AWS."""
    settings = settings or get_settings()
    logs.configure(settings.log_level)
    if settings.production:
        problems = settings.check_production()
        if problems:
            raise RuntimeError("Refusing to start in production: " + "; ".join(problems))
    audit.configure(settings.var_dir)

    store = store or Store.load(settings.data_dir, settings.demo_today)
    if model is None:
        from agent.llm import bedrock_model
        model = bedrock_model(settings)
    agent = Agent(model, store, settings)
    sessions = SessionManager(settings.max_open_sessions, settings.max_sessions_per_ip, settings.session_ttl_seconds)
    scenarios = _load_scenarios()

    per_ip = SlidingWindow(settings.requests_per_minute_per_ip, 60)
    new_calls = SlidingWindow(settings.calls_per_ip_per_hour, 3600)
    code_attempts = SlidingWindow(settings.access_code_attempts_per_15min, 900)
    text_turns = SlidingWindow(settings.text_turns_per_minute, 60)
    offers = SlidingWindow(10, 60)
    budget = DailyBudget(settings.daily_call_budget)
    voice_lock = asyncio.Lock()
    connections: dict[str, Any] = {}           # session id -> SmallWebRTCConnection
    webrtc = None

    if settings.voice_available:
        from pipecat.transports.smallwebrtc.connection import IceServer
        from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequestHandler
        ice = [IceServer(urls=settings.stun_url)]
        if settings.turn_url:
            ice.append(IceServer(urls=settings.turn_url, username=settings.turn_username or "",
                                 credential=settings.turn_password.get_secret_value() if settings.turn_password else ""))
        webrtc = SmallWebRTCRequestHandler(ice_servers=ice)

    async def janitor():
        while True:
            await asyncio.sleep(30)
            sessions.expire()
            for s in sessions.all():
                if s.ended and s.id in connections:
                    with contextlib.suppress(Exception):
                        await connections.pop(s.id).disconnect()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(janitor())
        log.info("Vaani started (%s); voice %s; model %s", settings.environment,
                 "on" if settings.voice_available else "off (no SARVAM_API_KEY)", settings.nova_model_id)
        yield
        task.cancel()
        for conn in list(connections.values()):
            with contextlib.suppress(Exception):
                await conn.disconnect()
        if webrtc:
            await webrtc.close()

    app = FastAPI(title="Vaani", lifespan=lifespan,
                  docs_url=None if settings.production else "/docs", redoc_url=None, openapi_url=None if settings.production else "/openapi.json")
    app.state.sessions, app.state.agent, app.state.store = sessions, agent, store

    # ---- helpers ------------------------------------------------------------------

    def client_ip(request: Request | WebSocket) -> str:
        if settings.trust_proxy:
            fwd = request.headers.get("x-forwarded-for", "")
            if fwd:
                return fwd.split(",")[-1].strip()       # the hop our own proxy added
        return request.client.host if request.client else "unknown"

    def limited(window: SlidingWindow, key: str, what: str) -> None:
        wait = window.hit(key)
        if wait is not None:
            raise SessionError(429, f"Too many {what}. Please wait {wait} seconds.", wait)

    def call_for(request: Request, call_id: str) -> CallSession:
        auth = request.headers.get("authorization", "")
        token = auth[7:] if auth.lower().startswith("bearer ") else None
        return sessions.authenticate(call_id, token)

    def check_access_code(request: Request) -> None:
        if settings.access_code is None:
            return
        limited(code_attempts, client_ip(request), "access code attempts")
        given = request.headers.get("x-access-code", "")
        if not hmac.compare_digest(given.encode(), settings.access_code.get_secret_value().encode()):
            raise SessionError(403, "Access code required.")

    async def end_call(session: CallSession, reason: str) -> None:
        sessions.end(session, reason)
        conn = connections.pop(session.id, None)
        if conn is not None:
            with contextlib.suppress(Exception):
                await conn.disconnect()

    # ---- middleware ----------------------------------------------------------------

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # size limit before reading anything
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.max_body_bytes:
            return JSONResponse({"error": "Request too large."}, status_code=413)
        if request.url.path.startswith("/api/"):
            wait = per_ip.hit(client_ip(request))
            if wait is not None:
                return JSONResponse({"error": "Too many requests."}, status_code=429, headers={"Retry-After": str(wait)})
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error on %s", request.url.path)
            response = JSONResponse({"error": "Something went wrong."}, status_code=500)
        _security_headers(response, settings)
        return response

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.hosts)

    @app.exception_handler(SessionError)
    async def _session_error(_request: Request, e: SessionError):
        headers = {"Retry-After": str(e.retry_after)} if e.retry_after else None
        return JSONResponse({"error": e.message}, status_code=e.status, headers=headers)

    @app.exception_handler(HTTPException)
    async def _http_error(_request: Request, e: HTTPException):
        return JSONResponse({"error": e.detail if e.status_code < 500 else "Something went wrong."}, status_code=e.status_code)

    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def _invalid(_request: Request, e: RequestValidationError):
        return JSONResponse({"error": "Invalid request.", "fields": [".".join(map(str, x["loc"][1:])) for x in e.errors()[:5]]},
                            status_code=422)

    # ---- public --------------------------------------------------------------------

    @app.get("/healthz")
    async def health():
        return {"ok": True}

    @app.get("/api/config")
    async def config():
        return {"access_code_required": settings.access_code is not None, "voice_available": settings.voice_available,
                "demo_today": settings.demo_today.isoformat(), "max_call_seconds": settings.call_max_seconds,
                "max_text_chars": settings.max_text_chars, "ice_servers": [{"urls": settings.stun_url}]}

    @app.get("/api/scenarios")
    async def list_scenarios(request: Request):
        check_access_code(request)
        return {"scenarios": scenarios}

    # ---- calls ---------------------------------------------------------------------

    @app.post("/api/calls")
    async def create_call(body: NewCall, request: Request):
        check_access_code(request)
        ip = client_ip(request)
        limited(new_calls, ip, "new calls from your network this hour")
        if not budget.take():
            raise SessionError(503, "Today's demo call budget is used up. Please try again tomorrow.")
        session, token = sessions.create(body.line, ip, body.scenario_id)
        session.emit("call", status="created", line=body.line)
        session.emit("transcript", role="bot", text=GREETING[body.line])
        audit.record(session.id, session.line, None, "call_created", {"scenario": body.scenario_id}, "ok")
        return {"call_id": session.id, "token": token, "line": session.line}

    @app.post("/api/calls/{call_id}/turn")
    async def text_turn(call_id: str, body: TextTurn, request: Request):
        session = call_for(request, call_id)
        if len(body.text) > settings.max_text_chars:
            raise SessionError(422, f"Keep messages under {settings.max_text_chars} characters.")
        if session.voice_active:
            raise SessionError(409, "This call is in voice mode.")
        limited(text_turns, session.id, "messages in this call")
        guessed = _guess_language(body.text)
        if guessed != "en-IN" or not session.language:      # Latin text may be Hinglish: keep what we knew
            session.language = guessed
        reply = await agent.turn(session, body.text.strip())
        ended = session.end_requested
        if ended:
            await end_call(session, "agent ended the call")
        return {"reply": reply, "ended": ended, "verified": session.verified, "locked": session.locked}

    @app.post("/api/calls/{call_id}/end")
    async def hang_up(call_id: str, request: Request):
        session = call_for(request, call_id)
        await end_call(session, "caller hung up")
        return {"ended": True}

    @app.websocket("/api/calls/{call_id}/events")
    async def events(ws: WebSocket, call_id: str):
        await ws.accept()
        try:
            # The token comes in the first message, not the URL, so it never lands in access logs.
            first = await asyncio.wait_for(ws.receive_json(), timeout=5)
            session = sessions.authenticate(call_id, str(first.get("token", ""))[:100])
        except Exception:                               # bad JSON, timeout, wrong token
            await ws.close(code=4401)
            return
        queue = session.subscribe()
        try:
            while True:
                event = await queue.get()
                await ws.send_json(event)
                if event["type"] == "call" and event.get("status") == "ended":
                    break
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            session.unsubscribe(queue)
            with contextlib.suppress(Exception):
                await ws.close()

    # ---- voice (WebRTC signalling) ------------------------------------------------

    @app.post("/api/calls/{call_id}/offer")
    async def offer(call_id: str, body: Offer, request: Request):
        session = call_for(request, call_id)
        if webrtc is None:
            raise SessionError(503, "Voice is not configured on this server. Use text mode.")
        limited(offers, client_ip(request), "connection attempts")
        from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequest

        if body.pc_id:                                  # renegotiation: only for this call's own peer
            if body.pc_id != session.pc_id:
                raise SessionError(403, "That connection does not belong to this call.")
            answer = await webrtc.handle_web_request(SmallWebRTCRequest(sdp=body.sdp, type=body.type, pc_id=body.pc_id,
                                                                        restart_pc=body.restart_pc), _no_callback)
            return answer
        async with voice_lock:
            if session.voice_active or session.pc_id:
                raise SessionError(409, "This call already has a voice connection.")
            active = sum(1 for s in sessions.all() if s.voice_active)
            if active >= settings.max_concurrent_voice_calls:
                raise SessionError(503, "All voice lines are busy. Try again shortly, or use text mode.", 30)
            session.voice_active = True                 # reserve the slot before awaiting anything

        async def start(connection):
            connections[session.id] = connection
            asyncio.create_task(_run_voice(session, connection))

        try:
            answer = await webrtc.handle_web_request(SmallWebRTCRequest(sdp=body.sdp, type=body.type), start)
        except Exception as e:
            session.voice_active = False
            log.warning("WebRTC offer failed for call %s: %s", session.id, type(e).__name__)
            raise SessionError(400, "Could not start the voice connection.") from None
        session.pc_id = answer["pc_id"]
        return answer

    @app.patch("/api/calls/{call_id}/offer")
    async def ice(call_id: str, body: CandidatePatch, request: Request):
        session = call_for(request, call_id)
        if webrtc is None or body.pc_id != session.pc_id:
            raise SessionError(403, "That connection does not belong to this call.")
        from pipecat.transports.smallwebrtc.request_handler import IceCandidate, SmallWebRTCPatchRequest
        await webrtc.handle_patch_request(SmallWebRTCPatchRequest(
            pc_id=body.pc_id, candidates=[IceCandidate(c.candidate, c.sdp_mid, c.sdp_mline_index) for c in body.candidates]))
        return {"ok": True}

    async def _run_voice(session: CallSession, connection) -> None:
        from voice.pipeline import run_call

        async def done(s: CallSession):
            connections.pop(s.id, None)
            await end_call(s, "voice call finished")

        await run_call(session, connection, agent, settings, done)

    # ---- frontend --------------------------------------------------------------------

    @app.get("/{path:path}")
    async def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found.")
        target = (WEB_DIST / path).resolve()
        if path and target.is_file() and WEB_DIST.resolve() in target.parents:
            return FileResponse(target, headers={"Cache-Control": "public, max-age=31536000, immutable"}
                                if path.startswith("assets/") else None)
        index = WEB_DIST / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return JSONResponse({"error": "Frontend not built. Run: cd web && npm install && npm run build"}, status_code=404)

    return app


async def _no_callback(_connection) -> None:
    return None


def _guess_language(text: str) -> str:
    from voice.language import reply_language
    return reply_language(text, None)


def _load_scenarios() -> list[dict]:
    out = []
    for path in sorted((ROOT / "data" / "scenarios").glob("*/*.yaml")):
        out.append(yaml.safe_load(path.read_text(encoding="utf-8")))
    return out


def _security_headers(response, settings: Settings) -> None:
    h = response.headers
    h["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "media-src 'self' blob: mediastream:; connect-src 'self'; font-src 'self'; object-src 'none'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    h["Permissions-Policy"] = "microphone=(self), camera=(), geolocation=(), payment=(), usb=()"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    h["Cross-Origin-Resource-Policy"] = "same-origin"
    if settings.production:
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if "server" in h:
        del h["server"]
