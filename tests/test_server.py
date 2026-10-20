"""The web server's security and cost controls."""
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from core.config import Settings
from server.app import create_app
from server.users import hash_password
from tests.fakes import ScriptedModel, say

PASSWORD = "correct-horse-42"
USERS = {"tester": hash_password(PASSWORD, iterations=1000), "other": hash_password("another-pass-9", iterations=1000)}


def make(tmp_path, signed_in=True, **overrides):
    settings = Settings(_env_file=None, var_dir=tmp_path, allowed_hosts="testserver", **overrides)
    c = TestClient(create_app(settings, model=ScriptedModel([say("Hello")] * 50), users=USERS))
    if signed_in:
        assert c.post("/api/login", json={"user_id": "tester", "password": PASSWORD}).status_code == 200
    return c


def start(c, **headers):
    r = c.post("/api/calls", json={"line": "customer"}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    return body["call_id"], {"Authorization": f"Bearer {body['token']}"}


def test_security_headers(tmp_path):
    with make(tmp_path) as c:
        h = c.get("/api/config").headers
        assert "default-src 'self'" in h["content-security-policy"] and "frame-ancestors 'none'" in h["content-security-policy"]
        assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
        assert h["referrer-policy"] == "no-referrer" and "microphone=(self)" in h["permissions-policy"]
        assert "server" not in h


def test_production_refuses_to_start_without_users(tmp_path):
    settings = Settings(_env_file=None, var_dir=tmp_path, environment="production", allowed_hosts="demo.example",
                        trust_proxy=True)
    with pytest.raises(RuntimeError, match="server/users.py"):
        create_app(settings, model=ScriptedModel([]), users={})


def test_everything_needs_a_sign_in(tmp_path):
    with make(tmp_path, signed_in=False) as c:
        assert c.get("/api/config").json() == {"signed_in": False}      # says nothing about the server
        assert c.get("/api/scenarios").status_code == 401
        assert c.post("/api/calls", json={"line": "customer"}).status_code == 401
        assert c.post("/api/login", json={"user_id": "tester", "password": "wrong"}).status_code == 401
        assert c.post("/api/login", json={"user_id": "nobody", "password": PASSWORD}).status_code == 401
        r = c.post("/api/login", json={"user_id": " Tester ", "password": PASSWORD})
        assert r.status_code == 200 and r.json() == {"user": "tester"}
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie
        assert c.get("/api/config").json()["user"] == "tester"
        assert c.get("/api/scenarios").status_code == 200
        c.post("/api/logout")
        assert c.get("/api/scenarios").status_code == 401


def test_password_guessing_is_limited_but_the_right_password_is_not(tmp_path):
    with make(tmp_path, signed_in=False, login_failures_per_15min=3, max_sessions_per_ip=50) as c:
        for _ in range(10):                                   # right password: never limited
            assert c.post("/api/login", json={"user_id": "tester", "password": PASSWORD}).status_code == 200
            assert c.post("/api/calls", json={"line": "customer"}).status_code == 200
        for guess in ("wrong-1", "wrong-2", "wrong-3"):
            assert c.post("/api/login", json={"user_id": "tester", "password": guess}).status_code == 401
        # once locked out, even the right password waits
        assert c.post("/api/login", json={"user_id": "tester", "password": PASSWORD}).status_code == 429


def test_a_removed_user_is_signed_out(tmp_path):
    users = dict(USERS)
    settings = Settings(_env_file=None, var_dir=tmp_path, allowed_hosts="testserver")
    with TestClient(create_app(settings, model=ScriptedModel([]), users=users)) as c:
        c.post("/api/login", json={"user_id": "other", "password": "another-pass-9"})
        assert c.get("/api/scenarios").status_code == 200
        del users["other"]
        assert c.get("/api/scenarios").status_code == 401


def test_a_call_belongs_to_the_user_who_started_it(tmp_path):
    with make(tmp_path) as c:
        call, auth = start(c)
        c.post("/api/login", json={"user_id": "other", "password": "another-pass-9"})
        assert c.post(f"/api/calls/{call}/turn", json={"text": "hi"}, headers=auth).status_code == 401


def test_production_refuses_a_publicly_reachable_app(tmp_path):
    base = {"_env_file": None, "var_dir": tmp_path, "environment": "production", "allowed_hosts": "demo.example"}
    with pytest.raises(RuntimeError, match="HOST must be 127.0.0.1"):
        create_app(Settings(**base, host="0.0.0.0", trust_proxy=True), model=ScriptedModel([]), users=USERS)
    with pytest.raises(RuntimeError, match="TRUST_PROXY"):
        create_app(Settings(**base), model=ScriptedModel([]), users=USERS)


def test_event_stream_refuses_other_sites_and_floods(tmp_path):
    from starlette.websockets import WebSocketDisconnect
    with make(tmp_path) as c:
        call, _ = start(c)
        with pytest.raises(WebSocketDisconnect), c.websocket_connect(f"/api/calls/{call}/events",
                                                                     headers={"Origin": "https://evil.example"}):
            pass
        for _ in range(30):
            with c.websocket_connect(f"/api/calls/{call}/events") as ws:
                ws.close()
        with pytest.raises(WebSocketDisconnect), c.websocket_connect(f"/api/calls/{call}/events"):
            pass


def test_calls_need_their_own_token(tmp_path):
    with make(tmp_path) as c:
        call_a, auth_a = start(c)
        call_b, _ = start(c)
        assert c.post(f"/api/calls/{call_a}/turn", json={"text": "hi"}, headers=auth_a).status_code == 200
        assert c.post(f"/api/calls/{call_b}/turn", json={"text": "hi"}, headers=auth_a).status_code == 401
        assert c.post(f"/api/calls/{call_a}/turn", json={"text": "hi"}).status_code == 401


def test_new_calls_per_ip_are_rate_limited(tmp_path):
    with make(tmp_path, calls_per_ip_per_hour=2, max_sessions_per_ip=10) as c:
        start(c)
        start(c)
        r = c.post("/api/calls", json={"line": "customer"})
        assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_open_calls_per_ip_are_capped(tmp_path):
    with make(tmp_path, max_sessions_per_ip=1) as c:
        call, auth = start(c)
        assert c.post("/api/calls", json={"line": "staff"}).status_code == 429
        c.post(f"/api/calls/{call}/end", headers=auth)
        start(c)


def test_daily_budget(tmp_path):
    with make(tmp_path, daily_call_budget=1, max_sessions_per_ip=10) as c:
        start(c)
        assert c.post("/api/calls", json={"line": "customer"}).status_code == 503


def test_text_turns_are_rate_limited_and_size_limited(tmp_path):
    with make(tmp_path, text_turns_per_minute=2) as c:
        call, auth = start(c)
        assert c.post(f"/api/calls/{call}/turn", json={"text": "x" * 600}, headers=auth).status_code == 422
        for _ in range(2):
            assert c.post(f"/api/calls/{call}/turn", json={"text": "hi"}, headers=auth).status_code == 200
        assert c.post(f"/api/calls/{call}/turn", json={"text": "hi"}, headers=auth).status_code == 429


def test_large_bodies_are_rejected_before_parsing(tmp_path):
    with make(tmp_path, max_body_bytes=1000) as c:
        r = c.post("/api/calls", content=b"{" + b" " * 5000 + b"}", headers={"Content-Type": "application/json"})
        assert r.status_code == 413


def test_unknown_hosts_are_rejected(tmp_path):
    with make(tmp_path) as c:
        assert c.get("/api/config", headers={"Host": "evil.example"}).status_code == 400


def test_validation_errors_do_not_echo_internals(tmp_path):
    with make(tmp_path) as c:
        r = c.post("/api/calls", json={"line": "admin"})
        assert r.status_code == 422 and "Traceback" not in r.text and r.json()["error"] == "Invalid request."


def test_voice_offer_cannot_hijack_another_peer(tmp_path):
    with make(tmp_path, sarvam_api_key=SecretStr("dummy")) as c:
        call, auth = start(c)
        r = c.post(f"/api/calls/{call}/offer", json={"sdp": "v=0", "type": "offer", "pc_id": "someone-elses-pc"}, headers=auth)
        assert r.status_code == 403
        r = c.patch(f"/api/calls/{call}/offer", json={"pc_id": "someone-elses-pc", "candidates": []}, headers=auth)
        assert r.status_code == 403


def test_event_stream_needs_the_token(tmp_path):
    with make(tmp_path) as c:
        call, auth = start(c)
        with c.websocket_connect(f"/api/calls/{call}/events") as ws:
            ws.send_json({"token": "wrong"})
            from starlette.websockets import WebSocketDisconnect
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 4401
        with c.websocket_connect(f"/api/calls/{call}/events") as ws:
            ws.send_json({"token": auth["Authorization"][7:]})
            assert ws.receive_json()["type"] == "call"


def test_forwarded_for_is_only_trusted_behind_our_proxy(tmp_path):
    # Without TRUST_PROXY a spoofed header must not dodge per-IP limits.
    with make(tmp_path, calls_per_ip_per_hour=1, max_sessions_per_ip=10) as c:
        start(c, **{"X-Forwarded-For": "1.1.1.1"})
        assert c.post("/api/calls", json={"line": "customer"}, headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 429
    # With it, the right-most entry (added by our proxy) is the client.
    with make(tmp_path, calls_per_ip_per_hour=1, max_sessions_per_ip=10, trust_proxy=True) as c:
        start(c, **{"X-Forwarded-For": "9.9.9.9, 1.1.1.1"})
        assert c.post("/api/calls", json={"line": "customer"}, headers={"X-Forwarded-For": "9.9.9.9, 2.2.2.2"}).status_code == 200


def test_frontend_path_traversal_is_blocked(tmp_path):
    with make(tmp_path) as c:
        r = c.get("/..%2F..%2Fcore%2Fconfig.py")
        assert "SecretStr" not in r.text


def test_event_stream_needs_a_sign_in(tmp_path):
    from starlette.websockets import WebSocketDisconnect
    with make(tmp_path) as c:
        call, auth = start(c)
        c.post("/api/logout")
        with pytest.raises(WebSocketDisconnect), c.websocket_connect(f"/api/calls/{call}/events"):
            pass
