"""Tests for trajectory replay (core/replay.py): order/direction, travel vs cutting, time,
reused limits, inferred op+colour from comments, and determinism.
"""
import pytest

from jobspec import JobSpec
from compiler import compile_gcode
from replay import replay_gcode

BASE = dict(module="laser_405", job_type="work",
            material=dict(id="ply3", category="safe"), params_version="m1",
            workpiece=dict(contour_mm=[(0, 0), (100, 0), (100, 60)],
                           registration_rms_mm=0.1, registration_max_mm=0.3),
            ops=[dict(op="add_rect", id="r1", x=10, y=20, w=8, h=6),
                 dict(op="set_pass", target="r1", power_pct=40, speed_mm_min=3000, passes=1)])


def _spec(**kw):
    return JobSpec.model_validate({**BASE, **kw})


def test_replay_single_rect_order_direction_time():
    r = replay_gcode(compile_gcode(_spec()))
    # one operation, a 4-segment CCW square (the compiler's convention)
    assert len(r.ops) == 1
    op = r.ops[0]
    assert op.op == "cut"                    # default op for a rect contour
    assert op.obj == "r1"
    assert op.direction == "ccw"
    assert op.cutting_moves == 4
    assert op.travel_moves == 2              # travel to corner + return between passes
    assert op.cutting_length_mm == 28.0      # 2*(8+6)
    assert op.passes == 1
    assert op.power_s == 102                 # 40% -> 102
    assert op.time_min > 0
    # every cut move is on the beam; every travel move is off (dashed in the preview)
    assert all(m.laser_on for m in op.moves if m.kind == "cut")
    assert all(not m.laser_on for m in op.moves if m.kind == "travel")


def test_replay_reuses_simulator_limits():
    r = replay_gcode(compile_gcode(_spec()))
    assert r.ok is True                       # the 0.2.0 compiler output passes the bound checks
    assert r.errors == []
    assert r.simulation.moves > 0

    # an out-of-bed program is rejected (limits come straight from the simulator)
    bad = "G21\nG90\nM3 S100\nG1 X300 Y0\nM5\n"
    rb = replay_gcode(bad)
    assert rb.ok is False
    assert any("X=300" in e for e in rb.errors)


def test_replay_infers_op_and_colour_from_layer_comment():
    gcode = (
        "G21\nG90\n"
        "; obj=a rect\n"
        "; Layer engrave #112233\n"
        "G1 X10 Y10 F2000\nM3 S100\n"
        "G1 X20 Y10 F2000\nG1 X20 Y20 F2000\nG1 X10 Y20 F2000\nG1 X10 Y10 F2000\nM5\n"
        "; obj=b outline\n"
        "; Layer cut #000000\n"
        "G1 X50 Y50 F3000\nM3 S180\nG1 X70 Y70 F3000\nM5\n"
    )
    r = replay_gcode(gcode)
    by_op = {o.obj: o for o in r.ops}
    assert set(by_op) == {"a", "b"}
    assert by_op["a"].op == "engrave" and by_op["a"].color == "#112233"
    assert by_op["b"].op == "cut" and by_op["b"].color == "#000000"
    # op a: one travel, four cuts, one pass, 40 mm of cutting
    assert by_op["a"].travel_moves == 1 and by_op["a"].cutting_moves == 4
    assert by_op["a"].passes == 1 and by_op["a"].power_s == 100
    assert by_op["a"].cutting_length_mm == 40.0
    assert r.total_time_min == round(sum(o.time_min for o in r.ops), 6)


def test_replay_multi_pass_counts():
    r = replay_gcode(compile_gcode(_spec(ops=[
        dict(op="add_rect", id="r1", x=10, y=20, w=8, h=6),
        dict(op="set_pass", target="r1", power_pct=40, speed_mm_min=1500, passes=3)])))
    op = r.ops[0]
    assert op.passes == 3
    assert op.cutting_moves == 12            # 4 segments x 3 passes
    assert op.cutting_length_mm == 84.0      # 28 x 3


def test_replay_deterministic():
    g = compile_gcode(_spec())
    a = replay_gcode(g)
    b = replay_gcode(g)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_replay_empty_has_no_ops():
    r = replay_gcode("G21\nG90\n")
    assert r.ops == []
    assert r.total_time_min == 0.0
