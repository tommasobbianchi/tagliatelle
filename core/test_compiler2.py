"""Tests for the 0.3.0 compiler (core/compiler2.py): layer order, kerf offset, multi-pass,
engraved grid labels, and full-path determinism. Also crosses into replay to prove the emitted
G-code round-trips into a valid, correctly-ordered preview.
"""
import pytest

from jobspec2 import JobSpec2
from compiler2 import compile_jobspec2
from replay import replay_gcode

BASE = dict(
    schema_version="0.3.0",
    module="laser_405",
    job_type="work",
    material=dict(id="ply3", category="safe"),
    params_version="m1",
    workpiece=dict(contour_mm=[(0, 0), (100, 0), (100, 60)],
                   registration_rms_mm=0.1, registration_max_mm=0.3,
                   constraints=[], modified=False),
)


def _s2(**kw):
    d = dict(BASE)
    d.update(kw)
    return JobSpec2.model_validate(d)


def test_layer_order_engrave_before_cut():
    spec = _s2(ops=[
        dict(op="add_rect", id="r9", x=10, y=20, w=8, h=6),
        dict(op="add_text", id="t1", text="Hi", font="dejavu", font_version="2.37", height_mm=5, x=30, y=70),
        dict(op="set_pass", target="r9", power_pct=50, speed_mm_min=3000, passes=1),
        dict(op="set_pass", target="t1", power_pct=30, speed_mm_min=2000, passes=1),
    ])
    out = compile_jobspec2(spec)
    # engrave (text) is emitted before the cut (rect), regardless of op-list order
    assert out.index("obj=t1") < out.index("obj=r9")
    r = replay_gcode(out)
    assert [o.op for o in r.ops] == ["engrave", "cut"]
    assert r.ok is True


def test_inner_cuts_before_outer_contour_last():
    # two cut rectangles: the larger one (outer contour) must be cut last
    spec = _s2(ops=[
        dict(op="add_rect", id="r_big", x=5, y=5, w=40, h=40),
        dict(op="add_rect", id="r_small", x=20, y=20, w=10, h=10),
        dict(op="set_pass", target="r_big", power_pct=50, speed_mm_min=2000, passes=1),
        dict(op="set_pass", target="r_small", power_pct=50, speed_mm_min=2000, passes=1),
    ])
    out = compile_jobspec2(spec)
    assert out.index("obj=r_small") < out.index("obj=r_big")
    r = replay_gcode(out)
    assert [o.obj for o in r.ops] == ["r_small", "r_big"]


def test_kerf_half_offset_geometry():
    # rect 10,20,8,6 with kerf_mm=0.5 -> hk=0.25 -> 10.25,20.25,7.5,5.5
    spec = _s2(
        layers=[dict(op="cut", color="#000000", settings=dict(kerf_mm=0.5))],
        ops=[dict(op="add_rect", id="r1", x=10, y=20, w=8, h=6),
             dict(op="set_pass", target="r1", power_pct=50, speed_mm_min=3000, passes=1)],
    )
    out = compile_jobspec2(spec)
    assert "X10.25 Y20.25" in out            # bottom-left shifted in by the half-kerf
    assert "X17.75 Y20.25" in out            # bottom-right: 10.25 + 7.5
    assert "Y25.75" in out                    # top: 20.25 + 5.5
    r = replay_gcode(out)
    assert abs(r.ops[0].cutting_length_mm - 26.0) < 1e-6   # 2*(7.5+5.5)
    assert "; kerf_mm=0.50" in out


def test_kerf_not_applied_when_it_would_invert():
    # kerf (2*hk) >= a side -> no offset, shape unchanged
    spec = _s2(
        layers=[dict(op="cut", color="#000", settings=dict(kerf_mm=1.0))],
        ops=[dict(op="add_rect", id="r1", x=10, y=20, w=1, h=6),
             dict(op="set_pass", target="r1", power_pct=50, speed_mm_min=3000, passes=1)],
    )
    out = compile_jobspec2(spec)
    assert "X10.00 Y20.00" in out            # unchanged (2*0.5=1.0 >= w=1)
    assert out.count("; kerf_mm=1.00") == 0   # no applied-kerf marker emitted


def test_engraved_grid_labels_as_text_placeholders():
    spec = _s2(ops=[
        dict(op="add_material_grid", id="g1",
             axes=[dict(axis="x", start=10, end=40, step=10),
                   dict(axis="y", start=10, end=20, step=10)],
             row_labels=["A", "B"], col_labels=["1", "2", "3", "4"], x=30, y=40),
        dict(op="set_pass", target="g1", power_pct=25, speed_mm_min=4000, passes=1),
    ])
    out = compile_jobspec2(spec)
    assert out.count("obj=g1_lbl") == 6       # 2 rows + 4 columns
    assert out.count("Layer engrave") == 6
    r = replay_gcode(out)
    assert len(r.ops) == 6
    assert all(o.op == "engrave" and o.obj == "g1_lbl" for o in r.ops)
    assert r.ok is True                        # labels stay inside the bed (grid placed with margin)


def test_multi_pass_emitted():
    spec = _s2(ops=[
        dict(op="add_rect", id="r1", x=10, y=20, w=8, h=6),
        dict(op="set_pass", target="r1", power_pct=40, speed_mm_min=1500, passes=2),
        dict(op="set_depth", target="r1", depth_mm=-0.4, multi_pass_depth_mm=0.2),
    ])
    out = compile_jobspec2(spec)
    assert out.count("M3") == 2
    assert out.count("G91") == 2
    assert "G0 Z-0.20" in out
    r = replay_gcode(out)
    assert r.ops[0].passes == 2
    assert r.ops[0].cutting_moves == 8


def test_no_power_fails_closed():
    spec = _s2(ops=[dict(op="add_rect", id="r1", x=10, y=20, w=8, h=6)])
    with pytest.raises(ValueError):
        compile_jobspec2(spec)


def test_minimal_single_rect_round_trips():
    # the smallest valid 0.3.0 spec: one rect + its set_pass, no layers
    spec = _s2(ops=[dict(op="add_rect", id="r1", x=10, y=20, w=8, h=6),
                   dict(op="set_pass", target="r1", power_pct=50, speed_mm_min=3000, passes=1)])
    out = compile_jobspec2(spec)
    assert "G21" in out and "G90" in out and "M3" in out
    assert out.startswith("; TaglIAtelle E2.0 compiler")
    r = replay_gcode(out)
    assert r.ok is True and len(r.ops) == 1 and r.ops[0].op == "cut"


def test_deterministic_whole_path():
    spec = _s2(
        layers=[dict(op="cut", color="#000", settings=dict(kerf_mm=0.5))],
        ops=[
            dict(op="add_text", id="t1", text="Ciao", font="dejavu", font_version="2.37", height_mm=6, x=25, y=80),
            dict(op="add_material_grid", id="g1",
                 axes=[dict(axis="x", start=10, end=40, step=10), dict(axis="y", start=10, end=20, step=10)],
                 row_labels=["A", "B"], col_labels=["1", "2", "3", "4"], x=30, y=40),
            dict(op="add_rect", id="r1", x=10, y=20, w=8, h=6),
            dict(op="set_pass", target="t1", power_pct=30, speed_mm_min=2000, passes=1),
            dict(op="set_pass", target="g1", power_pct=25, speed_mm_min=4000, passes=1),
            dict(op="set_pass", target="r1", power_pct=50, speed_mm_min=3000, passes=2),
            dict(op="set_depth", target="r1", depth_mm=-0.4, multi_pass_depth_mm=0.2),
        ],
    )
    a = compile_jobspec2(spec)
    b = compile_jobspec2(spec)
    assert a == b
    assert a.endswith("\n")
    # full-path determinism survives a freshly re-validated spec instance and a replay round-trip
    fresh = JobSpec2.model_validate(spec.model_dump())
    r1 = replay_gcode(compile_jobspec2(fresh))
    r2 = replay_gcode(compile_jobspec2(spec))
    assert r1.model_dump(mode="json") == r2.model_dump(mode="json")
    assert r1.ok is True
