import pytest
from jobspec import JobSpec
from compiler import compile_gcode
from gcode_scan import is_active

BASE = dict(module="laser_405", job_type="work",
            material=dict(id="ply3", category="safe"), params_version="m1",
            workpiece=dict(contour_mm=[(0, 0), (100, 0), (100, 60)],
                           registration_rms_mm=0.1, registration_max_mm=0.3),
            ops=[dict(op="add_rect", id="r1", x=10, y=20, w=8, h=6),
                 dict(op="set_pass", target="r1", power_pct=40, speed_mm_min=3000, passes=1)])


def make(**kw):
    return JobSpec.model_validate({**BASE, **kw})


def test_determinism():
    a = compile_gcode(make())
    b = compile_gcode(make())
    assert a == b
    assert isinstance(a, str)
    assert a.endswith("\n")


def test_is_active_via_scan():
    # the gate's active-job scan must see this as an active (laser) job
    assert is_active(compile_gcode(make()))


def test_simple_rect_contains_required_commands():
    out = compile_gcode(make())
    for token in ("G21", "G90", "M3", "M5", "S102", "F3000"):
        assert token in out, token
    assert out.startswith("; TaglIAtelle E1.0 compiler")
    assert "schema_version: 0.2.0" in out          # deterministic header, not a timestamp
    # laser on (S) precedes the drawing moves; the final laser-off is present
    s_idx = out.find("M3")
    assert s_idx != -1
    assert "X18.00 Y20.00" in out                 # rect top-right corner (x=10+8, y=20)


def test_power_mapping_pct_to_s():
    for pct, want in [(0, 0), (40, 102), (60, 153), (100, 255)]:
        out = compile_gcode(make(ops=[
            dict(op="add_rect", id="r1", x=0, y=0, w=5, h=5),
            dict(op="set_pass", target="r1", power_pct=pct, speed_mm_min=1000, passes=1)]))
        assert ("M3 S%d" % want) in out, (pct, want)


def test_precision_two_decimals():
    out = compile_gcode(make(ops=[
        dict(op="add_rect", id="r1", x=1.2345, y=-0.0, w=2.565, h=3.0049),
        dict(op="set_pass", target="r1", power_pct=50, speed_mm_min=1500, passes=1)]))
    assert "X1.23" in out
    assert "X3.80" in out            # 1.2345 + 2.565 = 3.7995 -> 3.80
    assert "Y3.00" in out


def test_multi_pass_depth_relative_z():
    out = compile_gcode(make(ops=[
        dict(op="add_rect", id="r1", x=10, y=20, w=8, h=6),
        dict(op="set_pass", target="r1", power_pct=40, speed_mm_min=1500, passes=1),
        dict(op="set_depth", target="r1", depth_mm=-0.5, multi_pass_depth_mm=0.2)]))
    assert "G91" in out
    assert "G0 Z-0.20" in out
    assert "G90" in out
    # G91 relative block is closed by G90 before returning to absolute XY
    g91 = out.index("G91")
    g0z = out.index("G0 Z-", g91)
    g90 = out.index("G90", g0z)
    assert g91 < g0z < g90


def test_resolved_placement_uses_resolved_xy():
    ops = list(BASE["ops"])
    ops.append(dict(op="center_on_workpiece",
                    target="r1",
                    resolved=dict(x=10, y=22, w=8, h=6)))
    out = compile_gcode(JobSpec.model_validate({**BASE, "ops": ops}))
    assert "X10.00 Y22.00" in out          # placed at resolved x,y, not the raw object y
    assert "X18.00 Y22.00" in out          # resolved width applied


def test_text_placeholder_emits_rect():
    out = compile_gcode(JobSpec.model_validate({**BASE, "ops": [
        dict(op="add_text", id="t1", text="Ciao", font="dejavu", font_version="2.37",
             height_mm=10, x=5, y=5),
        dict(op="set_pass", target="t1", power_pct=30, speed_mm_min=2000, passes=1)]}))
    assert "placeholder rect" in out          # glyph outline out of scope for this slice
    assert "M3" in out and "M5" in out


def test_no_set_pass_fails_closed():
    bad = JobSpec.model_validate({**BASE, "ops": [
        dict(op="add_rect", id="r1", x=0, y=0, w=5, h=5)]})
    with pytest.raises(ValueError):
        compile_gcode(bad)
