"""L5 \u00b7 il Mattarello \u2014 fail-safe watchdog: heartbeat timeout, alarms, remote stop.

Reactive by design: it is *driven* by the session's telemetry (``note`` / ``note_down``) and by
explicit operator input (``stop(USER)``).  It owns no threads and no timers, so it is trivially
deterministic under an injected clock.  SPEC \u00a75: "the silence is never 'all ok'"; loss of telemetry
or of the connection counts as a stop/pause \u2014 it is never a green light.

``stop()`` issues the halt over the same HTTP surface the executor uses (``/api/v1/stop_print``,
plus a best-effort ``/api/v1/emergency_stop``).  ``tools/executor/snap.py`` has no dedicated
``stop()`` method, so this *reuses its mechanism* (POST the stop endpoint with the session token)
rather than importing it (which would drag in ``SNAP_HOST`` / the token file).  A halt must never
fail silently: the reason and the per-endpoint outcome are recorded on ``halt_outcome`` and reported
to ``on_stop`` even if every HTTP call fails.
"""
from __future__ import annotations

import enum
import time

DEFAULT_TIMEOUT = 8.0                    # s; watchdog telemetry timeout (SPEC \u00a75)
DEFAULT_HALT_ENDPOINTS = ("/api/v1/stop_print", "/api/v1/emergency_stop")


class StopReason(enum.Enum):
    SILENT_TELEMETRY = "silent_telemetry"   # link up, but status stopped advancing / expired
    ALARM = "alarm"                          # the machine reported a fault in its status
    USER = "user"                            # operator / gate requested the halt
    LOST_LINK = "lost_link"                  # could not reach the machine at all


ALARM_STATUS_WORDS = frozenset({"ERROR", "ALARM", "ABORT", "ABORTED", "FAULT", "FAULTED", "CRITICAL"})
ALARM_PRINT_STATUS = frozenset({"ERROR", "FAILED", "FAULT", "CRITICAL"})


class AlarmDetector:
    """Deterministic predicate: does this status reading carry a machine alarm?

    Recognises the common A250 / Luban spellings (an ``alarm`` flag, a non-zero ``errCode``,
    a faulting ``status``, or a failed ``printStatus``) without depending on hardware."""

    def is_alarm(self, st) -> bool:
        if not isinstance(st, dict):
            return False
        a = st.get("alarm")
        if a is True:
            return True
        if isinstance(a, str) and a.strip().lower() in ("true", "1", "yes"):
            return True
        code = st.get("errCode", st.get("error_code"))
        if code is not None:
            if isinstance(code, bool):
                return code
            if isinstance(code, (int, float)):
                return code != 0
            if isinstance(code, str) and code.strip().lower() not in ("", "0", "none", "ok", "null"):
                return True
        s = st.get("status")
        if isinstance(s, str) and s.strip().upper() in ALARM_STATUS_WORDS:
            return True
        ps = st.get("printStatus")
        if isinstance(ps, str) and ps.strip().upper() in ALARM_PRINT_STATUS:
            return True
        return False


class Watchdog:
    """Fail-safe driver for the session's telemetry.  Feed it status with :meth:`note`, failures with
    :meth:`note_down`; it decides and self-stops on alarm or a stale/lost telemetry window, or you
    command it with :meth:`stop` (e.g. ``USER``)."""

    def __init__(self, *, transport=None, token=None, halt=None,
                 now=time.monotonic, timeout: float = DEFAULT_TIMEOUT,
                 halt_endpoints=DEFAULT_HALT_ENDPOINTS,
                 on_stop=None, alarm=None):
        self._transport = transport
        self._token = token                     # str, or callable -> current token
        self._halt = halt                        # optional pre-built halter: (reason, watchdog) -> any
        self._now = now
        self.timeout = float(timeout)
        self.halt_endpoints = tuple(halt_endpoints)
        self._on_stop = on_stop
        self.alarm = alarm or AlarmDetector()

        # live state
        self.last_status: dict | None = None
        self.last_ok: float | None = None
        self.last_down_kind: str | None = None   # "link" | "silent"
        self.last_error: str | None = None
        self.stopped = False
        self.stop_reason: StopReason | None = None
        self.halt_outcome: list = []

    # -- token -----------------------------------------------------------------
    def _cur_token(self):
        t = self._token() if callable(self._token) else self._token
        return t or ""

    # -- detection (state) -----------------------------------------------------
    def note(self, status, now: float | None = None):
        """A successful telemetry read.  Advances the liveness clock; stops immediately on alarm."""
        now = self._now() if now is None else now
        self.last_status = status
        self.last_ok = now
        self.last_error = None
        if not self.stopped and self.alarm.is_alarm(status):
            self.stop(StopReason.ALARM)

    def note_down(self, now: float | None = None, kind: str = "link", error=None):
        """A failed telemetry read.  ``kind`` is "link" (machine unreachable) or "silent" (answered
        but unhealthy) and decides the fail-safe reason should the window lapse."""
        now = self._now() if now is None else now
        self.last_down_kind = kind
        self.last_error = error

    # -- decision --------------------------------------------------------------
    def should_stop(self, now: float | None = None) -> StopReason | None:
        """The reason that *warrants* a halt at ``now``, or ``None``.  Pure \u2014 it inspects state but
        does not act and does not depend on whether we are already stopped."""
        if self.alarm.is_alarm(self.last_status):
            return StopReason.ALARM
        now = self._now() if now is None else now
        if self.last_ok is not None and (now - self.last_ok) > self.timeout:
            if self.last_down_kind == "link":
                return StopReason.LOST_LINK
            return StopReason.SILENT_TELEMETRY
        return None

    def check(self, now: float | None = None) -> StopReason | None:
        """Evaluate and, if a halt is warranted and we are not already stopped, issue it."""
        if self.stopped:
            return self.stop_reason
        reason = self.should_stop(now)
        return self.stop(reason) if reason is not None else None

    # -- action ----------------------------------------------------------------
    def stop(self, reason) -> StopReason:
        """Issue the halt over HTTP (best-effort, recorded) and report it.  Idempotent; may be
        called directly (e.g. ``USER``) or be the outcome of :meth:`check` / :meth:`note`."""
        if not isinstance(reason, StopReason):
            reason = StopReason(reason)
        self.halt_outcome = self._issue_halt(reason)
        first = not self.stopped
        self.stopped = True
        self.stop_reason = reason
        self.last_error = None
        if self._on_stop is not None:
            try:
                self._on_stop(reason, self)
            except Exception:
                pass
        return reason

    def _issue_halt(self, reason: StopReason) -> list:
        results: list = []
        if self._halt is not None:               # injected halter (unit tests / custom backends)
            try:
                r = self._halt(reason, self)
                results.append({"kind": "injector", "reason": reason.value, "result": r})
            except Exception as e:
                results.append({"kind": "injector", "reason": reason.value, "error": repr(e)})
            return results
        if self._transport is None:
            results.append({"kind": "halt", "reason": reason.value, "error": "no transport configured"})
            return results
        tok = self._cur_token()
        for ep in self.halt_endpoints:
            try:
                body = self._transport.post_form(ep, token=tok)
                body = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else body
                results.append({"endpoint": ep, "reason": reason.value, "ok": True, "body": str(body)[:120]})
            except Exception as e:
                results.append({"endpoint": ep, "reason": reason.value, "ok": False, "error": repr(e)})
        return results

    # -- lifecycle -------------------------------------------------------------
    def reset(self) -> None:
        self.stopped = False
        self.stop_reason = None
        self.last_ok = None
        self.last_down_kind = None
        self.last_status = None
        self.last_error = None
        self.halt_outcome = []

    def close(self) -> None:
        self.reset()

    def __repr__(self):  # pragma: no cover - cosmetic
        return ("Watchdog(timeout=%.1f, stopped=%s, reason=%s)"
                % (self.timeout, self.stopped, self.stop_reason.value if self.stop_reason else None))
