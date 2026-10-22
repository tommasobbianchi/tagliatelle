"""Deterministic 0.3.0 G-code compiler (L2): layer order, kerf, multi-pass, engraved grid labels.

Builds on the 0.2.0 compiler's emit approach (reusing its formatters and contour helper) and
adds:
  * LAYER ORDER  — engrave/fill → inner cuts → outer contour last (SPEC §4.2 work order).
                   Engrave objects first, then fill, then cut; *within* the cut group the
                   objects are emitted by ascending area so the outer contour (largest shape)
                   comes last.
  * KERF         — a `kerf_mm` layer setting, applied as a half-kerf inward offset for CUT
                   operations (more geometry): the cut contour shrinks by kerf/2 on each side,
                   compensating for material removed by the kerf.
  * MULTI-PASS   — unchanged from the 0.2.0 compiler (relative Z drop per pass).
  * GRID LABELS  — `add_material_grid` row/col labels emitted as engraved placeholder rects
                   (positioned by `grid.generate_grid`).

Pure: no randomness, no wall-clock, no model/provider imports, no I/O. Same 0.3.0 spec →
byte-identical G-code.
"""
from __future__ import annotations

from jobspec import AddRect, AddText
from jobspec2 import AddMaterialGrid, JobSpec2

from compiler import SAFE_Z, _contour, _f, _scale
from grid import generate_grid

__all__ = ["compile_jobspec2"]

_ENGRAVE = (AddText, AddMaterialGrid)


# ---------------- 0.3.0 per-object parameter lookup ----------------
def _op_for2(spec: JobSpec2, target: str, op_type: str):
    for o in spec.ops:
        if getattr(o, "op", None) == op_type and getattr(o, "target", None) == target:
            return o
    return None


def _object_box(spec: JobSpec2, obj) -> tuple[float, float, float, float]:
    """(x, y, w, h) of an object; resolved placement (center/fit) wins, else the object fields."""
    for opnm in ("center_on_workpiece", "fit_to_workpiece"):
        o = _op_for2(spec, obj.id, opnm)
        if o is not None and getattr(o, "resolved", None) is not None:
            r = o.resolved
            w = r.w if r.w is not None else (obj.w if isinstance(obj, AddRect) else obj.height_mm)
            h = r.h if r.h is not None else (obj.h if isinstance(obj, AddRect) else obj.height_mm)
            return (float(r.x), float(r.y), float(w), float(h))
    if isinstance(obj, AddRect):
        return (float(obj.x), float(obj.y), float(obj.w), float(obj.h))
    return (float(obj.x), float(obj.y), float(obj.height_mm), float(obj.height_mm))


def _natural_op(obj) -> str:
    return "engrave" if isinstance(obj, _ENGRAVE) else "cut"


def _layer_args(spec: JobSpec2, op: str) -> tuple[dict, str | None]:
    for l in spec.layers:
        if l.op == op:
            return (dict(l.settings or {}), l.color)
    return {}, None


def _params(spec: JobSpec2, cid: str, op: str) -> tuple:
    """Power%, speed, passes. Object `set_pass` wins; else the matching layer's settings;
    else fail closed (mirrors the 0.2.0 compiler's fail-safe)."""
    sp = _op_for2(spec, cid, "set_pass")
    if sp is not None:
        return sp.power_pct, sp.speed_mm_min, sp.passes
    settings, _ = _layer_args(spec, op)
    if "power_pct" in settings:
        return settings.get("power_pct", 0.0), settings.get("speed_mm_min", 3000.0), \
            int(settings.get("passes", 1))
    raise ValueError("object %s has no set_pass and no %s layer with power_pct" % (cid, op))


def _focus(spec: JobSpec2, cid: str) -> float:
    st = _op_for2(spec, cid, "set_tool")
    if st is not None and st.focus_z_mm > 0:
        return float(st.focus_z_mm)
    return SAFE_Z


def _drop(spec: JobSpec2, cid: str) -> float:
    sd = _op_for2(spec, cid, "set_depth")
    if sd is None:
        return 0.0
    sp = _op_for2(spec, cid, "set_pass")
    passes = max(1, int(sp.passes)) if sp is not None else 1
    if sd.multi_pass_depth_mm and sd.multi_pass_depth_mm > 0:
        return float(sd.multi_pass_depth_mm)
    if sd.depth_mm and sd.depth_mm < 0:
        return abs(float(sd.depth_mm)) / passes
    return 0.0


# ---------------- emit one closed contour shape (0.2.0 approach) ----------------
def _emit(L: list, obj_id: str, kind: str, op: str, color: str,
          x: float, y: float, w: float, h: float,
          focus: float, drop: float, S: int, F: int, passes: int) -> None:
    L.append("; obj=%s %s" % (obj_id, kind))
    L.append("; Layer %s %s" % (op, color))
    L.append("G0 Z%s" % _f(focus))
    L.append("M5")
    L.append("G1 X%s Y%s F%d" % (_f(x), _f(y), F))
    for _p in range(passes):
        if drop > 0:
            L.append("G91")
            L.append("G0 Z-%s" % _f(drop))
            L.append("G90")
        L.append("M3 S%d" % S)
        for cx, cy in _contour(x, y, w, h):
            L.append("G1 X%s Y%s F%d" % (cx, cy, F))
        L.append("M5")
        L.append("G0 X%s Y%s F%d" % (_f(x), _f(y), F))


def _kerf_offset(x, y, w, h, kerf_mm):
    """Half-kerf inward offset. Returns (x,y,w,h,applied). Offsets only while a positive shape
    remains; otherwise the shape is left unchanged (applied=False)."""
    hk = kerf_mm / 2.0
    if hk <= 0 or 2 * hk >= min(w, h):
        return x, y, w, h, False
    return x + hk, y + hk, w - 2 * hk, h - 2 * hk, True


# ---------------- public ----------------
def compile_jobspec2(spec: JobSpec2) -> str:
    """Deterministic G-code for a valid 0.3.0 laser_405 JobSpec2 (see module docstring)."""
    if spec.module != "laser_405":
        raise ValueError("compile_jobspec2 supports laser_405 only (E1.0 vertical slice)")

    objs = [o for o in spec.ops if isinstance(o, (AddRect, AddText, AddMaterialGrid))]
    if not objs:
        raise ValueError("no drawable objects (add_rect/add_text/add_material_grid)")

    # group by natural op, then order groups per spec.layers (default engrave→fill→cut)
    groups: dict = {}
    for o in objs:
        groups.setdefault(_natural_op(o), []).append(o)
    if spec.layers:
        order = [l.op for l in spec.layers if l.op in groups]
        order += [op for op in ("engrave", "fill", "cut") if op in groups and op not in order]
    else:
        order = [op for op in ("engrave", "fill", "cut") if op in groups]

    L: list = []
    L.append("; TaglIAtelle E2.0 compiler (deterministic, kerf + layer order)")
    L.append(";schema_version: 0.3.0")
    L.append("; module=%s material=%s params=%s" % (spec.module, spec.material.id, spec.params_version))
    L.append("G21")   # mm
    L.append("G90")   # absolute

    any_kerf = False
    for op in order:
        items = groups[op]
        if op == "cut":
            # inner cuts first, outer contour (largest area) last
            def _area(oj):
                bx = _object_box(spec, oj)
                return bx[2] * bx[3]
            items = sorted(items, key=lambda oj: (_area(oj), oj.id, oj.x, oj.y))

        settings, color = _layer_args(spec, op)
        kerf = float(settings.get("kerf_mm", 0.0)) if op == "cut" else 0.0
        if kerf > 0:
            any_kerf = True

        for obj in items:
            power_pct, speed, passes = _params(spec, obj.id, op)
            passes = max(1, int(passes))
            S = _scale(power_pct)
            F = max(1, int(round(speed)))
            focus = _focus(spec, obj.id)
            drop = _drop(spec, obj.id)
            color_out = color or "#000000"

            if isinstance(obj, AddMaterialGrid):
                grid = generate_grid(obj)
                for lab in list(grid["labels"]["rows"]) + list(grid["labels"]["columns"]):
                    _emit(L, "%s_lbl" % obj.id, "grid_label", "engrave", color_out,
                          lab["x"] - lab["width"] / 2.0, lab["y"] - lab["height"] / 2.0,
                          lab["width"], lab["height"], focus, drop, S, F, passes)
                continue

            x, y, w, h = _object_box(spec, obj)
            if op == "cut" and kerf > 0:
                x, y, w, h, applied = _kerf_offset(x, y, w, h, kerf)
                if applied:
                    L.append("; kerf_mm=%s applied_hk_mm=%s" % (_f(kerf), _f(kerf / 2.0)))

            kind = "text" if isinstance(obj, AddText) else "rect"
            if kind == "text":
                L.append("; text=%r (placeholder rect until glyph outline is in scope)" % obj.text)

            _emit(L, obj.id, kind, op, color_out, x, y, w, h, focus, drop, S, F, passes)

    if any_kerf:
        L.insert(3, "; kerf compensation: half-kerf inward offset (kerf_mm from the cut layer)")

    # terminator
    L.append("M5")
    L.append("G0 Z%s" % _f(SAFE_Z))
    return "\n".join(L) + "\n"
