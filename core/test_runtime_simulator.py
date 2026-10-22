"""L7 · the simulator gate at runtime: every compiled G-code must pass validation.

SPEC §11: "Simulatore G-code anche a runtime: ogni G-code passa dal simulatore prima
della dispatch (limiti, laser-fire, stato modale)." These tests sample the compiled
outputs of the core pipeline (resolved 0.2.0 jobs, multi-pass, text + center/fit,
and the 0.3.0 kerf/layer-order job) and assert the simulation gate accepts them —
and that the gate is not a rubber stamp (an out-of-bed program must be rejected).
"""
from __future__ import annotations

from jobspec import JobSpec
from jobspec2 import JobSpec2, migrate_020_to_030
from compiler import compile_gcode
from compiler2 import compile_jobspec2
from resolver import resolve_spec
from simulator import simulate_gcode, validate_against_spec

WP = dict(contour_mm=[(0, 0), (100, 0), (100, 60)],
          registration_rms_mm=0.1, registration_max_mm=0.3)

SPECS_020 = [
    ("single-rect",
     dict(module="laser_405", job_type="work", material=dict(id="ply3", category="safe"),
          params_version="m1", workpiece=WP,
          ops=[dict(op="add_rect", id="r1", x=10, y=20, w=8, h=6),
               dict(op="set_pass", target="r1", power_pct=40, speed_mm_min=3000, passes=1)])),
    ("multipass-depth",
     dict(module="laser_405", job_type="work", material=dict(id="ply3", category="safe"),
          params_version="m1", workpiece=WP,
          ops=[dict(op="add_rect", id="r1", x=10, y=20, w=80, h=20),
               dict(op="set_pass", target="r1", power_pct=40, speed_mm_min=3000, passes=3),
               dict(op="set_depth", target="r1", depth_mm=-0.6, multi_pass_depth_mm=0.2)])),
    ("frame-center-and-label-fit",
     dict(module="laser_405", job_type="work", material=dict(id="ply3", category="safe"),
          params_version="m2",
          workpiece=dict(contour_mm=[(0, 0), (120, 0), (120, 80), (0, 80)],
                         registration_rms_mm=0.05, registration_max_mm=0.3),
          ops=[dict(op="add_rect", id="frame", x=0, y=0, w=20, h=20),
               dict(op="add_text", id="label", text="NATIVE", font="oswald",
                    font_version="7", height_mm=6, x=0, y=0),
               dict(op="center_on_workpiece", target="frame"),
               dict(op="fit_to_workpiece", target="label", margin_mm=10),
               dict(op="set_pass", target="frame", power_pct=60, speed_mm_min=2400, passes=2),
               dict(op="set_pass", target="label", power_pct=30, speed_mm_min=5000, passes=1)])),
    ("two-rects",
     dict(module="laser_405", job_type="work", material=dict(id="ply3", category="safe"),
          params_version="m1", workpiece=WP,
          ops=[dict(op="add_rect", id="a", x=5, y=5, w=40, h=10),
               dict(op="add_rect", id="b", x=50, y=30, w=30, h=8),
               dict(op="set_pass", target="a", power_pct=50, speed_mm_min=2000, passes=1),
               dict(op="set_pass", target="b", power_pct=70, speed_mm_min=1500, passes=2),
               dict(op="set_depth", target="b", depth_mm=-0.3, multi_pass_depth_mm=0.0)])),
]

OLD_030 = dict(schema_version="0.2.0", module="laser_405", job_type="work",
               material=dict(id="ply3", category="safe"), params_version="m1",
               workpiece=WP,
               ops=[dict(op="add_rect", id="outer", x=10, y=10, w=80, h=40),
                    dict(op="add_rect", id="inner", x=20, y=15, w=30, h=10),
                    dict(op="set_pass", target="outer", power_pct=80, speed_mm_min=1200, passes=1),
                    dict(op="set_pass", target="inner", power_pct=50, speed_mm_min=2000, passes=1)])


def test_every_compiled_gcode_passes_the_gate():
    failures = []
    for name, d in SPECS_020:
        spec = resolve_spec(JobSpec.model_validate(d))
        r = validate_against_spec(compile_gcode(spec), spec)
        assert r.ok, "%s: gate rejected: %s" % (name, r.errors)
        assert r.laser_fired, "%s: work job must fire the laser" % name

    # 0.3.0 job: validate_against_spec is bound to the 0.2.0 JobSpec, so use the
    # machine-contract simulator (same bed/axis and laser-fire checks) as the gate.
    d = dict(OLD_030)
    d["layers"] = [dict(op="cut", color="#000000", settings=dict(kerf_mm=0.2))]
    spec3 = JobSpec2.model_validate(migrate_020_to_030(d))
    r3 = simulate_gcode(compile_jobspec2(spec3))
    assert r3.ok, "v0.3.0 gate rejected: %s" % r3.errors
    assert r3.laser_fired


def test_gate_rejects_out_of_bed_move():
    # the gate must be real: a move beyond the bed is a hard error
    bad = "G21\nG90\nG0 Z220\nM5\nG1 X300 Y0 F1000\nM3 S102\nG1 X301 Y0 F1000\nM5\nG0 Z220\n"
    d = SPECS_020[0][1]
    r = validate_against_spec(bad, JobSpec.model_validate(d))
    assert not r.ok
    assert any("exceeds bed limit" in e for e in r.errors)


def test_gate_rejects_unsupported_command():
    bad = "G21\nG90\nG42\nM3 S102\nG1 X10 Y10 F1000\n"
    d = SPECS_020[0][1]
    r = validate_against_spec(bad, JobSpec.model_validate(d))
    assert not r.ok
    assert any("unsupported" in e for e in r.errors)
