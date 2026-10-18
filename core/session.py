"""
One CallSession per call. It holds everything that decides what the caller
is allowed to see:

  - who the caller is proven to be (a customer after name + DOB/phone/loan ID
    and an OTP; a staff member after employee ID + PIN), and their role
  - failed attempts and lockouts
  - the OTP, stored only as a hash, with expiry and an attempt limit
  - a live event stream for the browser's "under the hood" panel

Tools read identity from here, never from the LLM's arguments, so nothing
the caller says to the model can make it act as someone else.
"""
import asyncio
import hashlib
import hmac
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

MAX_VERIFY_FAILURES = 3
MAX_OTP_ATTEMPTS = 3
OTP_TTL_SECONDS = 300
EVENT_BACKLOG = 400


def _hash(secret: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, 50_000)


@dataclass
class CallSession:
    id: str
    token_hash: bytes
    line: str                                  # "customer" | "staff"
    client_ip: str
    scenario_id: str | None = None
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    ended: bool = False
    language: str | None = None                # last language STT detected, e.g. "hi-IN"
    turns: int = 0
    writes: int = 0
    voice_active: bool = False
    pc_id: str | None = None                   # the WebRTC peer bound to this call

    # customer identity
    customer_id: str | None = None             # set only after the OTP is checked
    pending_customer_id: str | None = None     # matched name + factor, waiting for OTP
    otp_hash: bytes | None = None
    otp_salt: bytes = b""
    otp_expires: float = 0.0
    otp_attempts: int = 0
    otps_sent: int = 0
    # staff identity
    staff_id: str | None = None
    staff_role: str | None = None

    verify_failures: int = 0
    locked: bool = False
    end_requested: bool = False                # the agent decided the call is over

    history: list = field(default_factory=list)   # the agent's conversation so far

    events: deque = field(default_factory=lambda: deque(maxlen=EVENT_BACKLOG))
    _subscribers: set = field(default_factory=set)
    turn_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # ---- identity ----------------------------------------------------------

    @property
    def verified(self) -> bool:
        return (self.customer_id if self.line == "customer" else self.staff_id) is not None

    @property
    def actor(self) -> str | None:
        return self.customer_id or self.staff_id

    def record_failure(self) -> None:
        self.verify_failures += 1
        if self.verify_failures >= MAX_VERIFY_FAILURES:
            self.locked = True
            self.pending_customer_id = None
            self.otp_hash = None
            self.emit("state", locked=True, verified=False)

    def issue_otp(self, customer_id: str) -> str:
        code = f"{secrets.randbelow(1_000_000):06d}"
        self.otps_sent += 1
        self.pending_customer_id = customer_id
        self.otp_salt = secrets.token_bytes(16)
        self.otp_hash = _hash(code, self.otp_salt)
        self.otp_expires = time.time() + OTP_TTL_SECONDS
        self.otp_attempts = 0
        return code

    def check_otp(self, code: str) -> str:
        """'ok', 'wrong', 'expired', 'none' or 'locked'."""
        if self.locked:
            return "locked"
        if self.otp_hash is None or self.pending_customer_id is None:
            return "none"
        if time.time() > self.otp_expires:
            self.otp_hash = None
            self.pending_customer_id = None
            return "expired"
        self.otp_attempts += 1
        if hmac.compare_digest(_hash(code, self.otp_salt), self.otp_hash):
            self.customer_id = self.pending_customer_id
            self.pending_customer_id = None
            self.otp_hash = None
            self.emit("state", verified=True, locked=False)
            return "ok"
        if self.otp_attempts >= MAX_OTP_ATTEMPTS:
            self.otp_hash = None
            self.pending_customer_id = None       # start verification again
            self.record_failure()
        return "wrong"

    # ---- events ------------------------------------------------------------

    def emit(self, event_type: str, /, **data: Any) -> None:
        """Send an event to this call's browser panel. Never blocks."""
        event = {**data, "type": event_type, "ts": round(time.time(), 3)}
        self.events.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass                        # a slow browser loses events, the call carries on

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=EVENT_BACKLOG)
        for e in self.events:
            q.put_nowait(e)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)


class SessionError(Exception):
    def __init__(self, status: int, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status, self.message, self.retry_after = status, message, retry_after


class SessionManager:
    """Creates, finds and expires calls, and enforces how many may exist."""

    def __init__(self, max_open: int, max_per_ip: int, ttl_seconds: int):
        self._sessions: dict[str, CallSession] = {}
        self._lock = threading.Lock()
        self.max_open, self.max_per_ip, self.ttl = max_open, max_per_ip, ttl_seconds

    def create(self, line: str, client_ip: str, scenario_id: str | None) -> tuple[CallSession, str]:
        if line not in ("customer", "staff"):
            raise SessionError(400, "line must be customer or staff")
        self.expire()
        with self._lock:
            open_sessions = [s for s in self._sessions.values() if not s.ended]
            if len(open_sessions) >= self.max_open:
                raise SessionError(503, "The demo is busy. Please try again in a few minutes.", 60)
            if sum(1 for s in open_sessions if s.client_ip == client_ip) >= self.max_per_ip:
                raise SessionError(429, "Too many open calls from your network. End one first.", 30)
            token = secrets.token_urlsafe(32)
            session = CallSession(id=secrets.token_hex(8), token_hash=hashlib.sha256(token.encode()).digest(),
                                  line=line, client_ip=client_ip, scenario_id=scenario_id)
            self._sessions[session.id] = session
            return session, token

    def authenticate(self, session_id: str, token: str | None) -> CallSession:
        """Find a call by id and check its bearer token in constant time."""
        session = self._sessions.get(session_id)
        expected = session.token_hash if session else secrets.token_bytes(32)
        given = hashlib.sha256((token or "").encode()).digest()
        if not hmac.compare_digest(given, expected) or session is None or session.ended:
            raise SessionError(401, "Call not found or already ended.")
        session.last_seen = time.time()
        return session

    def end(self, session: CallSession, reason: str) -> None:
        if not session.ended:
            session.ended = True
            session.emit("call", status="ended", reason=reason)

    def expire(self) -> None:
        now = time.time()
        with self._lock:
            for sid, s in list(self._sessions.items()):
                idle = now - s.last_seen
                if s.ended and idle > 120:
                    del self._sessions[sid]
                elif not s.ended and not s.voice_active and idle > self.ttl:
                    s.ended = True
                    s.emit("call", status="ended", reason="expired")

    def all(self) -> list[CallSession]:
        return list(self._sessions.values())
