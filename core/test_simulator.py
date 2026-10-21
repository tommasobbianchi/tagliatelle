"""Tests for the deterministic G-code simulator (core/simulator.py).

Covers the required E1.0 behaviour: a valid program, out-of-bed movement, an unsupported command,
relative (G91) resolution, the non-fatal missing-M5 warning, non-numeric / negative parameters, and
validate_against_spec rejecting a "work" job whose program never fires the laser.
"""
from jobspec import JobSpec
from simulator import simulate_gcode, validate_against_spec

# The canonical small valid laser program from the task spec.
VALID = (
    "G21\n"
    "G90\n"
    "G0 Z220\n"
    "M3 S100\n"
    "G1 X10 Y10\n"
    "M5\n"
)


def test_valid_program():
    r = simulate_gcode(VALID)
    assert r.ok is True
    assert r.errors == []
    assert r.laser_fired is True          # M3 S100
    assert r.moves >= 1
    assert (r.max_x, r.max_y, r.max_z) == (10.0, 10.0, 220.0)


def test_out_of_bed_x_is_error():
    r = simulate_gcode("G21\nG90\nG1 X300\n")
    assert r.ok is False
    assert any("X" in e and "300" in e for e in r.errors)


def test_negative_coordinate_is_error():
    r = simulate_gcode("G21\nG90\nG1 X-5 Y10\n")
    assert r.ok is False
    assert any("negative" in e for e in r.errors)


def test_unsupported_command_g99():
    r = simulate_gcode("G21\nG90\nG99\n")
    assert r.ok is False
    assert any("G99" in e for e in r.errors)


def test_non_numeric_parameter_is_error():
    r = simulate_gcode("G21\nG90\nG1 Xabc\n")
    assert r.ok is False
    assert any("non-numeric" in e for e in r.errors)


def test_relative_g91_resolves():
    # Absolute move to (100,0,0), then relative +50 in X -> (150,0,0).
    r = simulate_gcode("G21\nG90\nG0 X100\nG91\nG1 X50\n")
    assert r.ok is True
    assert r.moves == 2
    assert r.max_x == 150.0


def test_missing_m5_is_warning_not_error():
    r = simulate_gcode("G21\nG90\nG0 Z220\nM3 S100\nG1 X10 Y10\n")   # no M5
    assert r.ok is True
    assert r.laser_fired is True
    assert any("M5" in w for w in r.warnings)


def test_feeding_while_firing_has_no_feed_warning():
    r = simulate_gcode("G21\nG90\nG0 Z220\nM3 S100\nG1 X10 Y10 F1000\nM5\n")
    assert r.ok is True
    assert not any("feed" in w.lower() for w in r.warnings)


def _spec(**kw) -> JobSpec:
    base = dict(
        module="laser_405",
        job_type="work",
        material=dict(id="ply3", category="safe"),
        params_version="m1",
        workpiece=dict(contour_mm=[(0, 0), (100, 0), (100, 60)],
                       registration_rms_mm=0.1, registration_max_mm=0.3),
        ops=[
            dict(op="add_rect", id="r1", x=10, y=10, w=20, h=20),
            dict(op="set_pass", target="r1", power_pct=40, speed_mm_min=1500, passes=1),
        ],
    )
    return JobSpec.model_validate({**base, **kw})


def test_validate_against_spec_no_fire_is_error():
    spec = _spec()
    gcode = "G21\nG90\nG0 Z220\nG1 X50 Y50\nM5\n"          # moves but never fires the beam
    r = validate_against_spec(gcode, spec)
    assert r.ok is False
    assert any("laser" in e.lower() and "work" in e.lower() for e in r.errors)


def test_validate_against_spec_fire_is_ok():
    spec = _spec()
    gcode = "G21\nG90\nG0 Z220\nM3 S100\nG1 X50 Y50 F1000\nM5\n"
    r = validate_against_spec(gcode, spec)
    assert r.ok is True
    assert r.laser_fired is True


def test_validate_against_spec_out_of_bed_is_error():
    spec = _spec()
    gcode = "G21\nG90\nM3 S100\nG1 X300 Y0\nM5\n"          # X=300 exceeds BED_MM
    r = validate_against_spec(gcode, spec)
    assert r.ok is False
