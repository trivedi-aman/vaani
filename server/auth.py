"""
Sign-in sessions. A successful login gets a random token in an HttpOnly,
SameSite=Strict cookie; the server keeps only its SHA-256 hash. Sessions live
in memory, so a restart signs everyone out (which is also how a removed user
loses access straight away).
"""
import hashlib
import secrets
import threading
import time

COOKIE = "vaani_login"


class LoginSessions:
    def __init__(self, ttl_seconds: int, max_sessions: int = 2000):
        self.ttl, self.max = ttl_seconds, max_sessions
        self._by_hash: dict[bytes, tuple[str, float]] = {}       # token hash -> (user_id, expires)
        self._lock = threading.Lock()

    @staticmethod
    def _hash(token: str) -> bytes:
        return hashlib.sha256(token.encode()).digest()

    def create(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            if len(self._by_hash) >= self.max:
                self._purge(now)
                if len(self._by_hash) >= self.max:                # still full: drop the oldest
                    oldest = min(self._by_hash, key=lambda k: self._by_hash[k][1])
                    del self._by_hash[oldest]
            self._by_hash[self._hash(token)] = (user_id, now + self.ttl)
        return token

    def user(self, token: str | None, users: dict[str, str]) -> str | None:
        """The signed-in user, if the token is live and the user still has access."""
        if not token:
            return None
        key = self._hash(token[:200])
        with self._lock:
            found = self._by_hash.get(key)
            if found is None:
                return None
            user_id, expires = found
            if expires < time.time() or user_id not in users:
                del self._by_hash[key]
                return None
            return user_id

    def revoke(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._by_hash.pop(self._hash(token[:200]), None)

    def _purge(self, now: float) -> None:
        for k in [k for k, (_, exp) in self._by_hash.items() if exp < now]:
            del self._by_hash[k]
