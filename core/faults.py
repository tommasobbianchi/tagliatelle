"""L8 · Fault injection (SPEC §10 #3) — silent telemetry, moved marker, moved workpiece,
lost camera → **stop and audit**, deterministically.

Reuses the L5 fail-safe machinery (`tools/mattarello`: `Watchdog` + `StopReason` + the
`MachineSession` telemetry forwarder) and drives it with a **manual clock** and an
**injected halter** — no threads, no wall clock, no real HTTP, no AI providers.  Each injected
fault either (a) lapses the watchdog's silence window (`silent_telemetry`) or (b) is detected from
the injected telemetry and issued as a distinct `StopReason`; every stop appends one audit entry.

The four SPEC §10 #3 faults map to four distinct, stable L5 `StopReason` values:

    silent_telemetry  -> StopReason.SILENT_TELEMETRY   (L5)
    moved_marker      -> StopReason.MOVED_MARKER       (fiducial drift   > MARKER_DRIFT_MM)
    moved_workpiece   -> StopReason.MOVED_WORKPIECE    (registered dev  > WORKPIECE_DRIFT_MM)
    lost_camera       -> StopReason.LOST_CAMERA        (vision telemetry unhealthy)
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# ---- make the sibling `tools/` package importable (core/ is not a python package) ----
_CORE_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = str(_CORE_DIR.parent / "tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from mattarello import MachineSession, StopReason, Watchdog  # noqa: E402

__all__ = [
    "FAULT_REASONS",
    "FAULTS",
    "MARKER_DRIFT_MM",
    "WORKPIECE_DRIFT_MM",
    "FaultHarness",
    "inject_fault",
    "sample_telemetry",
]

# Deterministic drift thresholds (mm) beyond which the fiducial / workpiece is "moved".
MARKER_DRIFT_MM = 0.5        # fiducial marker drift tolerated before stop
WORKPIECE_DRIFT_MM = 1.0     # registered vs current workpiece deviation before stop


FAULT_REASONS = {
    "silent_telemetry": StopReason.SILENT_TELEMETRY,
    "moved_marker": StopReason.MOVED_MARKER,
    "moved_workpiece": StopReason.MOVED_WORKPIECE,
    "lost_camera": StopReason.LOST_CAMERA,
}

#: The four SPEC §10 #3 faults, in order (the acceptance lists them exactly so).
FAULTS = ("silent_telemetry", "moved_marker", "moved_workpiece", "lost_camera")


# ---------------------------------------------------------------------------
# pure fault detection
# ---------------------------------------------------------------------------
def _drift(a, b) -> float:
    if a is None or b is None:
        return 0.0
    return round(((float(a[0]) - float(b[0])) ** 2 + (float(a[1]) - float(b[1])) ** 2) ** 0.5, 4)


def detect(fault: str, telemetry: dict | None) -> tuple[bool, str]:
    """Pure predicate: does this telemetry *trip* the given fault?  Returns ``(tripped, detail)``.

    Nothing here mutates or acts — it is a deterministic function of the injected telemetry, so a
    fault only stops when its threshold is actually crossed (a healthy reading never stops).
    """
    tel = telemetry or {}
    if fault == "silent_telemetry":
        up = tel.get("telemetry_up", False)
        return (not up), "heartbeat responses stopped arriving beyond the silence threshold"
    if fault == "moved_marker":
        d = _drift(tel.get("registered_mm"), tel.get("measured_mm"))
        return (d > MARKER_DRIFT_MM), "fiducial marker drifted %.4f mm (limit %.1f mm)" % (d, MARKER_DRIFT_MM)
    if fault == "moved_workpiece":
        d = _drift(tel.get("registered_mm"), tel.get("current_mm"))
        return (d > WORKPIECE_DRIFT_MM), "workpiece deviated %.4f mm from registration (limit %.1f mm)" % (d, WORKPIECE_DRIFT_MM)
    if fault == "lost_camera":
        ok = tel.get("camera_ok")
        return (bool(ok) is False), "camera/vision telemetry unhealthy (camera_ok=False)"
    raise KeyError("unknown fault %r (expected one of %s)" % (fault, ", ".join(FAULTS)))


def sample_telemetry(fault: str) -> dict:
    """A deterministic telemetry reading that *trips* the given fault (for injection / docs)."""
    if fault == "silent_telemetry":
        return {"telemetry_up": False}
    if fault == "moved_marker":
        return {"registered_mm": (95.0, 62.0), "measured_mm": (95.0, 63.1)}   # 1.1 mm drift
    if fault == "moved_workpiece":
        return {"registered_mm": (30.0, 10.0), "current_mm": (32.5, 10.0)}     # 2.5 mm deviation
    if fault == "lost_camera":
        return {"camera_ok": False}
    raise KeyError("unknown fault %r" % (fault,))


# ---------------------------------------------------------------------------
# the harness: one Manual clock + L5 Watchdog + MachineSession, all deterministic
# ---------------------------------------------------------------------------
class FaultHarness:
    """A deterministic fake-machine fault harness: a shared manual clock drives an L5
    `Watchdog` (the decision/stop/halt owner) and a `MachineSession` (the telemetry forwarder that
    carries `last_status` / `last_down_kind`).

    `inject(fault, telemetry)` drives the (fake) session with the fault's reading, lets the watchdog
    decide/act, and appends one audit entry.  Deterministic: the clock is manual, the halter is
    injected (no HTTP), and there are no threads.
    """

    def __init__(self, *, timeout: float = 8.0, clock: datetime | None = None, audit: list | None = None):
        self._clock = clock or datetime.utcnow
        self.audit: list = audit if audit is not None else []
        self._t = [0.0]
        nowfn = lambda: self._t[0]                       # manual clock (shared by watchdog + session)
        # injected halter: records the halt as data, never opens a socket.
        self.wd = Watchdog(now=nowfn, timeout=float(timeout),
                           halt=lambda reason, w: "halted")
        self.session = MachineSession(now=nowfn, sleep=lambda _s: None)
        self.session.set_monitor(self.wd)

    # -- manual clock ----------------------------------------------------------
    def advance(self, dt: float) -> float:
        self._t[0] += float(dt)
        return self._t[0]

    # -- injection -------------------------------------------------------------
    def inject(self, fault: str, telemetry: dict | None = None) -> dict:
        """Inject a fault: drive the (fake) session/telemetry, let the L5 watchdog decide.

        Returns a result dict with `fault`, `stopped`, `reason`, `reason_value`, `detail`, `entry`
        (the audit record) and `audit_len`.  When `telemetry` does not actually trip the fault
        (e.g. a healthy reading), `stopped` is False and no audit entry is written — the fail-safe
        never stops on a green reading.  Deterministic for a given (fault, telemetry).
        """
        tripped, detail = detect(fault, telemetry)
        if not tripped:
            return {"fault": fault, "stopped": False, "reason": None, "reason_value": None,
                    "detail": detail, "entry": None, "audit_len": len(self.audit)}

        if fault == "silent_telemetry":
            # one healthy reading (arms the window), then the link goes silent past the threshold.
            t0 = self.advance(0.0)
            self.session.last_status = {"status": "IDLE", "printStatus": None, "laserPower": 0}
            self.wd.note(self.session.last_status, t0)
            self.advance(self.wd.timeout + 1.0)                       # cross the silence threshold
            self.session.last_down_kind = "silent"
            # the session's failed-read path → watchdog note_down + check (decides SILENT_TELEMETRY)
            self.session._notify_monitor_down(self._t[0], "silent", exc=None)
        else:
            # a live, non-alarming reading that carries the anomaly → forward it, then issue the halt.
            t0 = self.advance(0.0)
            self.session.last_status = dict(telemetry or {})
            self.wd.note(self.session.last_status, t0)
            # L5 owns the halt: idempotent stop() records the reason + (injected) halter outcome.
            self.wd.stop(FAULT_REASONS[fault])

        reason = self.wd.stop_reason
        if reason is None:
            reason = FAULT_REASONS[fault]

        stamp = self._clock()
        entry = {
            "event": "fault_stop",
            "fault": fault,
            "stop_reason": reason.value,
            "detail": detail,
            "halt": [dict(h) for h in self.wd.halt_outcome],
            "session_lost": bool(self.session._lost),
            "date": stamp.isoformat() if hasattr(stamp, "isoformat") else str(stamp),
        }
        self.audit.append(entry)
        return {"fault": fault, "stopped": True, "reason": reason, "reason_value": reason.value,
                "detail": detail, "entry": entry, "audit_len": len(self.audit)}

    def reset(self) -> None:
        self.wd.reset()
        self.audit.clear()


def inject_fault(fault: str, telemetry: dict | None = None, **kw) -> dict:
    """One-shot convenience: run a fresh `FaultHarness` for a single fault and return the result."""
    return FaultHarness(**kw).inject(fault, telemetry or sample_telemetry(fault))
