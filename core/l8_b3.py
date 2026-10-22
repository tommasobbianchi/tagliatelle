"""L8 · Integration · B3 vertical — end-to-end acceptance driven against a FAKE machine.

This is the integration deliverable for lane L8: it wires the *already merged* deterministic core
(spec 0.2.0 → 0.3.0, grid, gate, 0.3.0 compiler, replay, active-job scan) into the single B3
acceptance path (SPEC §10 #1), and runs the machine half against a local `http.server` stand-in for
the Snapmaker A250 (the L5 `tools/mattarello` session + watchdog — no real hardware, all stdlib).

`run_b3_fake(interview)` produces, in order, the eight B3 outputs:
   1. the interview input (echoed back);
   2. the engraved-label grid (`grid.generate_grid`);
   3. the replay preview with per-op estimated times (`replay.replay_gcode`);
   4. the approval gate — spec hash + a physical Yes-tap confirmation (the fake machine's tap);
   5. the G-code (`compiler2.compile_jobspec2`);
   6. the "active job" verdict (`gcode_scan.is_active`);
   7. the simulated session — fake server, heartbeat, L5 Watchdog, a complete prepare/start/stop;
   8. a cell chosen by typing its coordinates (`choose_cell`) and the recipe proposal saved on approval.

Fail-safe: if the gate reports any blocker, `run_b3_fake` refuses *before* any machine interaction
(no fake server is even started, no G-code compiled). Deterministic and offline: no AI-provider
imports, no real network, no wall-clock-dependent values in the result.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ---- make the sibling `tools/` package importable (core/ is not a python package) ----
_CORE_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = str(_CORE_DIR.parent / "tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from grid import generate_grid                       # noqa: E402
from jobspec import FOCAL_Z_MM                        # noqa: E402
from jobspec2 import JobSpec2, migrate_020_to_030, spec_hash2  # noqa: E402
from materials import power_cap                     # noqa: E402
from compiler2 import compile_jobspec2              # noqa: E402
from replay import replay_gcode                     # noqa: E402
from gcode_scan import is_active                    # noqa: E402
from mattarello import MachineSession, Watchdog     # noqa: E402

#: Deterministic A250 default laser power, in percent (below the "safe" cap of 60).
DEFAULT_POWER_PCT = 30.0
DEFAULT_SPEED_MM_MIN = 3000.0
DEFAULT_PASSES = 1
DEFAULT_PARAMS_VERSION = "seed-405-v1"

#: mm; deterministic left/bottom headroom so the grid's engraved labels (left & below) stay >= 0.
_MIN_LEFT_MM = 30.0
_MIN_BOTTOM_MM = 10.0

__all__ = [
    "run_b3_fake",
    "choose_cell",
    "recipe_proposal",
    "gate_blockers2",
    "build_spec",
    "safe_origin",
    "FakeA250Server",
]


# ---------------------------------------------------------------------------
# geometry: place the grid inside the frozen contour, leaving label headroom
# ---------------------------------------------------------------------------
def safe_origin(contour_mm, grid_w: float, grid_h: float) -> tuple[float, float]:
    """Absolute grid origin (x, y) in bed mm.

    Centers the grid in the contour's axis-aligned bounding box, then clamps so the *engraved
    labels* (which sit to the LEFT and BELOW the grid, see grid.generate_grid) remain in-bounds —
    the compiler/simulator reject negative or off-bed coordinates, so the origin carries that margin.
    Deterministic: pure function of the contour and the grid size.
    """
    xs = [float(p[0]) for p in contour_mm]
    ys = [float(p[1]) for p in contour_mm]
    cminx, cmaxx = min(xs), max(xs)
    cminy, cmaxy = min(ys), max(ys)
    x0 = max(_MIN_LEFT_MM, (cminx + cmaxx - grid_w) / 2.0)
    x0 = min(x0, max(_MIN_LEFT_MM, cmaxx - max(1.0, grid_w)))
    y0 = max(_MIN_BOTTOM_MM, (cminy + cmaxy - grid_h) / 2.0)
    y0 = min(y0, max(_MIN_BOTTOM_MM, cmaxy - max(1.0, grid_h)))
    return round(x0, 2), round(y0, 2)


# ---------------------------------------------------------------------------
# spec construction: build a 0.2.0 dump (grid op included), migrate, validate as 0.3.0
# ---------------------------------------------------------------------------
def _axes(interview: dict) -> tuple[dict, dict]:
    g = interview.get("grid", {})
    ax = {a["axis"]: a for a in g.get("axes", [])}
    x_axis = ax.get("x", {"axis": "x", "start": 0.0, "end": 120.0, "step": 30.0})
    y_axis = ax.get("y", {"axis": "y", "start": 0.0, "end": 60.0, "step": 20.0})
    return x_axis, y_axis


def build_spec(interview: dict) -> JobSpec2:
    """Build a validated 0.3.0 `JobSpec2` from the B3 interview (a grid object + a `set_pass`).

    The spec is *constructed* as a 0.2.0 dict (so `gate_blockers` can be duck-typed onto it after the
    grid op — the only 0.3.0-only element — is dropped), then migrated and validated as 0.3.0.
    """
    mat = interview.get("material", {})
    contour = [tuple(p) for p in interview.get("contour_mm", [[0, 0], [200, 0], [200, 150]])]

    x_axis, y_axis = _axes(interview)
    grid_w = float(x_axis["end"])
    grid_h = float(y_axis["end"])
    ox, oy = safe_origin(contour, grid_w, grid_h)

    g = interview.get("grid", {})
    params = interview.get("params", {})
    power = float(params.get("power_pct", DEFAULT_POWER_PCT))
    speed = float(params.get("speed_mm_min", DEFAULT_SPEED_MM_MIN))
    passes = int(params.get("passes", DEFAULT_PASSES))

    # ---- build the spec as a 0.2.0-style dump, then run the canonical 0.2.0 -> 0.3.0 migration ----
    # (the `add_material_grid` op is 0.3.0-only, but `migrate_020_to_030` is dict-only and adds only
    #  new default fields, so the grid op passes straight through into a valid 0.3.0 spec)
    old_dump = {
        "schema_version": "0.2.0",
        "module": "laser_405",
        "job_type": "work",
        "material": {"id": mat.get("id", "plywood_3"), "category": mat.get("category", "safe")},
        "params_version": interview.get("params_version", DEFAULT_PARAMS_VERSION),
        "workpiece": {
            "contour_mm": contour,
            "registration_rms_mm": float(interview.get("registration_rms_mm", 0.1)),
            "registration_max_mm": float(interview.get("registration_max_mm", 0.3)),
        },
        "ops": [
            {
                "op": "add_material_grid",
                "id": "grid",
                "axes": [
                    {"axis": "x", "start": x_axis["start"], "end": x_axis["end"], "step": x_axis["step"]},
                    {"axis": "y", "start": y_axis["start"], "end": y_axis["end"], "step": y_axis["step"]},
                ],
                "row_labels": list(g.get("row_labels", [])),
                "col_labels": list(g.get("col_labels", [])),
                "x": ox,
                "y": oy,
            },
            {"op": "set_pass", "target": "grid",
             "power_pct": power, "speed_mm_min": speed, "passes": passes},
        ],
    }
    return JobSpec2.model_validate(migrate_020_to_030(old_dump))


def _set_pass_of(spec: JobSpec2):
    for o in spec.ops:
        if getattr(o, "op", None) == "set_pass":
            return o
    return None


def gate_blockers2(interview: dict, spec: JobSpec2) -> list[str]:
    """Blockers for the B3 spec (0.3.0 `spec`) — the 0.2.0 `jobspec.gate_blockers` checks, reproduced
    on the 0.3.0 spec directly (the 0.3.0-only grid op cannot round-trip through a 0.2.0 `JobSpec`,
    whose validator rejects a `set_pass` targeting it), plus the `materials.power_cap` check.

    The three 0.2.0 checks, in order, are: an unresolved `center_on_workpiece`, an unresolved
    `fit_to_workpiece`, a `forbidden` material, and no `set_pass` at all. Empty list = ready for the
    approval gate; non-empty = refuse *before* any machine interaction.
    """
    out: list[str] = []
    for o in spec.ops:
        if o.op in ("center_on_workpiece", "fit_to_workpiece") and getattr(o, "resolved", None) is None:
            out.append("%s:%s unresolved" % (o.op, o.target))
    if spec.material.category == "forbidden":
        out.append("forbidden material " + spec.material.id)
    sp = _set_pass_of(spec)
    if sp is None:
        out.append("no set_pass: laser power/speed undefined")

    cap = power_cap(spec.material.category)
    if sp is not None and sp.power_pct > cap:
        out.append("laser power %.0f%% exceeds the %s cap %.0f%%" % (sp.power_pct, spec.material.category, cap))
    return out


# ---------------------------------------------------------------------------
# cell selection + recipe (deterministic)
# ---------------------------------------------------------------------------
def choose_cell(result: dict, x: float, y: float) -> dict:
    """Nearest grid cell for typed coordinates (x, y): nearest lattice column and row.

    Returns the chosen row/col indices, the engraved label texts for that row and column, and the
    cell parameters (inherited from the job's `set_pass`). Raises `ValueError` when the grid result
    has no axis (no grid was produced / the job was refused).
    """
    grid = result.get("grid") or {}
    x_pos = grid.get("x_positions") or []
    y_pos = grid.get("y_positions") or []
    if not x_pos or not y_pos:
        raise ValueError("no grid in result — cannot choose a cell")

    col = min(range(len(x_pos)), key=lambda i: abs(float(x_pos[i]) - float(x)))
    row = min(range(len(y_pos)), key=lambda i: abs(float(y_pos[i]) - float(y)))

    col_labels = grid.get("labels", {}).get("columns", [])
    row_labels = grid.get("labels", {}).get("rows", [])
    col_text = (col_labels[col].get("text") if col < len(col_labels) else None)
    row_text = (row_labels[row].get("text") if row < len(row_labels) else None)

    return {
        "x": round(float(x), 2),
        "y": round(float(y), 2),
        "row": row,
        "col": col,
        "row_label": row_text,
        "col_label": col_text,
        "cell_params": dict(result.get("params") or {}),
    }


def recipe_proposal(result: dict, cell: dict | None) -> dict:
    """A deterministic recipe proposal for a chosen cell (what a human would approve and save)."""
    params = dict(result.get("params") or {})
    return {
        "material_id": result.get("material_id"),
        "params_version": result.get("params_version"),
        "z_mm": float(result.get("z_mm", FOCAL_Z_MM)),
        "cell": {k: v for k, v in (cell or {}).items() if k != "cell_params"},
        "params": params,
    }


# ---------------------------------------------------------------------------
# fake A250 (stdlib http.server stand-in for the machine, mirrors L5's FakeA250)
# ---------------------------------------------------------------------------
class FakeA250Server:
    """Threaded localhost stand-in for the Snapmaker A250 (measured protocol, all in-process).

    `connect` mints a fresh token once; `status` answers empty (→ not accepted) until `tap_yes()`;
    prepare/start/stop are recorded in the `calls` list so tests can assert the halt/prepare actually
    reached the (fake) machine. No real network, no real hardware.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.token = "boot-token"
        self.accepted = False
        self.calls: list[str] = []
        self._fresh = 0
        self._server: ThreadingHTTPServer | None = None
        self._port: int | None = None

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> "FakeA250Server":
        handler = self._make_handler()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._port = None

    def base_url(self) -> str:
        return "http://127.0.0.1:%d" % self._port

    def tap_yes(self) -> None:
        with self._lock:
            self.accepted = True

    def _log(self, method: str, path: str) -> None:
        with self._lock:
            self.calls.append("%s %s" % (method, path))

    # -- request handler ----------------------------------------------------
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
                if "form-urlencoded" in ct:
                    import urllib.parse
                    try:
                        return dict(urllib.parse.parse_qsl(body.decode("utf-8"))).get("token", "")
                    except Exception:
                        return ""
                import re
                m = re.search(rb'name="token"\r\n\r\n([^\r]*)', body)
                return m.group(1).decode() if m else ""

            def do_GET(self):
                owner._log("GET", self.path)
                path = self.path.split("?", 1)[0]
                import urllib.parse
                tok = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("token", [""])[0]
                with owner._lock:
                    if path != "/api/v1/status":
                        self._finish(404)
                        return
                    if tok != owner.token:
                        self._finish(401)
                        return
                    if not owner.accepted:
                        self._finish(200, b"")                     # not yet: empty, non-JSON
                        return
                    self._finish(200, json.dumps(owner._idle()).encode())

            def do_POST(self):
                owner._log("POST", self.path)
                body = _read_body(self)
                tok = self._token(body)
                with owner._lock:
                    if self.path == "/api/v1/connect":
                        if tok == "":
                            owner._fresh += 1
                            owner.token = "fresh-%d" % owner._fresh
                            owner.accepted = False
                            payload = json.dumps({"token": owner.token, "series": "SM2D040",
                                                  "headType": "dual"}).encode()
                        elif tok == owner.token:
                            payload = json.dumps({"token": tok, "series": "SM2D040",
                                                  "headType": "dual"}).encode()
                        else:
                            self._finish(403, b"{}"); return
                        self._finish(200, payload)
                        return
                    if tok != owner.token:
                        self._finish(403, b"{}"); return
                    if self.path == "/api/v1/prepare_print":
                        self._finish(200, b"Prepare successfully", "text/plain"); return
                    if self.path in ("/api/v1/start_print", "/api/v1/stop_print",
                                     "/api/v1/emergency_stop", "/api/v1/disconnect"):
                        self._finish(200, json.dumps({"code": 0}).encode()); return
                    self._finish(404)

        return Handler

    @staticmethod
    def _idle() -> dict:
        # a clean, non-alarming, non-busy status so the L5 watchdog never stops on the happy path
        return {"status": "IDLE", "homed": True, "laserPower": 0,
                "x": 0, "y": 0, "z": 220, "printStatus": None}


# ---------------------------------------------------------------------------
# run the simulated session (fake server + heartbeat + L5 Watchdog)
# ---------------------------------------------------------------------------
def _run_session(server: FakeA250Server, gcode: str) -> dict:
    """Drive one complete A250 session over the fake machine; capture a deterministic digest of it."""
    tmp = tempfile.mkdtemp(prefix="l8-b3-")
    gpath = Path(tmp) / "job.gcode"
    gpath.write_text(gcode, encoding="utf-8")

    events: list[str] = []
    session = MachineSession(
        base_url=server.base_url(),
        heartbeat_interval=0.05,
        silence_threshold=0.5,
    )
    wd = Watchdog(transport=session.transport_for(), token=lambda: session.token, timeout=8.0)
    session.set_monitor(wd)
    session.add_listener(lambda e: events.append(getattr(e, "kind", type(e).__name__)))

    accepted = False
    alive = False
    last_status = None
    prepare = ""
    start = ""
    stop = ""
    try:
        session.connect(token="")
        server.tap_yes()                                   # the physical Yes-tap on (fake) the machine
        st = session.wait_for_confirmation(timeout=5.0, poll_interval=0.05)
        accepted = isinstance(st, dict)
        alive = session.is_alive()
        last_status = session.last_status
        time.sleep(0.2)                                   # several successful heartbeats (watchdog window is 8 s)
        alive = session.is_alive()
        prepare = session.prepare_print(gpath, "Laser")
        start = session.start_print()
        time.sleep(0.1)
        stop = session.stop_print()
    finally:
        try:
            session.disconnect()
        except Exception:
            pass
        session.close()
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    return {
        "token": session.token,
        "accepted": accepted,
        "alive": alive,
        "lost": bool(getattr(session, "_lost", False)),
        "last_status": last_status,
        "prepare": prepare,
        "start": start,
        "stop": stop,
        "watchdog_stopped": bool(wd.stopped),
        "watchdog_reason": None,
        "events": list(events),
        "server_calls": list(server.calls),
    }


# ---------------------------------------------------------------------------
# the B3 acceptance path
# ---------------------------------------------------------------------------
def run_b3_fake(interview: dict) -> dict:
    """Run the full B3 vertical acceptance path (SPEC §10 #1) against a fake A250.

    Returns a dict with outputs `interview`, `grid`, `preview`, `gcode`, `active_job`, `session`,
    `cell`, `recipe`, `refusal`, and an `ok` flag. On a blocked gate it refuses *before* any machine
    interaction (no server started, no G-code compiled, `session` / `gcode` / `cell` / `recipe` are None).
    """
    spec = build_spec(interview)
    spec_hash = spec_hash2(spec)

    grid = None
    grid_op = next((o for o in spec.ops if getattr(o, "op", None) == "add_material_grid"), None)
    if grid_op is not None:
        grid = generate_grid(grid_op)

    sp = _set_pass_of(spec)
    power_pct = float(sp.power_pct) if sp is not None else 0.0
    speed = float(sp.speed_mm_min) if sp is not None else 0.0
    passes = int(sp.passes) if sp is not None else 1
    cap = power_cap(spec.material.category)

    blockers = gate_blockers2(interview, spec)
    gate_blocked = len(blockers) > 0

    base = {
        "interview": dict(interview),
        "grid": grid,
        "params": {"power_pct": power_pct, "speed_mm_min": speed, "passes": passes, "power_cap": cap},
        "material_id": spec.material.id,
        "params_version": spec.params_version,
        "z_mm": FOCAL_Z_MM,
    }

    # ---- fail-safe: refuse before any machine interaction ----
    if gate_blocked:
        refusal = "refused before machine interaction; blockers: " + "; ".join(blockers)
        base.update({
            "ok": False,
            "gate": {"blocked": True, "blockers": blockers, "power_pct": power_pct,
                     "power_cap": cap, "spec_hash2": spec_hash, "confirmed": False},
            "preview": None,
            "gcode": None,
            "active_job": None,
            "session": None,
            "cell": None,
            "recipe": None,
            "recipe_saved": False,
            "refusal": refusal,
        })
        return base

    # ---- happy path ----
    gcode = compile_jobspec2(spec)
    replay = replay_gcode(gcode)
    active = is_active(gcode)

    base.update({
        "gate": {"blocked": False, "blockers": [], "power_pct": power_pct,
                 "power_cap": cap, "spec_hash2": spec_hash},
        "preview": {
            "ops": replay.ops,
            "n_ops": len(replay.ops),
            "total_time_min": replay.total_time_min,
            "ok": replay.ok,
            "errors": list(replay.errors),
            "simulation": replay.simulation,
        },
        "gcode": gcode,
        "active_job": active,
    })

    # (7) simulate the machine session — only an "active job" needs the physical Yes-tap
    if active:
        server = FakeA250Server().start()
        try:
            base["session"] = _run_session(server, gcode)
        finally:
            server.stop()
    else:
        base["session"] = None
    base["gate"]["confirmed"] = bool(base["session"] and base["session"].get("accepted"))

    # (8) cell choice + recipe
    cell = None
    cell_req = interview.get("cell")
    if cell_req and grid is not None:
        try:
            cell = choose_cell(base, float(cell_req.get("x", 0)), float(cell_req.get("y", 0)))
        except ValueError:
            cell = None
    approved = bool(interview.get("approved", False))
    if cell is not None and approved:
        proposal = recipe_proposal(base, cell)
        base["recipe"] = proposal
        base["recipe_saved"] = True
    else:
        base["recipe"] = None
        base["recipe_saved"] = False

    base["cell"] = cell
    base["ok"] = True
    base["refusal"] = None
    return base
