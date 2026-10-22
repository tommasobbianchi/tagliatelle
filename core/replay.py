"""Trajectory replay for the accurate preview (L2, SPEC overlay "tempo stimato" + Test
"coincidenza del percorso con lo spec").

Replay re-reads the *real* G-code trajectories — not the spec — so the preview can show, for
every operation: its number + direction (CW/CCW), dashed travel moves vs cutting moves, power and
passes per colour/stroke, and an estimated time. Bound/limit checks are delegated to the existing
deterministic simulator (`simulator.simulate_gcode`), so replay and the CI gate agree.

Deterministic; stdlib + pydantic + the simulator only. No model/provider imports.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from simulator import SimulationResult, simulate_gcode

__all__ = ["replay_gcode", "ReplayResult", "OpMove", "Op", "RAPID_MM_MIN", "DEFAULT_CUT_MM_MIN"]

# Deterministic feed assumptions for moves that carry no explicit F (mm/min).
RAPID_MM_MIN = 15000.0          # travel (G0/laser-off) moves without an F
DEFAULT_CUT_MM_MIN = 3000.0     # cutting moves without an F

_CMD = re.compile(r"^([GMgm])(\d+)$")
_PARAM = re.compile(r"^([A-Za-z])(.*)$")
_INLINE_COMMENT = re.compile(r"\([^)]*\)")
_OBJ = re.compile(r"obj=(\S+)")
_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}")
_OPWORD = re.compile(r"\b(engrave|fill|cut)\b", re.I)


# ------------------------- frozen models -------------------------
class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OpMove(_M):
    """One G0/G1 XY move, in program order. `kind` distinguishes dashed travel (laser off) from
    cutting (laser on). Length and the feed/power active on that move are captured for time/power."""
    kind: str                                  # "travel" | "cut"
    x1: float
    y1: float
    x2: float
    y2: float
    z: float = 0.0
    length_mm: float = 0.0
    feed_mm_min: float | None = None
    power_s: int | None = None
    laser_on: bool = False


class Op(_M):
    """One operation (object) in program order, with its trajectory stats."""
    op: str                                    # cut | engrave | fill
    color: str | None = None
    obj: str | None = None
    kind: str | None = None                    # rect | text | grid_label | setup
    cutting_moves: int = 0
    travel_moves: int = 0
    cutting_length_mm: float = 0.0
    travel_length_mm: float = 0.0
    passes: int = 0
    power_s: int | None = None
    direction: str = "none"                    # cw | ccw | linear | none
    time_min: float = 0.0
    moves: list[OpMove] = Field(default_factory=list)


class ReplayResult(_M):
    """Ordered replay of a G-code program plus the simulator's bound/limit checks."""
    ops: list[Op] = Field(default_factory=list)
    simulation: SimulationResult
    total_time_min: float = 0.0
    ok: bool = True
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ------------------------- helpers -------------------------
def _strip_comments(line: str) -> str:
    line = line.split(";", 1)[0]
    return _INLINE_COMMENT.sub(" ", line).strip()


def _parse(body: str) -> tuple[tuple[str, int] | None, dict]:
    """Tolerant single-statement parser -> (command, params). No errors collected (fail-open here)."""
    command: tuple[str, int] | None = None
    params: dict = {}
    for tok in body.split():
        m = _CMD.match(tok)
        if m:
            if command is None:
                command = (m.group(1).upper(), int(m.group(2)))
            continue
        p = _PARAM.match(tok)
        if p:
            try:
                params[p.group(1).upper()] = float(p.group(2))
            except ValueError:
                pass
    return command, params


def _direction(points: list[tuple[float, float]]) -> str:
    """Closed-polygon orientation via the shoelace formula. >=3 points expected for cut contours."""
    if len(points) < 2:
        return "none"
    if len(points) == 2:
        return "linear"
    area = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    if abs(area) < 1e-6:
        return "none"
    return "ccw" if area > 0 else "cw"


def _new_bucket(obj: str | None, kind: str | None = None) -> dict:
    return {"obj": obj, "op": None, "color": None, "kind": kind, "moves": [], "pass_count": 0}


def _build_op(b: dict) -> Op | None:
    moves = b["moves"]
    if not moves:
        return None
    cuts = [m for m in moves if m.kind == "cut"]
    travels = [m for m in moves if m.kind == "travel"]
    cut_len = round(sum(m.length_mm for m in cuts), 4)
    trav_len = round(sum(m.length_mm for m in travels), 4)
    passes = max(1, b["pass_count"]) if cuts else 0
    power = max((m.power_s for m in cuts if m.power_s is not None), default=None)
    direction = _direction([(m.x2, m.y2) for m in cuts])

    def _t(m: OpMove) -> float:
        feed = m.feed_mm_min
        if feed is None or feed <= 0:
            feed = RAPID_MM_MIN if m.kind == "travel" else DEFAULT_CUT_MM_MIN
        return m.length_mm / feed

    time = round(sum(_t(m) for m in moves), 6)
    return Op(
        op=b.get("op") or "cut",
        color=b.get("color"),
        obj=b.get("obj"),
        kind=b.get("kind"),
        cutting_moves=len(cuts),
        travel_moves=len(travels),
        cutting_length_mm=cut_len,
        travel_length_mm=trav_len,
        passes=passes,
        power_s=power,
        direction=direction,
        time_min=time,
        moves=moves,
    )


# ------------------------- public -------------------------
def replay_gcode(gcode: str) -> ReplayResult:
    """Deterministically replay a G-code program into ordered, direction/time-tagged operations.

    Reuses `simulate_gcode` for bed/axis limits and laser on/off validation (`ok`, errors,
    warnings). Comments `;obj=<id> ...` delimit operations; an immediately following
    `;Layer <op> <#color>` comment tags the op type and colour. Move classification: G1 while the
    laser is on → cutting; G0 or laser-off G1 → dashed travel.
    """
    sim = simulate_gcode(gcode)

    ops: list[Op] = []
    current: dict | None = None

    def flush() -> None:
        nonlocal current
        if current is not None:
            op = _build_op(current)
            if op is not None:
                ops.append(op)
            current = None

    x = y = z = 0.0
    absolute = True
    laser_on = False
    modal_s = 0.0
    modal_f: float | None = None

    for raw in gcode.splitlines():
        # ---- comment context (op boundary / layer / colour) ----
        semi = raw.find(";")
        if semi != -1:
            comment = raw[semi + 1:].strip()
            mo = _OBJ.search(comment)
            if mo:
                flush()
                current = _new_bucket(mo.group(1))
            elif current is not None and not current["moves"]:
                ow = _OPWORD.search(comment)
                if ow:
                    current["op"] = ow.group(1).lower()
                co = _COLOR.search(comment)
                if co:
                    current["color"] = co.group(0).lower()

        body = _strip_comments(raw)
        if not body:
            continue

        command, params = _parse(body)
        if command is None:
            continue
        letter, code = command

        if letter == "M":
            if code in (3, 4):
                if not laser_on:
                    if current is None:
                        current = _new_bucket(None)
                    current["pass_count"] += 1
                if "S" in params:
                    modal_s = params["S"]
                laser_on = True
            elif code == 5:
                laser_on = False
            continue

        # ---- G commands ----
        if code == 90:
            absolute = True
        elif code == 91:
            absolute = False
        elif code in (0, 1):
            if "S" in params:
                modal_s = params["S"]
            if "F" in params:
                modal_f = params["F"]
            if not (("X" in params) or ("Y" in params)):
                continue  # modal-only command (e.g. bare G1 F...), no XY move

            tx = params["X"] if (absolute and "X" in params) else (x + params["X"] if "X" in params else x)
            ty = params["Y"] if (absolute and "Y" in params) else (y + params["Y"] if "Y" in params else y)
            tz = params["Z"] if (absolute and "Z" in params) else (z + params["Z"] if "Z" in params else z)

            if current is None:
                current = _new_bucket(None, kind="setup")

            kind = "cut" if (laser_on and code == 1) else "travel"
            length = round(((tx - x) ** 2 + (ty - y) ** 2) ** 0.5, 4)
            current["moves"].append(OpMove(
                kind=kind, x1=x, y1=y, x2=tx, y2=ty, z=tz, length_mm=length,
                feed_mm_min=modal_f, power_s=int(modal_s) if modal_s else None, laser_on=laser_on,
            ))
            x, y, z = tx, ty, tz

    flush()

    total = round(sum(o.time_min for o in ops), 6)
    return ReplayResult(
        ops=ops,
        simulation=sim,
        total_time_min=total,
        ok=sim.ok,
        errors=list(sim.errors),
        warnings=list(sim.warnings),
    )
