"""L5 \u00b7 il Mattarello \u2014 Snapmaker HTTP session: token, heartbeat, Yes-tap, loss.

Deterministic and offline-testable: every HTTP call goes through an injectable
transport (default: stdlib ``urllib`` against ``base_url``), the clock and the
sleep are injectable, and nothing here requires a real machine.  The test-suite
(see ``test_session.py``) points this at a stdlib ``http.server`` fake A250.

Protocol (measured; see ``tools/executor/snap.py`` + ``HANDOFF.md`` prediction #11):
  POST /api/v1/connect       token=...            -> {token, series, headType}
  GET  /api/v1/status        ?token=<ts>          -> JSON status while the session is accepted
  POST /api/v1/prepare_print token,type,file      -> "Prepare successfully"
  POST /api/v1/start_print   token=...            -> {"code":0}
  POST /api/v1/stop_print    token=...            -> {"code":0}
  POST /api/v1/disconnect    token=...

SPEC invariants honoured here (docs/SPEC.md \u00a75):
  * the token lives on the RPi only, file mode 0600 (os.chmod), presented to the machine once;
  * heartbeat ``GET /status`` every 2 s; silence > 8 s is a LOST session, never "all ok";
  * a physical Yes-tap on the machine is what turns a freshly-minted token into an accepted session.
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# --- HTTP surface (mirrors snap.py) -------------------------------------------------------
CONNECT = "/api/v1/connect"
STATUS = "/api/v1/status"
PREPARE = "/api/v1/prepare_print"
START = "/api/v1/start_print"
STOP = "/api/v1/stop_print"
DISCONNECT = "/api/v1/disconnect"

DEFAULT_HEARTBEAT = 2.0        # s, Luban / A250 measured cadence (HANDOFF #11)
DEFAULT_SILENCE = 8.0          # s; > 8 s with no heartbeat = session lost (SPEC \u00a75)
DEFAULT_TIMEOUT = 6.0          # s, per-request HTTP timeout


class MachineSessionError(Exception):
    """A machine/session-level failure that callers may want to distinguish from logic errors."""


class MachineNotAccepted(MachineSessionError):
    """:meth:`MachineSession.status` raised while the session has not been accepted yet
    (fresh token without the Yes-tap) \u2014 the machine answers with an empty / non-JSON body."""


def _maybe_json(body) -> dict | str | None:
    """Best-effort decode of a body into a dict; ``None`` when empty, the raw text when
    not JSON (the A250 returns an empty / odd body until the Yes-tap is made, measured)."""
    if body is None:
        return None
    s = (body if isinstance(body, (bytes, bytearray)) else body)
    if not s:
        return None
    text = s.decode("utf-8", "replace").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def write_token_file(path, token: str) -> Path:
    """Persist a session token with owner-only perms (mode 0600) \u2014 SPEC: the token stays on
    the RPi only.  The chmod is *verified*: if it did not take effect we fail loud, because a
    world-readable laser-session token is a data / safety regression."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(token) + "\n")
    os.chmod(path, 0o600)
    actual = stat.S_IMODE(path.stat().st_mode)
    if actual != 0o600:
        raise MachineSessionError("token file %s is mode %s, expected 0600" % (path, oct(actual)))
    return path


def _down_kind(exc: BaseException) -> str:
    """Classify a failed telemetry read as a dropped *link* vs a live-but-unhealthy channel.
    A real HTTP answer (5xx) means the machine is reachable but refuses/has expired the
    session; a socket-level failure means we cannot reach it at all."""
    if isinstance(exc, urllib.error.HTTPError):
        return "silent"
    if isinstance(exc, (urllib.error.URLError, socket.timeout, http.client.RemoteDisconnected, OSError)):
        return "link"
    return "silent"


class SessionEvent:
    """Base for every event a :class:`MachineSession` emits to its listeners."""
    kind = "session_event"
    __slots__ = ("ts", "detail")

    def __init__(self, ts: float = 0.0, detail: str = ""):
        self.ts = ts            # caller-supplied clock (monotonic by default)
        self.detail = detail

    def describe(self) -> str:
        return "%s kind=%s detail=%r" % (type(self).__name__, self.kind, self.detail)

    def __repr__(self):  # pragma: no cover - cosmetic
        return self.describe()


class SessionConnected(SessionEvent):
    kind = "connected"


class SessionAccepted(SessionEvent):
    kind = "accepted"


class SessionLost(SessionEvent):
    """Emitted once when heartbeat silence exceeds the threshold (SPEC \u00a75: the silence is never 'all ok')."""
    kind = "session_lost"


class SessionStopped(SessionEvent):
    kind = "stopped"


class HttpTransport:
    """Minimal stdlib HTTP transport.  ``get``/``post_form`` return raw response bytes and let
    4xx/5xx raise (``urllib.error.HTTPError``), which the session treats as a failed read.
    Injecting a different transport object (with the same three methods) is how the tests run offline."""

    def __init__(self, base_url: str, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout

    def url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return self.base_url + path

    def get(self, path: str) -> bytes:
        req = urllib.request.Request(self.url(path), method="GET")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read()

    def post_form(self, path: str, **fields) -> bytes:
        body = urllib.parse.urlencode(fields).encode("utf-8")
        req = urllib.request.Request(
            self.url(path), data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read()

    def post_file(self, path: str, fields, filename: str, content) -> bytes:
        import uuid
        boundary = uuid.uuid4().hex.encode()
        parts = b"".join(
            b"--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
            % (boundary, k.encode("utf-8"), v if isinstance(v, (bytes, bytearray)) else str(v).encode("utf-8"))
            for k, v in fields.items()
        )
        parts += (b"--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                  b"Content-Type: application/octet-stream\r\n\r\n" % (boundary, filename.encode("utf-8")))
        parts += (content if isinstance(content, (bytes, bytearray)) else content.encode("utf-8"))
        parts += b"\r\n--%s--\r\n" % boundary
        req = urllib.request.Request(
            self.url(path), data=parts, method="POST",
            headers={"Content-Type": "multipart/form-data; boundary=" + boundary.decode("ascii")},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read()


class MachineSession:
    """Manage one Snapmaker session over HTTP: present the token once, heartbeat every 2 s,
    detect a lost link, and (for active jobs) wait for the physical Yes-tap before starting.

    The *monitor* (the watchdog) is duck-typed: if set, the session forwards each status to
    ``monitor.note(status, now)``, each failure to ``monitor.note_down(now, kind)``, and ticks
    ``monitor.check(now)`` every beat so it can stop on its own telemetry/alarm rules.
    """

    def __init__(self, base_url: str | None = None, *, transport=None,
                 heartbeat_interval: float = DEFAULT_HEARTBEAT,
                 silence_threshold: float = DEFAULT_SILENCE,
                 token_file: str | Path | None = None,
                 persist_token: bool = False,
                 monitor=None,
                 now=time.monotonic,
                 sleep=time.sleep):
        self._base_url = base_url
        self._transport = transport
        self.heartbeat_interval = max(0.0, float(heartbeat_interval))
        self.silence_threshold = float(silence_threshold)
        self._token_file = Path(token_file) if token_file is not None else None
        self._persist_token = bool(persist_token)
        self._monitor = monitor
        self._now = now
        self._sleep = sleep

        # live state
        self.token: str | None = None
        self._token_presented = False
        self.connect_info: dict | None = None
        self.last_status: dict | None = None
        self.last_error: str | None = None
        self.last_down_kind: str | None = None  # "link" | "silent" from the most recent failed read
        self._last_ok: float | None = None      # last *successful heartbeat* (status) time
        self._lost = False
        self._stopped = threading.Event()
        self._beat_thread: threading.Thread | None = None
        self._listeners: list = []
        self._listener_lock = threading.Lock()
        self._token_lock = threading.RLock()

    # -- plumbing ---------------------------------------------------------------
    def transport_for(self):
        t = self._transport
        if t is None:
            if not self._base_url:
                raise MachineSessionError("connect() needs a base_url (or an injected transport)")
            self._transport = HttpTransport(self._base_url)
            t = self._transport
        return t

    def set_monitor(self, monitor) -> "MachineSession":
        self._monitor = monitor
        return self

    def _post_form(self, path: str, **fields) -> bytes:
        return self.transport_for().post_form(path, **fields)

    def _get(self, path: str) -> bytes:
        return self.transport_for().get(path)

    # -- tokens -----------------------------------------------------------------
    def _set_token(self, token):
        with self._token_lock:
            self.token = token

    def _persist(self):
        """Persist the token file *only* when we are the RPi agent (``persist_token`` + path).
        The token is otherwise kept in memory only, per the SPEC (RPi-held, mode 600)."""
        if not (self._persist_token and self._token_file is not None and self.token):
            return
        with self._token_lock:
            write_token_file(self._token_file, self.token)

    # -- events -----------------------------------------------------------------
    def add_listener(self, fn):
        with self._listener_lock:
            self._listeners.append(fn)
            return fn

    def remove_listener(self, fn):
        with self._listener_lock:
            if fn in self._listeners:
                self._listeners.remove(fn)

    def _emit(self, event):
        with self._listener_lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(event)
            except Exception:                      # a crashing subscriber must not kill the beat
                pass

    # -- connection / token presenting ------------------------------------------
    def _present_once(self, tok: str):
        """One /connect with ``tok`` (present-the-token-once); returns ``(info, effective_token)``."""
        body = self._post_form(CONNECT, token=tok)
        info = _maybe_json(body)
        info = info if isinstance(info, dict) else {}
        effective = info.get("token") or tok
        return info, effective

    def connect(self, base_url: str | None = None, token: str | None = None) -> dict:
        """Establish the HTTP session and present the token.

        * ``token`` empty/None \u2192 fresh session: one /connect with an empty token mints a new one,
          which we then present *exactly once* (the measured Yes-tap flow, HANDOFF #11).
        * ``token`` non-empty \u2192 a known token is presented *once*.

        A successful /connect only proves the link is up; it does **not** prove the Yes-tap was made.
        Use :meth:`wait_for_confirmation` for that (fresh sessions)."""
        if base_url is not None:
            self._base_url = base_url
            self._transport = None                    # rebuild transport from the new base_url
        tok = (token if token is not None else "").strip()
        first_info, effective = self._present_once(tok)
        if tok == "" and effective and effective != tok:
            # a fresh token was minted -> present THAT one, exactly once
            second_info, effective = self._present_once(effective)
            first_info = {**first_info, **second_info}
        self._set_token(effective or None)
        self._token_presented = True
        self.connect_info = {**first_info, "token": self.token}
        self._persist()
        self._emit(SessionConnected(ts=self._now(), detail="connected"))
        return self.connect_info

    # -- telemetry --------------------------------------------------------------
    def status(self) -> dict:
        """Read machine status.  Raises :class:`MachineNotAccepted` while the session is not yet
        accepted, or an ``urllib.error`` when the machine refuses / the link is down; the caller
        treats either as lost telemetry.  A success advances the liveness clock and forwards the
        reading to the monitor (watchdog)."""
        path = "%s?token=%s&%d" % (STATUS, urllib.parse.quote(self.token or ""), int(self._now() * 1000))
        body = self._get(path)
        st = _maybe_json(body)
        if not isinstance(st, dict):
            raise MachineNotAccepted("status not accepted yet (%r)" % (st,))
        self._last_ok = self._now()
        self.last_status = st
        self._lost = False
        if self._monitor is not None:
            try:
                self._monitor.note(st, self._now())
            except Exception:
                pass
        return st

    def is_alive(self) -> bool:
        """True iff a heartbeat (status read) succeeded within ``silence_threshold`` of ``now``."""
        if self._lost or self._last_ok is None:
            return False
        return (self._now() - self._last_ok) <= self.silence_threshold

    # -- heartbeat loop ---------------------------------------------------------
    def start_heartbeat(self) -> "MachineSession":
        """Start the 2 s heartbeat loop (daemon thread).  Idempotent; safe to re-arm after a halt."""
        self._stopped.clear()
        if self._beat_thread is not None and self._beat_thread.is_alive():
            return self
        self._beat_thread = threading.Thread(target=self._beat, name="mattarello-heartbeat", daemon=True)
        self._beat_thread.start()
        return self

    def halt_heartbeat(self) -> None:
        self._stopped.set()

    def _beat(self):
        while not self._stopped.wait(self.heartbeat_interval if self.heartbeat_interval > 0 else 1.0):
            try:
                self.status()
            except Exception as e:
                self.last_error = repr(e)
                self.last_down_kind = _down_kind(e)
                self._notify_monitor_down(self._now(), self.last_down_kind, e)
            else:
                if self._monitor is not None:
                    try:
                        self._monitor.check(self._now())
                    except Exception:
                        pass
            # The silence check runs every beat (even after a success, where it is a no-op because
            # status() just advanced _last_ok): silence > threshold is a LOST session, once.
            if self._last_ok is not None and (self._now() - self._last_ok) > self.silence_threshold \
                    and not self._lost:
                self._mark_lost(self._now())

    def _notify_monitor_down(self, now: float, kind: str, exc: BaseException | None) -> None:
        if self._monitor is None:
            return
        try:
            self._monitor.note_down(now, kind, error=(repr(exc) if exc is not None else "session lost"))
            self._monitor.check(now)
        except Exception:
            pass

    def _mark_lost(self, now: float) -> None:
        self._lost = True
        self._emit(SessionLost(ts=now, detail="no heartbeat for >%.0f s" % self.silence_threshold))
        self._notify_monitor_down(now, self.last_down_kind or "link", None)

    # -- confirmation (Yes-tap) -------------------------------------------------
    def wait_for_confirmation(self, timeout: float = 120.0, poll_interval: float | None = None) -> dict:
        """Wait for the physical Yes-tap on the machine (a fresh token becoming accepted).

        Until the owner taps Yes, ``/status`` answers empty / non-JSON; we poll until it returns a
        dict, then emit :class:`SessionAccepted`, start the heartbeat, and return the accepted status.
        For an *already-accepted* token this returns on the first poll.  Raises :class:`TimeoutError`
        if the tap never arrives within ``timeout`` seconds (SPEC: no tap => no session)."""
        poll = self.heartbeat_interval if poll_interval is None else float(poll_interval)
        poll = max(0.0, poll)
        deadline = self._now() + max(0.0, float(timeout))
        while True:
            try:
                st = self.status()
            except Exception as e:
                self.last_error = repr(e)
                st = None
            if isinstance(st, dict):
                self._emit(SessionAccepted(ts=self._now(), detail="Yes-tap confirmed on machine"))
                self._persist()
                self.start_heartbeat()
                return st
            if self._now() >= deadline:
                raise TimeoutError("session not confirmed (Yes-tap) within %.1f s" % float(timeout))
            self._sleep(poll if poll > 0 else 0.02)

    # -- job control ------------------------------------------------------------
    def prepare_print(self, path, type_: str = "Laser") -> str:
        """Upload a file so it shows on the touchscreen (never starts it)."""
        p = Path(path)
        body = self.transport_for().post_file(PREPARE, {"token": self.token or "", "type": type_}, p.name,
                                              p.read_bytes())
        return body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body)

    def start_print(self) -> str:
        body = self._post_form(START, token=self.token or "")
        return body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body)

    def stop_print(self) -> str:
        body = self._post_form(STOP, token=self.token or "")
        return body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body)

    def disconnect(self) -> str:
        self.halt_heartbeat()
        try:
            body = self._post_form(DISCONNECT, token=self.token or "")
            return body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body)
        finally:
            self._emit(SessionStopped(ts=self._now(), detail="disconnected"))

    def close(self) -> None:
        self.halt_heartbeat()
        if self._beat_thread is not None:
            self._beat_thread.join(timeout=1.0)

    def __repr__(self):  # pragma: no cover - cosmetic
        return ("MachineSession(url=%s, token=%s, alive=%s, lost=%s)"
                % (self._base_url, bool(self.token), self.is_alive(), self._lost))
