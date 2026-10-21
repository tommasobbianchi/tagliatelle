"""Deterministic G-code compiler for TaglIAtelle E1.0 (laser_405 nm, vector).

Contract: a *valid and resolved* `JobSpec` (see jobspec.py) in → a fixed MarLin-style
G-code string out. Pure: no randomness, no wall-clock, no model/provider imports, no I/O.
The same resolved spec always yields byte-identical G-code, which is what the
simulator, the gate's active-job scan (`gcode_scan.is_active`) and the runner all rely
on for integrity (audit: hash of spec == hash of executed job).

Targets: Snapmaker A250 with the laser_405 module (E1.0 vertical slice).

Conventions (Luban-style):
  G21  mm, G90 absolute, G91 for relative depth drops, M3 laser on, M5 off.
  S = integer power on 0..255: `int(floor(power_pct * 255 / 100 + 0.5))`
       (deterministic; 40 -> 102, 60 -> 153, 100 -> 255).
  F = feedrate mm/min, passed through from `set_pass.speed_mm_min` (rounded to int).
  Focus: the laser is fired at a fixed focal Z set at the start of the job;
         `set_tool.focus_z_mm` overrides the schema default `FOCAL_Z_MM` if present.
  Multi-pass: `set_depth.multi_pass_depth_mm > 0` → a per-pass relative Z drop
         emitted as  G91 / G0 Z-minus / G90  (Luban-style) before each pass. The laser
         is off while Z changes. If `multi_pass_depth_mm == 0`, `set_depth.depth_mm`
         (absolute total, signed) is split over `set_pass.passes` as the per-pass step.

ASSUMPTIONS (callers must know these before relying on the compiler):
  * `add_text` is emitted as a placeholder rectangle sized from the resolved bbox
    when one exists (else from `height_mm` on both axes), with a comment noting that
    the real glyph outline is out of scope for this vertical slice. `add_rect` is
    implemented fully.
  * Feedrate is passed through from `set_pass.speed_mm_min` verbatim (round to int).
  * Power rounding is deterministic `floor(pct * 2.55 + 0.5)` — matches the
    reference table (40 → 102), not IEEE banker's rounding.
"""
from __future__ import annotations

import math
from jobspec import (
    AddRect,
    AddText,
    FOCAL_Z_MM,
    JobSpec,
    SetDepth,
    SetPass,
    SetTool,
)

__all__ = ["compile_gcode"]

SAFE_Z = float(FOCAL_Z_MM)


# ---------------- deterministic formatters ----------------
def _r2(mm: float) -> float:
    """Round to 2 decimals half-away-from-zero (JS .toFixed(2) style)."""
    q = 100.0
    return math.copysign(math.floor(abs(mm) * q + 0.5), mm) / q


def _f(mm: float) -> str:
    return "%.2f" % _r2(mm)


def _scale(pct: float) -> int:
    v = max(0.0, min(100.0, float(pct))) * 255.0 / 100.0
    return int(math.floor(v + 0.5))


# ---------------- per-object parameter lookup ----------------
def _op_for(spec: JobSpec, target: str, op_type: str):
    for o in spec.ops:
        if o.op == op_type and o.target == target:
            return o
    return None


def _object_box(spec: JobSpec, obj) -> tuple[float, float, float, float]:
    """(x, y, w, h) bottom-left box of an add_rect / add_text object in bed mm.

    Preference: resolved bbox of a center_on_workpiece / fit_to_workpiece op targeting
    the object (when `resolved` is set, per resolver). Otherwise the object's own
    fields; for AddText the width is not defined in v0 so we default w == h to
    height_mm (placeholder assumption, documented)."""
    cid = obj.id
    for opnm in ("center_on_workpiece", "fit_to_workpiece"):
        o = _op_for(spec, cid, opnm)
        if o is not None and getattr(o, "resolved", None) is not None and o.resolved is not None:
            r = o.resolved
            w = r.w if r.w is not None else (obj.w if isinstance(obj, AddRect) else obj.height_mm)
            h = r.h if r.h is not None else (obj.h if isinstance(obj, AddRect) else obj.height_mm)
            return (float(r.x), float(r.y), float(w), float(h))
    if isinstance(obj, AddRect):
        return (float(obj.x), float(obj.y), float(obj.w), float(obj.h))
    return (float(obj.x), float(obj.y), float(obj.height_mm), float(obj.height_mm))


def _per_pass_drop(spec: JobSpec, cid: str) -> float:
    """Relative Z step (mm) applied before each pass; 0 means no Z change.

    Order: set_depth.multi_pass_depth_mm (per-pass step, Luban-style) wins; else
    split set_depth.depth_mm over passes; else 0 (engrave at focal Z only).
    """
    sd = _op_for(spec, cid, "set_depth")
    if sd is None:
        return 0.0
    sp = _op_for(spec, cid, "set_pass")
    passes = max(1, int(sp.passes)) if sp is not None else 1
    if sd.multi_pass_depth_mm and sd.multi_pass_depth_mm > 0:
        return float(sd.multi_pass_depth_mm)
    if sd.depth_mm and sd.depth_mm < 0:
        return abs(float(sd.depth_mm)) / passes
    return 0.0


def _focus_z(spec: JobSpec, cid: str) -> float:
    st = _op_for(spec, cid, "set_tool")
    if st is not None and st.focus_z_mm > 0:
        return float(st.focus_z_mm)
    return SAFE_Z


def _contour(x: float, y: float, w: float, h: float):
    """Closed CCW quad; each entry is the destination of one G1 segment."""
    a = (_f(x), _f(y))
    b = (_f(x + w), _f(y))
    c = (_f(x + w), _f(y + h))
    d = (_f(x), _f(y + h))
    return [b, c, d, a]


# ---------------- public ----------------
def compile_gcode(spec: JobSpec) -> str:
    """Deterministic G-code string for a valid, resolved laser_405 vector JobSpec.

    Guarantees:
      * No non-determinism (no random, no time, no imports beyond the schema module).
      * Same JobSpec value → byte-identical output.
      * M5 (laser off) is the last *laser* command before the terminator G0 Z<FOCAL>.
      * M3 S<0..255> turns the laser on only during contour G1 moves.
    """
    if spec.module != "laser_405":
        raise ValueError("compile_gcode supports laser_405 only (E1.0 vertical slice)")

    L: list[str] = []
    # -------- deterministic header (schema version, NOT a timestamp) --------
    L.append("; TaglIAtelle E1.0 compiler (deterministic)")
    L.append(";schema_version: %s" % spec.schema_version)
    L.append("; module=%s material=%s params=%s" % (spec.module, spec.material.id, spec.params_version))
    L.append("G21")   # mm
    L.append("G90")   # absolute

    # Resolve the per-object parameters first (set_pass/set_tool/set_depth are
    # keyed by target; if several target the same object the first occurrence wins).
    obj_ids = [o.id for o in spec.ops if o.op in ("add_rect", "add_text")]
    sp = next((o for o in spec.ops if o.op == "set_pass"), None)
    if sp is None:
        # gate_blockers already rejects this, but the compiler must fail closed too
        raise ValueError("no set_pass: laser power/speed undefined")

    for cid in obj_ids:
        obj = next(o for o in spec.ops if o.id == cid)
        # object-specific set_* override the default set_pass if present
        sp_i = _op_for(spec, cid, "set_pass") or sp
        x, y, w, h = _object_box(spec, obj)
        focus = _focus_z(spec, cid)
        drop = _per_pass_drop(spec, cid)
        S = _scale(sp_i.power_pct)
        F = max(1, int(round(sp_i.speed_mm_min)))
        passes = max(1, int(sp_i.passes))

        if isinstance(obj, AddText):
            L.append("; obj=%s text=%r (placeholder rect until glyph outline is in scope)" % (cid, obj.text))
        else:
            L.append("; obj=%s rect" % cid)

        # Safe Z before any contour work
        L.append("G0 Z%s" % _f(focus))
        L.append("M5")
        L.append("G1 X%s Y%s F%d" % (_f(x), _f(y), F))   # travel to first corner, laser off

        for p in range(passes):
            if drop > 0:
                L.append("G91")
                L.append("G0 Z-%s" % _f(drop))
                L.append("G90")
            L.append("M3 S%d" % S)
            for cx, cy in _contour(x, y, w, h):
                L.append("G1 X%s Y%s F%d" % (cx, cy, F))
            L.append("M5")
            # travel back to the starting corner for the next pass (laser off)
            L.append("G0 X%s Y%s F%d" % (_f(x), _f(y), F))

    # -------- terminator --------
    L.append("M5")
    L.append("G0 Z%s" % _f(SAFE_Z))
    return "\n".join(L) + "\n"
