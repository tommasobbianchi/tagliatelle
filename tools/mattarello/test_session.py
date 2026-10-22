"""L5 tests \u2014 offline, no real hardware.

Two layers:
  * **unit**   \u2014 pure-logic checks (token-once, Yes-tap, file mode 0600, alarm predicate, and the
    four watchdog StopReasons) run against a Python-object transport and a fake clock: fast and exact.
  * **http**   \u2014 the full protocol against a real local stdlib ``http.server`` stand-in for the A250
    (``connect`` / ``status`` heartbeat / ``prepare_print`` / ``start_print`` / ``stop_print``), proving:
      normal heartbeat \u2192 session stays alive;
      silence > threshold \u2192 ``SessionLost`` + ``is_alive()`` False;
      an alarm in the status \u2192 the watchdog halts with ``ALARM`` and the halt is sent to the (fake) machine.

Run:  cd tools/mattarello && python3 -m pytest test_session.py -q
"""
from __future__ import annotations

import json
import os
import re
import socket
import stat
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

# make `import mattarello` resolve regardless of pytest's rootdir
_TOOLS_DIR = str(Path(__file__).resolve().parent.parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from mattarello import (  # noqa: E402
    MachineSession,
    SessionLost,
    Watchdog,
    StopReason,
    AlarmDetector,
    write_token_file,
)


# =====================================================================
#  offline fakes
# =====================================================================
class FakeTransport:
    """In-memory stand-in for a transport.  Mirrors the measured connect semantics:
    empty token \u2192 mint a fresh one; a presented token \u2192 echo it.  ``get`` can be made to
    answer "not yet accepted" (empty body) for the first N calls."""

    def __init__(self, get_fail_times: int = 0):
        self.calls: list = []
        self._fresh = 0
        self._n = 0
        self.get_fail_times = get_fail_times

    def post_form(self, path, **fields) -> bytes:
        self.calls.append(("post_form", path, dict(fields)))
        tok = fields.get("token", "")
        if "connect" in path:
            if tok == "":
                self._fresh += 1
                return json.dumps({"token": "fresh-%d" % self._fresh, "series": "SM2D040"}).encode()
            return json.dumps({"token": tok, "series": "SM2D040"}).encode()
        return b'{"code":0}'

    def get(self, path) -> bytes:
        self.calls.append(("get", path))
        self._n += 1
        if self._n <= self.get_fail_times:
            return b""                                   # not yet accepted: empty, non-JSON
        return b'{"status":"IDLE","homed":true,"laserPower":0}'

    def post_file(self, *a, **k) -> bytes:
        return b"Prepare successfully"


class Clock:
    """A fake monotonic clock for deterministic timeout tests."""
    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


# =====================================================================
#  stdlib http.server fake A250
# =====================================================================
class FakeA250:
    """Local-only HTTP stand-in for the Snapmaker 2.0 A250 (measured protocol).

    Controllable from the test thread: ``tap_yes()`` (owner taps Yes on the machine),
    ``go_down()`` (telemetry/channel stops answering), ``set_alarm(**kw)`` (status carries
    a fault), ``set_status(...)``.  Records ``stop_print_calls`` so tests can assert the
    watchdog actually sent the halt to the machine."""

    def __init__(self):
        self.lock = threading.Lock()
        self.token = "boot-token"
        self.accepted = False
        self.down = False
        self.status = {"status": "IDLE", "homed": True, "laserPower": 0,
                       "x": 0, "y": 0, "z": 220, "printStatus": None}
        self._fresh = 0
        self.stop_print_calls = 0
        self._server: ThreadingHTTPServer | None = None
        self._port = None

    # -- control -------------------------------------------------------------
    def start(self):
        handler = self._make_handler()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def base_url(self) -> str:
        return "http://127.0.0.1:%d" % self._port

    def tap_yes(self):
        with self.lock:
            self.accepted = True

    def go_down(self):
        with self.lock:
            self.down = True

    def set_status(self, st: dict):
        with self.lock:
            self.status = dict(st)

    def set_alarm(self, **kw):
        with self.lock:
            self.status.update(kw)

    # -- handler -------------------------------------------------------------
    def _make_handler(self):
        owner = self

        def _read_body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a, **k):
                pass

            def _finish(self, code: int, payload: bytes = b"", ctype: str = "application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if payload:
                    self.wfile.write(payload)

            def _token(self, body: bytes) -> str:
                ct = (self.headers.get("Content-Type") or "").lower()
                if "multipart" in ct:
                    m = re.search(rb'name="token"\r\n\r\n([^\r]*)', body)
                    return m.group(1).decode() if m else ""
                try:
                    return dict(urllib.parse.parse_qsl(body.decode("utf-8"))).get("token", "")
                except Exception:
                    return ""

            def do_GET(self):
                owner._record("GET", self.path)
                path = self.path.split("?", 1)[0]
                tok = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("token", [""])[0]
                with owner.lock:
                    if path != "/api/v1/status":
                        self._finish(404)
                        return
                    if tok != owner.token:
                        self._finish(401)                                  # wrong/unknown token
                        return
                    if owner.down:
                        self._finish(503, b"SERVICE UNAVAILABLE")          # channel stopped
                        return
                    if not owner.accepted:
                        self._finish(200, b"")                             # not yet: empty, non-JSON
                        return
                    self._finish(200, json.dumps(owner.status).encode())

            def do_POST(self):
                owner._record("POST", self.path)
                body = _read_body(self)
                tok = self._token(body)
                path = self.path
                with owner.lock:
                    if path == "/api/v1/connect":
                        if tok == "":
                            owner._fresh += 1
                            newtok = "fresh-%d" % owner._fresh
                            owner.token = newtok
                            owner.accepted = False
                            payload = json.dumps({"token": newtok, "series": "SM2D040",
                                                  "headType": "dual"}).encode()
                        elif tok == owner.token:
                            payload = json.dumps({"token": tok, "series": "SM2D040",
                                                  "headType": "dual"}).encode()
                        else:
                            self._finish(403, b"{}")
                            return
                        self._finish(200, payload)
                        return
                    if tok != owner.token:
                        self._finish(403, b"{}")
                        return
                    if path == "/api/v1/prepare_print":
                        self._finish(200, b"Prepare successfully", "text/plain")
                        return
                    if path in ("/api/v1/start_print", "/api/v1/stop_print",
                                "/api/v1/emergency_stop", "/api/v1/disconnect"):
                        if path == "/api/v1/stop_print":
                            owner.stop_print_calls += 1
                        self._finish(200, json.dumps({"code": 0}).encode())
                        return
                    self._finish(404)

        return Handler

    def _record(self, method: str, path: str):
        pass  # logging hook (kept trivial; tests assert on counters/events instead)


# =====================================================================
#  a session wired to a watchdog over the shared transport (unit + http)
# =====================================================================
def attach_watchdog(session: MachineSession, timeout: float = 8.0) -> Watchdog:
    wd = Watchdog(transport=session.transport_for(), token=lambda: session.token, timeout=timeout)
    session.set_monitor(wd)
    return wd


# =====================================================================
#  unit: token presentation
# =====================================================================
def test_fresh_session_mints_and_presents_token_once():
    t = FakeTransport()
    s = MachineSession(base_url="http://x", transport=t)
    s.connect(token="")
    tokens = [c[2]["token"] for c in t.calls if c[1] == "/api/v1/connect"]
    assert tokens == ["", "fresh-1"]       # mint with empty, then present the minted one exactly once
    assert s.token == "fresh-1"


def test_known_token_is_presented_once():
    t = FakeTransport()
    s = MachineSession(base_url="http://x", transport=t)
    s.connect(token="known-token")
    tokens = [c[2]["token"] for c in t.calls if c[1] == "/api/v1/connect"]
    assert tokens == ["known-token"]       # a known token is presented exactly once
    assert s.token == "known-token"


def test_token_stays_owner_only_mode_600(tmp_path):
    p = tmp_path / "snap_token"
    s = MachineSession(base_url="http://x", transport=FakeTransport(), token_file=p, persist_token=True)
    s.connect(token="secret-token")
    assert p.read_text().strip() == "secret-token"
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_token_not_persisted_off_rpi(tmp_path, monkeypatch):
    # when not told to persist (e.g. running on the dev server), the token must stay in memory only
    p = tmp_path / "snap_token"
    s = MachineSession(base_url="http://x", transport=FakeTransport(), token_file=p, persist_token=False)
    s.connect(token="keep-in-memory")
    assert s.token == "keep-in-memory"
    assert not p.exists()


def test_write_token_file_fails_loud_on_bad_mode(tmp_path, monkeypatch):
    p = tmp_path / "snap_token"
    real_chmod = os.chmod

    def bad_chmod(path, mode):
        real_chmod(path, 0o644)           # pretend the chmod to 0600 "failed"

    monkeypatch.setattr(session_module.os, "chmod", bad_chmod)   # session.py imported `os` as an attribute
    with pytest.raises(Exception):
        write_token_file(p, "tok")


session_module = sys.modules["mattarello.session"]


# =====================================================================
#  unit: Yes-tap confirmation
# =====================================================================
def test_wait_for_confirmation_returns_on_accept():
    t = FakeTransport()
    s = MachineSession(base_url="http://x", transport=t, heartbeat_interval=0.01)
    s.connect(token="")
    st = s.wait_for_confirmation(timeout=5.0, poll_interval=0.01)
    assert st.get("status") == "IDLE"
    assert s._beat_thread is not None        # heartbeat now running
    assert s._beat_thread.is_alive()         # ... and actually beating


def test_wait_for_confirmation_retries_until_accepted():
    t = FakeTransport(get_fail_times=3)
    s = MachineSession(base_url="http://x", transport=t, heartbeat_interval=0.01, sleep=lambda d: None)
    s.connect(token="")
    st = s.wait_for_confirmation(timeout=5.0, poll_interval=0.01)
    assert st.get("status") == "IDLE"
    gets = [c for c in t.calls if c[0] == "get"]
    assert len(gets) == 4                    # 3 not-yet (empty) + 1 accepted


def test_wait_for_confirmation_times_out():
    t = FakeTransport(get_fail_times=999)
    s = MachineSession(base_url="http://x", transport=t, heartbeat_interval=0.01, sleep=time.sleep)
    s.connect(token="")
    with pytest.raises(TimeoutError):
        s.wait_for_confirmation(timeout=0.15, poll_interval=0.02)


# =====================================================================
#  unit: alarm predicate
# =====================================================================
def test_alarm_detector_recognises_faults():
    d = AlarmDetector()
    assert d.is_alarm({"status": "ERROR"}) is True
    assert d.is_alarm({"errCode": 5}) is True
    assert d.is_alarm({"alarm": True}) is True
    assert d.is_alarm({"printStatus": "Failed"}) is True
    assert d.is_alarm({"status": "IDLE", "laserPower": 0, "errCode": 0}) is False
    assert d.is_alarm({"status": "RUNNING", "printStatus": "In Progress"}) is False
    assert d.is_alarm(None) is False
    assert d.is_alarm("nonsense") is False


# =====================================================================
#  unit: watchdog stop reasons (deterministic fake clock + injected halter)
# =====================================================================
def test_watchdog_stops_on_alarm():
    calls = []
    wd = Watchdog(halt=lambda reason, w: calls.append(reason), now=Clock(0.0), timeout=8.0)
    assert wd.check(now=0.0) is None
    wd.note({"status": "RUNNING", "errCode": 7}, now=0.0)
    assert wd.stopped and wd.stop_reason is StopReason.ALARM
    assert calls == [StopReason.ALARM]


def test_watchdog_stops_lost_link_when_unreachable():
    calls = []
    wd = Watchdog(halt=lambda reason, w: calls.append(reason), now=Clock(0.0), timeout=8.0)
    wd.note({"status": "RUNNING"}, now=0.0)     # last good telemetry at t=0
    wd.note_down(now=10.0, kind="link", error="Connection refused")
    assert wd.check(now=11.0) is not None       # 11-0 = 11s > 8s, and it was a link failure
    assert wd.stop_reason is StopReason.LOST_LINK and calls == [StopReason.LOST_LINK]


def test_watchdog_stops_silent_telemetry_when_stale():
    calls = []
    wd = Watchdog(halt=lambda reason, w: calls.append(reason), now=Clock(0.0), timeout=8.0)
    wd.note({"status": "RUNNING"}, now=0.0)
    wd.note_down(now=10.0, kind="silent", error="HTTP 503")
    assert wd.check(now=11.0) is not None
    assert wd.stop_reason is StopReason.SILENT_TELEMETRY and calls == [StopReason.SILENT_TELEMETRY]


def test_watchdog_user_stop_is_always_honoured():
    events = []
    wd = Watchdog(halt=lambda reason, w: None, now=Clock(0.0), timeout=8.0,
                  on_stop=lambda r, w: events.append(r))
    assert wd.stop(StopReason.USER) is StopReason.USER
    assert wd.stopped and wd.stop_reason is StopReason.USER and events == [StopReason.USER]


def test_watchdog_not_stopped_within_window():
    wd = Watchdog(now=Clock(0.0), timeout=8.0)
    wd.note({"status": "RUNNING"}, now=0.0)
    wd.note_down(now=5.0, kind="silent")
    assert wd.check(now=5.0) is None            # 5s < 8s: still within the fail-safe window
    assert not wd.stopped


def test_watchdog_stops_only_once_on_auto_path():
    calls = []
    wd = Watchdog(halt=lambda reason, w: calls.append(reason), now=Clock(0.0), timeout=8.0)
    wd.note({"status": "RUNNING"}, now=0.0)
    wd.note_down(now=10.0, kind="silent")
    assert wd.check(now=11.0) is not None
    assert wd.check(now=12.0) is not None       # already stopped -> reports, does not re-halt
    assert len(calls) == 1                       # halt issued exactly once


# =====================================================================
#  http: the full protocol against a stdlib http.server fake A250 (offline)
# =====================================================================
@pytest.fixture
def fake_a250():
    f = FakeA250().start()
    yield f
    f.stop()


def test_http_heartbeat_stays_alive(fake_a250):
    # a healthy, accepted session beats every 50 ms and must never flap to "lost"
    s = MachineSession(base_url=fake_a250.base_url(), heartbeat_interval=0.05, silence_threshold=0.4)
    events = []
    s.add_listener(events.append)
    s.connect(token="")
    fake_a250.tap_yes()                          # Yes-tap on the machine
    st = s.wait_for_confirmation(timeout=5.0, poll_interval=0.05)
    assert st.get("status") == "IDLE"
    time.sleep(0.25)                             # several successful heartbeats
    assert s.is_alive()
    assert not s._lost
    assert not any(isinstance(e, SessionLost) for e in events)
    assert fake_a250.stop_print_calls == 0       # nothing has asked the machine to stop
    s.close()


def test_http_silence_over_threshold_is_session_lost(fake_a250):
    # once the channel stops answering, >8s-equivalent silence loses the session (SPEC §5)
    # and the watchdog fails safe with SILENT_TELEMETRY (a 503 is "silent", not "link")
    s = MachineSession(base_url=fake_a250.base_url(), heartbeat_interval=0.05, silence_threshold=0.4)
    events = []
    s.add_listener(events.append)
    wd = Watchdog(transport=s.transport_for(), token=lambda: s.token, timeout=0.5)
    s.set_monitor(wd)
    s.connect(token="")
    fake_a250.tap_yes()
    assert s.wait_for_confirmation(timeout=5.0, poll_interval=0.05).get("status") == "IDLE"
    time.sleep(0.15)                             # a couple of good beats, then silence
    fake_a250.go_down()
    deadline = time.time() + 4.0
    while time.time() < deadline and not (s._lost and wd.stopped):
        time.sleep(0.02)
    assert s._lost
    assert not s.is_alive()
    assert any(isinstance(e, SessionLost) for e in events)
    assert wd.stopped and wd.stop_reason is StopReason.SILENT_TELEMETRY
    s.close()


def test_http_alarm_in_status_halts_machine(fake_a250):
    # the machine reports a fault in its status -> the watchdog halts with ALARM and the
    # stop is actually delivered to the (fake) machine
    s = MachineSession(base_url=fake_a250.base_url(), heartbeat_interval=0.05, silence_threshold=2.0)
    wd = Watchdog(transport=s.transport_for(), token=lambda: s.token, timeout=8.0)
    s.set_monitor(wd)
    s.connect(token="")
    fake_a250.tap_yes()
    assert s.wait_for_confirmation(timeout=5.0, poll_interval=0.05).get("status") == "IDLE"
    time.sleep(0.1)
    fake_a250.set_alarm(errCode=7, status="ERROR")   # the next heartbeat reads this alarm
    deadline = time.time() + 3.0
    while time.time() < deadline and not wd.stopped:
        time.sleep(0.02)
    assert wd.stopped
    assert wd.stop_reason is StopReason.ALARM
    assert fake_a250.stop_print_calls >= 1          # the halt reached the (fake) machine
    s.close()

