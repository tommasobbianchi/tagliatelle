"""Resolver for laser_405 E1.0: fills the `resolved` field of
center_on_workpiece / fit_to_workpiece ops from the frozen workpiece contour.

Deterministic, no model imports (project rule: nothing after the gate touches the AI
provider). The contour is frozen in the spec; the resolver never re-reads the camera.

Geometry:
  - Workpiece == is the polygon `workpiece.contour_mm` (already in mm, registration-verified).
  - Object placement is defined by an axis-aligned bounding box (x, y, w, h) in bed mm.
  - center_on_workpiece : translate the object so its bbox centre == polygon centroid.
  - fit_to_workpiece    : translate + scale (uniform, about the polygon centroid) so the
                          object fits inside the contour with `margin_mm` clearance.
"""
from __future__ import annotations

from dataclasses import dataclass

from jobspec import (AddRect, AddText, BED_MM, CenterOnWorkpiece, FitToWorkpiece,
                     JobSpec, Resolved)


@dataclass(frozen=True)
class ObjectBounds:
    """Axis-aligned bbox of one object, in bed mm (centred on its x,y anchor)."""
    x: float
    y: float
    w: float
    h: float


def object_bounds_for(op: AddText | AddRect) -> ObjectBounds:
    """Exact bounds for a rect; for text we need glyph metrics, so take the declared
    w/h if available, else default from the font height (best-effort, overridable)."""
    if isinstance(op, AddRect):
        return ObjectBounds(op.x, op.y, op.w, op.h)
    # AddText: width estimated from height if not otherwise resolved — the compiler
    # (which owns shaping) may override with exact metrics via resolve_text_bounds.
    return ObjectBounds(op.x, op.y, op.height_mm, op.height_mm)


def _polygon_centroid(pts: list[tuple[float, float]]) -> tuple[float, float]:
    """Area centroid of a simple polygon (shoelace)."""
    n = len(pts)
    a = 0.0
    cx = cy = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(a) < 1e-12:
        raise ValueError("workpiece contour has zero area")
    a *= 0.5
    return cx / (6 * a), cy / (6 * a)


def _point_in_polygon(px: float, py: float, pts: list[tuple[float, float]]) -> bool:
    inside = False
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        if ((y1 > py) != (y2 > py)) and (px < (x2 - x1) * (py - y1) / ((y2 - y1) or 1e-12) + x1):
            inside = not inside
    return inside


def _bbox_fits(x: float, y: float, w: float, h: float, pts: list[tuple[float, float]],
               margin: float) -> bool:
    """True if the axis-aligned bbox (with margin) lies fully inside the contour."""
    m = margin
    corners = [(x - m, y - m), (x + w + m, y - m), (x + w + m, y + h + m), (x - m, y + h + m)]
    return all(_point_in_polygon(px, py, pts) for px, py in corners)


def resolve_center(contour, op: CenterOnWorkpiece, bounds: ObjectBounds) -> Resolved:
    """Translate so bbox centre == polygon centroid."""
    cx, cy = _polygon_centroid(contour)
    new_x = cx - bounds.w / 2
    new_y = cy - bounds.h / 2
    return Resolved(x=new_x, y=new_y, w=bounds.w, h=bounds.h)


def resolve_fit(contour, op: FitToWorkpiece, bounds: ObjectBounds) -> Resolved:
    """Uniformly scale about the centroid until it fits in the contour with margin."""
    cx, cy = _polygon_centroid(contour)
    m = op.margin_mm

    # Inscribed-box approach: find the max uniform scale about the centroid such that
    # the bbox (scaled about centroid) stays inside the contour. We binary-search scale
    # in [0, max_scale] where max_scale is generous (bounded by bed).
    lo, hi = 1e-6, 4.0
    # We search for the largest factor s where the bbox scaled about centroid fits.
    best = 0.0
    for _ in range(40):
        s = (lo + hi) / 2
        w = bounds.w * s
        h = bounds.h * s
        x = cx - w / 2
        y = cy - h / 2
        if _bbox_fits(x, y, w, h, contour, m):
            best = s
            lo = s
        else:
            hi = s
    w = bounds.w * best
    h = bounds.h * best
    return Resolved(x=cx - w / 2, y=cy - h / 2, w=w, h=h)


def resolve_spec(spec: JobSpec, text_bounds=None) -> JobSpec:
    """Return a copy of `spec` with every center/fit op's `resolved` filled.

    `text_bounds`: optional callable(AddText) -> ObjectBounds for exact glyph metrics;
    defaults to the heuristic in `object_bounds_for`.
    """
    contour = spec.workpiece.contour_mm
    bounds_for = object_bounds_for if text_bounds is None else (
        lambda op: text_bounds(op) if isinstance(op, AddText) else object_bounds_for(op))

    ops = []
    for op in spec.ops:
        if isinstance(op, CenterOnWorkpiece):
            target = next(o for o in spec.ops if getattr(o, "id", None) == op.target)
            ops.append(op.model_copy(update={"resolved": resolve_center(contour, op, bounds_for(target))}))
        elif isinstance(op, FitToWorkpiece):
            target = next(o for o in spec.ops if getattr(o, "id", None) == op.target)
            ops.append(op.model_copy(update={"resolved": resolve_fit(contour, op, bounds_for(target))}))
        else:
            ops.append(op)
    return spec.model_copy(update={"ops": ops})
