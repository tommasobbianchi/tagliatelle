"""A1 · Importing files — the deterministic, offline core of acceptance A1.

Pipeline (SPEC §10 A1): a coloured SVG → *operation proposal* → §4.2 *work order* →
Job Spec 0.3.0 → resolve → compile (compiler2) → gate → G-code, whose sha256 is pinned
to a golden file (mirrors ``test_golden_gcode``).

Scope of THIS module (the deterministic lane only):
  * parse a small SVG string into colour groups (``parse_svg_layers``);
  * map colour → operation via a palette (``propose_operations``);
  * apply the §4.2 work order (``order_operations``): engrave/fill → inner cuts →
    outer contour (largest closed cut) last, travel moves reduced inside each group
    (the compiler emits per-operation; here we fix the stable order + flags);
  * deduce mm dimensions + a deterministic px→mm scale (``deduce_dimensions``);
  * build a valid 0.3.0 ``JobSpec2`` (``svg_to_jobspec``);
  * run the whole pipeline to a pinned G-code hash (``a1_golden_hash``), *raising*
    with the blocker list if the gate refuses.

Deliberately out of scope (follow-ups, NOT built here): the L4 preview-confirmation
overlay, the L3-kernel font / STEP-2D handling, glyph outlines, and any live hardware.
The compiler (``compiler2``) only emits *rect / text / grid* contours, so each SVG shape
is carried as an ``add_rect`` sized to the shape's bounding box; the *exact* path
geometry is frozen into ``sketch.profiles`` (SPEC §4.1: frozen numbers, inside the hash)
and re-rendered by the L3 kernel in later deliveries.

Determinism + offline rules honoured (SPEC principles): no randomness, no wall-clock,
no I/O, no AI-provider imports after the gate, identical input → identical output.

Assumptions (all documented + pinned by the tests):
  * palette default:  black ``#000000`` → engrave, red ``#ff0000`` → cut,
    grey ``#808080`` → fill.  An explicit palette argument (mapping colour → ``op`` or
    colour → ``{"op": ...}``) overrides it so tests pin mappings.
  * scale: 96 dpi → ``PX_TO_MM = 25.4 / 96`` when the width has no explicit ``mm`` unit;
    an explicit ``width="…mm"`` fixes the scale (mm per user-unit) exactly.
  * open paths: an open path is auto-closed when its closing gap <= ``OPEN_PATH_CLOSE_TOL``
    (default 5 user-units ≈ 1.3 mm) — flagged ``auto_closed``; a larger gap is *kept open*
    and flagged ``highlight_open`` (SPEC A1: "automatic closing only if the gap is minimal;
    the others highlighted").
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, replace

from jobspec2 import JobSpec2
from compiler2 import compile_jobspec2
from materials import power_cap

__all__ = [
    "Path", "Layer", "Operation",
    "parse_svg_layers", "is_colour_in_palette", "propose_operations", "order_operations",
    "deduce_dimensions", "svg_to_jobspec", "a1_golden_hash", "A1GateBlocked",
    "DEFAULT_PALETTE", "PX_TO_MM", "OPEN_PATH_CLOSE_TOL",
]

# --------------------------------------------------------------------------- #
# constants (deterministic)
# --------------------------------------------------------------------------- #
PX_TO_MM: float = 25.4 / 96.0          # 96 dpi: px → mm (deterministic default scale)
OPEN_PATH_CLOSE_TOL: float = 5.0       # user-units; open gap ≤ this ⇒ auto-close, else highlight
MIN_SHAPE_MM: float = 0.1              # smallest drawable extent the schema allows (w/h > 0)

GROUP_RANK = {"engrave": 0, "fill": 1, "cut": 2}   # §4.2: engrave/fill → cut
_OP_DEFAULTS = {"engrave": 0, "fill": 1, "cut": 2}

#: SPEC §10 default palette — colour → {"op": ...} (string values are accepted too).
DEFAULT_PALETTE: dict = {
    "#000000": {"op": "engrave"},   # black → engrave
    "#ff0000": {"op": "cut"},       # red   → cut
    "#808080": {"op": "fill"},      # grey  → fill
}

#: Deterministic per-operation laser parameters (all below the "safe" 60 % cap so the
#: default (safe) material passes the gate; power/speed/passes are the visible numbers).
_PASS_DEFAULTS = {
    "engrave": {"power_pct": 30.0, "speed_mm_min": 3000.0, "passes": 1},
    "fill":    {"power_pct": 40.0, "speed_mm_min": 2000.0, "passes": 1},
    "cut":     {"power_pct": 50.0, "speed_mm_min": 1200.0, "passes": 1},
}
_LAYER_SETTINGS = {"cut": {"kerf_mm": 0.0}}   # kerf compensation is a recipe value; 0 here

# --------------------------------------------------------------------------- #
# small deterministic geometry helpers
# --------------------------------------------------------------------------- #
def _r2(v: float) -> float:
    """Round to 2 decimals half-away-from-zero (matches ``compiler._r2`` / ``grid._r2``)."""
    return math.copysign(math.floor(abs(v) * 100 + 0.5), v) / 100.0


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _eq(a, b, tol: float = 1e-6) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _area(pts) -> float:
    """Absolute shoelace area of a polygon (0 for a degenerate line/point)."""
    a = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return abs(a) * 0.5


# --------------------------------------------------------------------------- #
# data model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Path:
    """One SVG path in *user units*, plus whether it reads closed."""
    points: tuple          # tuple[(x, y)] in SVG user units
    closed: bool

    def area(self) -> float:
        return _area(self.points) if (self.closed and len(self.points) >= 3) else 0.0


@dataclass(frozen=True)
class Layer:
    """All paths shared by one fill colour (SPEC §4.2: an operation is a layer)."""
    color: str             # normalised "#rrggbb" (lower case)
    paths: tuple           # tuple[Path]


@dataclass(frozen=True)
class Operation:
    """One proposed operation (a colour layer) with its §4.2 order flags.

    ``auto_closed_idxs`` / ``highlight_open_idxs`` index into ``paths``: which open
    paths were auto-closed (small gap) and which were left open + highlighted (large gap).
    """
    op: str                       # "engrave" | "fill" | "cut"
    color: str
    paths: tuple                  # tuple[Path] (after the auto-close rule)
    auto_closed_idxs: tuple = ()
    highlight_open_idxs: tuple = ()
    is_outer_contour: bool = False

    def area(self) -> float:
        """Largest-area closed profile in the operation (drives the outer-contour flag)."""
        return max((p.area() for p in self.paths), default=0.0)


# --------------------------------------------------------------------------- #
# colour + attribute helpers
# --------------------------------------------------------------------------- #
def _normalise_hex(fill) -> str | None:
    """Normalise a fill to lower-case ``#rrggbb``; None when it is not a hex fill."""
    if fill is None:
        return None
    s = str(fill).strip().lower()
    if not s.startswith("#"):
        return None
    h = s[1:]
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) == 6 and all(c in "0123456789abcdef" for c in h):
        return "#" + h
    return None


def _attrs(blob: str) -> dict:
    """Parse ``key="value"`` / ``key='value'`` attributes from an SVG tag blob."""
    out: dict = {}
    for m in re.finditer(r'([\w:-]+)\s*=\s*("([^"]*)"|\'([^\']*)\')', blob):
        key = m.group(1)
        val = m.group(3) if m.group(3) is not None else m.group(4)
        out[key] = val
    return out


def _attr_num(v) -> float | None:
    """The leading number of a dimension string (``"100"``/``"100px"``/``"100mm"`` → 100)."""
    if v is None:
        return None
    m = re.search(r"-?\d*\.?\d+", str(v))
    return float(m.group()) if m else None


def _attr_mm(v) -> float | None:
    """The numeric width only when its unit is explicitly ``mm`` (else None → 96 dpi)."""
    if v is None:
        return None
    val = _attr_num(v)
    return val if (val is not None and str(v).strip().lower().endswith("mm")) else None


def _op_type_for(color: str, palette: dict) -> str:
    """Resolve a colour to an op type from the palette; unlisted colours default to engrave."""
    v = palette.get(color)
    if isinstance(v, dict):
        return v.get("op", "engrave")
    if isinstance(v, str):
        return v
    return "engrave"


# --------------------------------------------------------------------------- #
# SVG path `d` parser (deterministic, line-based: M/L/H/V/Z)
# --------------------------------------------------------------------------- #
def _circle_points(cx: float, cy: float, r: float) -> list:
    """A circle as a deterministic 16-gon (the L3 kernel renders the true curve later)."""
    n = 16
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n))
            for k in range(n)]


def _parse_path_d(d: str) -> list:
    """Parse an SVG path ``d`` into an ordered point list (user units).

    Supports the line/arc commands ``M/m``, ``L/l``, ``H/h``, ``V/v``, ``Z/z`` (and
    repeated coordinate groups, relative for repeats per SVG semantics).  Curve commands
    are accepted (endpoints only) so the parser never chokes; the exact curve is the
    L3 kernel's job.  Deterministic: same ``d`` → same points.
    """
    pts: list = []
    cx = cy = 0.0
    for m in re.finditer(r"([a-zA-Z])([^a-zA-Z]*)", d):
        letter = m.group(1)
        low = letter.lower()
        nums = [float(x) for x in re.findall(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?", m.group(2))]
        if low == "z":
            if pts:
                cx, cy = pts[0]
            continue
        arity = {"h": 1, "v": 1, "m": 2, "l": 2}.get(low)
        if arity is None or not nums:
            continue                     # unsupported/empty command: skip its numbers
        i = 0
        first = True
        while i + arity <= len(nums):
            if low in ("h", "v"):
                val = nums[i]
                i += 1
                abs_ = (letter.isupper() or first)
                if low == "h":
                    cx = val if abs_ else cx + val
                else:
                    cy = val if abs_ else cy + val
            else:  # m / l
                x, y = nums[i], nums[i + 1]
                i += 2
                if first:
                    if letter.isupper():
                        cx, cy = x, y
                    else:
                        cx, cy = cx + x, cy + y
                    if low == "m":
                        # remember the moveto origin for an implicit close
                        pass
                else:                     # implicit repeat → relative
                    cx += x
                    cy += y
            pts.append((cx, cy))
            first = False
    return pts


# --------------------------------------------------------------------------- #
# 1. parse
# --------------------------------------------------------------------------- #
def parse_svg_layers(svg_text: str) -> list[Layer]:
    """Group an SVG string's ``<path>``/``<rect>``/``<circle>`` elements by fill colour.

    Returns colour-keyed :class:`Layer` objects (normalised ``#rrggbb``), preserving the
    first-seen colour order (deterministic).  Elements with no hex fill are ignored.
    """
    groups: dict = {}
    order: list = []
    for m in re.finditer(r"<(path|rect|circle)\b([^>]*?)>", svg_text, re.I | re.S):
        tag = m.group(1).lower()
        attrs = _attrs(m.group(2))
        color = _normalise_hex(attrs.get("fill"))
        if color is None:
            continue                     # cannot group by colour → ignore
        if tag == "rect":
            x = float(attrs.get("x", 0)); y = float(attrs.get("y", 0))
            w = float(attrs.get("width", 0)); h = float(attrs.get("height", 0))
            pts = ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
            path = Path(points=pts, closed=True)
        elif tag == "circle":
            cx = float(attrs.get("cx", 0)); cy = float(attrs.get("cy", 0))
            r = float(attrs.get("r", 0))
            path = Path(points=tuple(_circle_points(cx, cy, r)), closed=True)
        else:  # path
            d = attrs.get("d", "")
            pts = _parse_path_d(d)
            if not pts:
                continue
            closed = bool(re.search(r"[zZ]", d)) or (len(pts) >= 3 and _eq(pts[0], pts[-1]))
            path = Path(points=tuple(pts), closed=closed)
        if color not in groups:
            groups[color] = []
            order.append(color)
        groups[color].append(path)
    return [Layer(color=c, paths=tuple(groups[c])) for c in order]


def is_colour_in_palette(color, palette: dict) -> bool:
    """True when ``color`` is a hex fill that the palette explicitly maps to an op."""
    c = _normalise_hex(color)
    return c is not None and c in palette


# --------------------------------------------------------------------------- #
# 2. propose operations
# --------------------------------------------------------------------------- #
def _apply_open_path_rules(paths: tuple) -> tuple:
    """Return (paths', auto_closed_idxs, highlight_open_idxs) applying SPEC A1's open-path
    rule: a minimal gap auto-closes (flagged); a large gap stays open (flagged)."""
    closed = []
    auto_idxs = []
    hi_idxs = []
    for i, p in enumerate(paths):
        if p.closed:
            closed.append(p)
            continue
        gap = _dist(p.points[-1], p.points[0]) if len(p.points) >= 2 else 0.0
        if gap <= OPEN_PATH_CLOSE_TOL:
            closed.append(replace(p, closed=True))   # auto-close the loop
            auto_idxs.append(i)
        else:
            closed.append(p)                          # keep open, highlight for the user
            hi_idxs.append(i)
    return tuple(closed), tuple(auto_idxs), tuple(hi_idxs)


def propose_operations(layers: list[Layer], palette: dict | None = None) -> list[Operation]:
    """One proposed :class:`Operation` per colour layer, in a deterministic order.

    Order key: §4.2 group rank (engrave → fill → cut), then normalised colour — so the
    proposal is stable regardless of parse order.  Open paths are normalised per the
    A1 rule (auto-close small gaps, highlight large ones) with the indices recorded.
    """
    pal = palette if palette is not None else DEFAULT_PALETTE
    ops = []
    for layer in layers:
        paths, auto, hi = _apply_open_path_rules(layer.paths)
        ops.append(Operation(
            op=_op_type_for(layer.color, pal),
            color=layer.color,
            paths=paths,
            auto_closed_idxs=auto,
            highlight_open_idxs=hi,
        ))
    ops.sort(key=lambda o: (GROUP_RANK.get(o.op, 9), o.color, len(o.paths)))
    return ops


# --------------------------------------------------------------------------- #
# 3. §4.2 work order
# --------------------------------------------------------------------------- #
def order_operations(operations: list[Operation]) -> list[Operation]:
    """Apply §4.2: engrave/fill → inner cuts → outer contour (largest closed cut) last.

    Within engrave/fill the input (proposal) order is kept (stable).  Inner cuts are kept
    in ascending-area order (ties → original index).  The outer contour is flagged
    ``is_outer_contour`` on exactly one op (the largest closed cut) and appended last.
    """
    ops = list(operations)
    n = len(ops)
    areas = [o.area() for o in ops]

    # outer contour = the largest closed *cut* (a cut, per the A1/§4.2 rule)
    outer = -1
    for i in [i for i in range(n) if ops[i].op == "cut"]:
        if areas[i] <= 0:
            continue
        if outer < 0 or areas[i] > areas[outer]:
            outer = i

    ordered_ids: list = []
    for rank in ("engrave", "fill"):
        ordered_ids += [i for i in range(n) if ops[i].op == rank]
    inner = [i for i in range(n) if ops[i].op == "cut" and i != outer]
    inner.sort(key=lambda i: (areas[i], i))          # inner cuts first (asc area), stable
    ordered_ids += inner
    if outer >= 0:
        ordered_ids.append(outer)                    # outer contour last

    out = []
    for i in ordered_ids:
        o = replace(ops[i], is_outer_contour=(i == outer)) if i == outer else ops[i]
        out.append(o)
    return out


# --------------------------------------------------------------------------- #
# 4. dimensions
# --------------------------------------------------------------------------- #
def _root_attrs(svg_text: str) -> dict:
    m = re.search(r"<svg\b([^>]*?)>", svg_text, re.I | re.S)
    return _attrs(m.group(1)) if m else {}


def deduce_dimensions(svg_text: str) -> tuple[float, float, float]:
    """Return ``(width_mm, height_mm, scale)`` where ``scale`` = mm per user-unit.

    * user extent from the ``viewBox`` (width/height), else the numeric ``width``/``height``;
    * if the ``width`` attribute is explicitly ``mm``, ``scale = width_mm / user_width``;
    * otherwise (px / unitless) ``scale = PX_TO_MM`` (96 dpi), per the A1 assumption.
    Deterministic for a fixed SVG string.
    """
    ra = _root_attrs(svg_text)

    user_w = user_h = None
    vb = ra.get("viewBox")
    if vb:
        parts = [p for p in re.split(r"[\s,]+", vb.strip()) if p]
        if len(parts) >= 4:
            try:
                user_w, user_h = float(parts[2]), float(parts[3])
            except ValueError:
                pass
    wv = _attr_num(ra.get("width")); hv = _attr_num(ra.get("height"))
    if user_w is None:
        user_w = wv
    if user_h is None:
        user_h = hv
    if user_w in (None, 0.0) and wv:
        user_w = wv
    if user_h in (None, 0.0) and hv:
        user_h = hv
    if user_w is None:
        user_w = 1.0
    if user_h is None:
        user_h = 1.0

    wmm = _attr_mm(ra.get("width"))
    if wmm is not None and user_w:
        scale = wmm / user_w
    else:
        scale = PX_TO_MM
    return user_w * scale, user_h * scale, scale


# --------------------------------------------------------------------------- #
# 5. build the 0.3.0 JobSpec2
# --------------------------------------------------------------------------- #
_DEFAULT_MATERIAL = {"id": "plywood_3", "category": "safe"}
_DEFAULT_PARAMS = "seed-405-v1"


def _spec_box_mm(op, gminx, gminy, scale) -> tuple[float, float, float, float]:
    """Bounding box of :class:`Operation` (in mm): relative to the global origin, scaled to mm,
    clamped to a positive, schema-valid extent (``w/h > 0``)."""
    xs = [px for p in op.paths for px, py in p.points]
    ys = [py for p in op.paths for px, py in p.points]
    x0, x1 = _r2((min(xs) - gminx) * scale), _r2((max(xs) - gminx) * scale)
    y0, y1 = _r2((min(ys) - gminy) * scale), _r2((max(ys) - gminy) * scale)
    x, y = max(0.0, x0), max(0.0, y0)
    w, h = max(MIN_SHAPE_MM, abs(x1 - x0)), max(MIN_SHAPE_MM, abs(y1 - y0))
    return x, y, w, h


def _workpiece_contour(width_mm: float, height_mm: float) -> list:
    w = width_mm if width_mm > 0 else 10.0
    h = height_mm if height_mm > 0 else 10.0
    return [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]


def svg_to_jobspec(svg_text: str, palette: dict | None = None, material: dict | None = None) -> JobSpec2:
    """Build a valid 0.3.0 ``JobSpec2`` from a coloured SVG.

    Each shape becomes an ``add_rect`` sized to its bounding box (the deterministic-core
    drawable; the exact profile is frozen in ``sketch.profiles``), a per-object ``set_pass``
    (the visible power/speed/passes), and a ``layers`` list ordered per §4.2.  Coordinates are
    scaled to mm with the deduced px→mm scale, translated so the global origin is ``origin``, and
    the outer contour keeps its §4.2 position (largest closed cut → last in the cut group).
    """
    pal = palette if palette is not None else DEFAULT_PALETTE
    layers = parse_svg_layers(svg_text)
    ordered = order_operations(propose_operations(layers, pal))
    if not ordered:
        raise ValueError("the SVG has no hex-filled shapes to propose as operations")

    width_mm, height_mm, scale = deduce_dimensions(svg_text)

    mat = material if material is not None else {}
    mat_id = mat.get("id", _DEFAULT_MATERIAL["id"])
    mat_cat = mat.get("category", _DEFAULT_MATERIAL["category"])
    params = mat.get("params_version", _DEFAULT_PARAMS)

    # global origin: translate every bbox so the minimum corner is (0, 0) in mm.
    all_x = [px for o in ordered for p in o.paths for px, py in p.points]
    all_y = [py for o in ordered for p in o.paths for px, py in p.points]
    gminx = min(all_x, default=0.0)
    gminy = min(all_y, default=0.0)

    ops_list: list = []
    profiles: list = []
    for i, o in enumerate(ordered):
        x, y, w, h = _spec_box_mm(o, gminx, gminy, scale)
        obj_id = "s%d" % i
        ops_list.append({"op": "add_rect", "id": obj_id, "x": x, "y": y, "w": w, "h": h})
        pass_def = _PASS_DEFAULTS[o.op]
        ops_list.append({
            "op": "set_pass", "target": obj_id,
            "power_pct": pass_def["power_pct"], "speed_mm_min": pass_def["speed_mm_min"],
            "passes": pass_def["passes"],
        })
        profiles.append({
            "op": o.op, "color": o.color, "id": obj_id,
            "auto_closed": list(o.auto_closed_idxs), "highlight_open": list(o.highlight_open_idxs),
            "is_outer_contour": o.is_outer_contour, "bbox_mm": [x, y, w, h],
            "pts_mm": [[_r2(px * scale), _r2(py * scale)] for p in o.paths for px, py in p.points],
        })

    layers_out = []
    for opnm in ("engrave", "fill", "cut"):
        if any(o.op == opnm for o in ordered):
            color = next(o.color for o in ordered if o.op == opnm)
            layers_out.append({"op": opnm, "color": color, "settings": dict(_LAYER_SETTINGS.get(opnm, {}))})

    spec_dict = {
        "schema_version": "0.3.0",
        "module": "laser_405",
        "job_type": "work",
        "material": {"id": mat_id, "category": mat_cat},
        "params_version": params,
        "workpiece": {
            "contour_mm": _workpiece_contour(width_mm, height_mm),
            "registration_rms_mm": 0.1, "registration_max_mm": 0.3,
        },
        "ops": ops_list,
        "locked": [],
        "sketch": {
            "profiles": profiles,
            "recipe": {"source": "import_svg", "dpi": 96, "scale": scale,
                        "palette": {c: (_op_type_for(c, pal)) for c in sorted(pal)}},
        },
        "layers": layers_out,
        "exclusion_mask": {"polygons": [], "source": "user"},
        "imported_blocks": [],
        "variants": [],
    }
    return JobSpec2.model_validate(spec_dict)


# --------------------------------------------------------------------------- #
# 6. gate + golden hash
# --------------------------------------------------------------------------- #
class A1GateBlocked(Exception):
    """Raised by ``a1_golden_hash`` when the approval gate reports one or more blockers."""

    def __init__(self, blockers):
        self.blockers = list(blockers)
        super().__init__("A1 gate blocked: " + "; ".join(self.blockers))


def _gate_blockers(spec: JobSpec2) -> list[str]:
    """A1 readiness gate — mirrors ``l8_b3.gate_blockers2`` (kept here to avoid pulling the
    L8/tools dependency into the deterministic import core): unresolved centre/fit, a forbidden
    material, a missing ``set_pass``, and laser power above the category cap.  Empty = ready."""
    out: list = []
    for o in spec.ops:
        if o.op in ("center_on_workpiece", "fit_to_workpiece") and getattr(o, "resolved", None) is None:
            out.append("%s:%s unresolved" % (o.op, o.target))
    if spec.material.category == "forbidden":
        out.append("forbidden material " + spec.material.id)
    sps = [o for o in spec.ops if o.op == "set_pass"]
    if not sps:
        out.append("no set_pass: laser power/speed undefined")
    else:
        # A1 carries a per-object set_pass (one per shape); fail closed on the WORST (max)
        # power against the material cap, not just the first — the B3 gate was single-set_pass.
        cap = power_cap(spec.material.category)
        worst = max(sps, key=lambda o: o.power_pct)
        if worst.power_pct > cap:
            out.append("laser power %.0f%% exceeds the %s cap %.0f%%"
                       % (worst.power_pct, spec.material.category, cap))
    return out


def a1_golden_hash(svg_text: str, palette: dict | None = None, material: dict | None = None) -> str:
    """Run the full deterministic A1 pipeline and return ``sha256(gcode)``.

    propose → order → ``svg_to_jobspec`` → resolve (identity: A1 has no centre/fit ops) →
    ``compile_jobspec2`` → gate → ``sha256``.  Raises :class:`A1GateBlocked` (with the blocker
    list) if the gate refuses the job.  Deterministic: same input → same hash.
    """
    spec = svg_to_jobspec(svg_text, palette=palette, material=material)
    # resolve step is an identity for A1 (no center_on_workpiece / fit_to_workpiece ops):
    # the coordinates are already in mm from the SVG, so the resolver is a no-op and omitted.
    gcode = compile_jobspec2(spec)
    blockers = _gate_blockers(spec)
    if blockers:
        raise A1GateBlocked(blockers)
    return hashlib.sha256(gcode.encode("utf-8")).hexdigest()
