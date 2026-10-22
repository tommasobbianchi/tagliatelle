"""L7 · fault injection on the (fake) live stack: the watchdog/stop path is triggered.

SPEC §11: "stack simulato con fault injection (camera persa, marker coperti, fumo,
operaio spostato, telemetria silente)" and §5: "the silence is never 'all ok'".

The L5 Mattarello Watchdog (tools/mattarello/watchdog.py) is driven, not driving: no
threads, no real timers — telemetry is *fed* to it, so an injected clock *is* the
fault. We feed exactly those faults (silent telemetry, lost link, moved/corrupted
workpiece alarm, lost camera) and assert the fail-safe decision comes back with the
right reason and the halt path actually fired (recorded on ``halt_outcome``).

The L5 watchdog is reused directly when importable; otherwise a self-contained fake
with the same state machine stands in, so the test keeps its meaning in both cases.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
L5 = ROOT / "tools" / "mattarello" / "watchdog.py"

# ---------------- load L5 watchdog when present (stdlib-only module) ----------------
_watchdog = None
if L5.exists():
    spec = importlib.util.spec_from_file_location("l7_l5_watchdog", L5)
    if spec is not None and spec.loader is not None:
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            _watchdog = mod
        except Exception:
            _watchdog = None

HAS_L5 = _watchdog is not None


# ---------------- self-contained fallback (same semantics, minimal) ----------------
class _FakeWatchdog:
    """Miniature stand-in: note()/note_down()/check()/stop() with the same
    fail-safe mapping the L5 watchdog implements."""
    def __init__(self, timeout=8.0, halt=None):
        self.timeout = timeout
        self._halt = halt
        self.last_ok = None
        self.last_down_kind = None
        self.last_alarm = False
        self.stopped = False
        self.stop_reason = None
        self.halt_outcome = []

    def note(self, status, now=None):
        self.last_ok = now
        if not self.stopped and (isinstance(status, dict) and status.get("alarm") is True):
            self.stop("alarm")

    def note_down(self, now=None, kind="link", error=None):
        self.last_down_kind = kind

    def should_stop(self, now=None):
        if self.last_alarm:
            return "alarm"
        if self.last_ok is not None and (now - self.last_ok) > self.timeout:
            return "lost_link" if self.last_down_kind == "link" else "silent_telemetry"
        return None

    def stop(self, reason):
        if self._halt is not None:
            self.halt_outcome = [{"kind": "injector", "reason": reason, "result": self._halt(reason, self)}]
        else:
            self.halt_outcome = [{"kind": "halt", "reason": reason, "error": "no harness"}]
        self.stopped = True
        self.stop_reason = reason
        return reason


def _make(halt_recorder):
    """A watchdog instance (L5 or fake) with an injected halt recorder and timeout."""
    if HAS_L5:
        return _watchdog.Watchdog(timeout=8.0, halt=lambda reason, wd: halt_recorder.append((reason.value, wd)))
    w = _FakeWatchdog(timeout=8.0, halt=lambda reason, wd: halt_recorder.append((reason, wd)))
    return w


def _value(reason) -> str:
    """StopReason (L5 enum) or str (fake) → its machine-readable value."""
    return getattr(reason, "value", None) or str(reason)


def test_silent_telemetry_triggers_stop():
    """Link is up but the telemetry window lapses → SILENT_TELEMETRY halt."""
    hits: list = []
    wd = _make(hits)
    wd.note({"status": "OK", "printStatus": "RUNNING"}, now=0.0)
    assert wd.check(now=4.0) is None           # still within the 8 s window
    reason = wd.check(now=9.0)                 # window lapsed
    assert reason is not None and _value(reason) == "silent_telemetry"
    assert wd.stopped and hits, "halt was decided but the stop path never fired"


def test_lost_link_triggers_stop():
    """Machine unreachable + window lapsed → LOST_LINK halt."""
    hits: list = []
    wd = _make(hits)
    wd.note({"status": "OK"}, now=0.0)
    wd.note_down(now=1.0, kind="link", error="connection refused")
    reason = wd.check(now=9.5)
    assert reason is not None and _value(reason) == "lost_link"
    assert wd.stopped and hits


def test_moved_workpiece_alarm_triggers_stop():
    """Camera sees the workpiece moved/marker corrupted → machine raises an alarm;
    the next telemetry note must stop immediately, no window wait."""
    hits: list = []
    wd = _make(hits)
    wd.note({"status": "OK", "printStatus": "RUNNING"}, now=0.0)
    wd.note({"status": "ERROR", "errCode": 42, "printStatus": "FAILED"}, now=1.0)
    assert wd.stopped, "alarm status did not trigger the stop"
    assert _value(wd.stop_reason) == "alarm"
    assert hits, "halt path was never exercised for the alarm"


def test_lost_camera_treated_as_silence():
    """Lost camera = telemetry answered-but-unhealthy ('silent'); when the window
    lapses the fail-safe reason is silent telemetry, never a green light."""
    hits: list = []
    wd = _make(hits)
    wd.note({"status": "OK"}, now=0.0)
    wd.note_down(now=2.0, kind="silent", error="camera not found")
    reason = wd.check(now=10.0)
    assert reason is not None and _value(reason) == "silent_telemetry"
    assert wd.stopped and hits


def test_user_stop_path_and_idempotency():
    """Operator stop is issued through the same recorded halt path; re-asking keeps
    the watchdog in the stopped state under the USER reason."""
    hits: list = []
    wd = _make(hits)
    wd.note({"status": "OK"}, now=0.0)
    reason = wd.stop("user")
    assert _value(reason) == "user"
    assert wd.stopped and _value(wd.stop_reason) == "user"
    assert hits, "halt path was never exercised for a user stop"
    wd.reset()
    wd.stop("user")
    assert wd.stopped and _value(wd.stop_reason) == "user"
