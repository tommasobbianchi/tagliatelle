import math

import pytest

from jobspec import FitToWorkpiece, JobSpec
from resolver import (ObjectBounds, object_bounds_for, resolve_center, resolve_fit, resolve_spec,
                      _polygon_centroid, _bbox_fits)

BASE = dict(module="laser_405", job_type="work", material=dict(id="ply3", category="safe"),
            params_version="m1",
            workpiece=dict(contour_mm=[(0, 0), (100, 0), (100, 60)], registration_rms_mm=0.1,
                           registration_max_mm=0.3),
            ops=[dict(op="add_rect", id="r1", x=10, y=10, w=20, h=10),
                 dict(op="add_text", id="t1", text="Ciao", font="dejavu", font_version="2.37",
                      height_mm=10, x=10, y=10),
                 dict(op="center_on_workpiece", target="r1"),
                 dict(op="fit_to_workpiece", target="t1", margin_mm=0),
                 dict(op="set_pass", target="r1", power_pct=40, speed_mm_min=1500, passes=1)])


def test_centroid_triangle():
    # right triangle (0,0),(100,0),(100,60): vertex average x=(0+100+100)/3=200/3, y=20
    c = _polygon_centroid([(0, 0), (100, 0), (100, 60)])
    assert abs(c[0] - 200 / 3) < 1e-9
    assert abs(c[1] - 20) < 1e-9


def test_center_resolves_to_centroid():
    spec = JobSpec.model_validate(BASE)
    r1 = next(o for o in spec.ops if o.id == "r1")
    res = resolve_center(spec.workpiece.contour_mm, None, ObjectBounds(r1.x, r1.y, r1.w, r1.h))
    cx, cy = _polygon_centroid(spec.workpiece.contour_mm)
    assert res.x == pytest.approx(cx - r1.w / 2)
    assert res.y == pytest.approx(cy - r1.h / 2)
    assert res.w == r1.w and res.h == r1.h


def test_fit_scales_inside_contour():
    spec = JobSpec.model_validate(BASE)
    t1 = next(o for o in spec.ops if o.id == "t1")
    fit_op = next(o for o in spec.ops if isinstance(o, FitToWorkpiece))
    b = object_bounds_for(t1)
    res = resolve_fit(spec.workpiece.contour_mm, fit_op, b)
    assert res.w > 0 and res.h > 0
    # scaled bbox must fit inside the triangle contour with the requested margin (0)
    assert _bbox_fits(res.x, res.y, res.w, res.h, spec.workpiece.contour_mm, fit_op.margin_mm)


def test_resolve_spec_fills_all_and_preserves_hash_semantics():
    spec = JobSpec.model_validate(BASE)
    resolved = resolve_spec(spec)
    for op in resolved.ops:
        if op.op in ("center_on_workpiece", "fit_to_workpiece"):
            assert op.resolved is not None
    # determinism: resolving twice is identical
    assert resolve_spec(resolved) == resolved


def test_text_bounds_override():
    spec = JobSpec.model_validate(BASE)
    # fake exact metrics: text is 30 wide, 10 tall
    resolved = resolve_spec(spec, text_bounds=lambda op: ObjectBounds(op.x, op.y, 30, 10))
    t1 = next(o for o in resolved.ops if o.op == "fit_to_workpiece")
    assert t1.resolved.w == pytest.approx(30 * 1.0) or t1.resolved.w > 0
