"""L5 \u00b7 il Mattarello \u2014 Snapmaker session + fail-safe watchdog (offline-testable).

Public surface:
  * :class:`MachineSession`  \u2014 Snaphaker/``A250`` HTTP session: connect + token-once, heartbeat,
    Yes-tap confirmation, loss detection.
  * :class:`Watchdog`        \u2014 fail-safe driver: telemetry/alarm timeout + remote ``stop()``.
  * :class:`StopReason`      \u2014 why the job stopped (silent_telemetry | alarm | user | lost_link).
  * :class:`AlarmDetector`   \u2014 deterministic "does this status carry a machine alarm?".
  * event types              \u2014 :class:`SessionLost`, :class:`SessionAccepted`, :class:`SessionConnected`,
    :class:`SessionStopped`.

Offline-testable: everything here takes an injectable transport, clock and sleep; the test-suite
runs the full protocol against a stdlib ``http.server`` fake A250 with no real hardware.
"""
from __future__ import annotations

from .session import (
    CONNECT,
    STATUS,
    PREPARE,
    START,
    STOP,
    DISCONNECT,
    DEFAULT_HEARTBEAT,
    DEFAULT_SILENCE,
    DEFAULT_TIMEOUT,
    HttpTransport,
    MachineSession,
    MachineSessionError,
    MachineNotAccepted,
    SessionEvent,
    SessionConnected,
    SessionAccepted,
    SessionLost,
    SessionStopped,
    write_token_file,
)
from .watchdog import Watchdog, StopReason, AlarmDetector, DEFAULT_HALT_ENDPOINTS

__all__ = [
    "CONNECT", "STATUS", "PREPARE", "START", "STOP", "DISCONNECT",
    "DEFAULT_HEARTBEAT", "DEFAULT_SILENCE", "DEFAULT_TIMEOUT", "DEFAULT_HALT_ENDPOINTS",
    "HttpTransport", "MachineSession", "MachineSessionError", "MachineNotAccepted",
    "SessionEvent", "SessionConnected", "SessionAccepted", "SessionLost", "SessionStopped",
    "write_token_file", "Watchdog", "StopReason", "AlarmDetector",
]

__version__ = "0.1.0"
