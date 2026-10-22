"""L7 · golden files: fixed resolved spec → expected G-code (sha256).

Each golden is the G-code the deterministic compiler emitted for a *fixed resolved*
spec, pinned to a sha256. Re-emitting the same spec must reproduce the exact hash;
any change in emission order, formatting, power scaling, kerf or layer order changes
the hash and fails the suite (regression catch for the compiler's output contract).

Regenerating a golden (only after the change is *intended* and reviewed):
    python3 -m test_golden_gcode --regen
"""
from __future__ import annotations

import hashlib
import sys

from jobspec import JobSpec, spec_hash
from jobspec2 import JobSpec2, migrate_020_to_030
from compiler import compile_gcode
from compiler2 import compile_jobspec2
from resolver import resolve_spec

# ---------------------------------------------------------------- fixed specs ---
GOLDEN_1_SPEC = dict(
    module="laser_405", job_type="work",
    material=dict(id="ply3", category="safe"), params_version="m1",
    workpiece=dict(contour_mm=[(0, 0), (100, 0), (100, 60)],
                   registration_rms_mm=0.1, registration_max_mm=0.3),
    ops=[dict(op="add_rect", id="r1", x=10, y=20, w=80, h=20),
         dict(op="set_pass", target="r1", power_pct=40, speed_mm_min=3000, passes=3),
         dict(op="set_depth", target="r1", depth_mm=-0.6, multi_pass_depth_mm=0.2),
         dict(op="set_tool", target="r1", tool="laser_405_10w", focus_z_mm=220.0)],
)

GOLDEN_2_SPEC = dict(   # resolved by the resolver before the gate
    module="laser_405", job_type="work",
    material=dict(id="ply3", category="safe"), params_version="m2",
    workpiece=dict(contour_mm=[(0, 0), (120, 0), (120, 80), (0, 80)],
                   registration_rms_mm=0.05, registration_max_mm=0.3),
    ops=[dict(op="add_rect", id="frame", x=0, y=0, w=20, h=20),
         dict(op="add_text", id="label", text="NATIVE", font="oswald",
              font_version="7", height_mm=6, x=0, y=0),
         dict(op="center_on_workpiece", target="frame"),
         dict(op="fit_to_workpiece", target="label", margin_mm=10),
         dict(op="set_pass", target="frame", power_pct=60, speed_mm_min=2400, passes=2),
         dict(op="set_pass", target="label", power_pct=30, speed_mm_min=5000, passes=1)],
)

GOLDEN_3_OLD = dict(    # 0.2.0 base, migrated to 0.3.0 with a kerf cut layer
    schema_version="0.2.0", module="laser_405", job_type="work",
    material=dict(id="ply3", category="safe"), params_version="m1",
    workpiece=dict(contour_mm=[(0, 0), (100, 0), (100, 60)],
                   registration_rms_mm=0.1, registration_max_mm=0.3),
    ops=[dict(op="add_rect", id="outer", x=10, y=10, w=80, h=40),
         dict(op="add_rect", id="inner", x=20, y=15, w=30, h=10),
         dict(op="set_pass", target="outer", power_pct=80, speed_mm_min=1200, passes=1),
         dict(op="set_pass", target="inner", power_pct=50, speed_mm_min=2000, passes=1)],
)
GOLDEN_3_SPEC = GOLDEN_3_OLD | dict(
    layers=[dict(op="cut", color="#000000", settings=dict(kerf_mm=0.2))],
)

# --------------------------------------------------------------- goldens (pin) ---
GOLDENS = [
    # (name, spec dict, spec schema version, gcode sha256)
    ("v020-single-rect-multipass-multi-drop",
     GOLDEN_1_SPEC, "0.2.0",
     "bcdf5ebd919b734d870a7df3d3ca5c382842d2ed41a7693b4eeb7ff7abc6af90"),
    ("v020-frame-and-label-resolved",
     GOLDEN_2_SPEC, "0.2.0",
     "0750dd7fa9d0f402b265a0b5e17f5a3eb6271e46189268415ab9c51760e02c03"),
    ("v030-kerf-cut-layer-order",
     GOLDEN_3_SPEC, "0.3.0",
     "ec48329a5e42a210fd06e5fa75bdd8eb5d8a89e52de631f4695f1f0f5dca95a7"),
]


def _sha(gcode: str) -> str:
    return hashlib.sha256(gcode.encode("utf-8")).hexdigest()


def _build(name: str, spec_dict: dict, version: str) -> tuple[object, str]:
    """Validate the fixed (resolved) spec and compile it with its compiler."""
    if version == "0.2.0":
        spec = JobSpec.model_validate(dict(spec_dict))
        if name.endswith("resolved"):
            spec = resolve_spec(spec)
        return spec, compile_gcode(spec)
    d = dict(spec_dict)
    d.setdefault("layers", [])
    spec = JobSpec2.model_validate(migrate_020_to_030(d))
    return spec, compile_jobspec2(spec)


def test_goldens_reproduce():
    for name, spec_dict, version, want in GOLDENS:
        spec, got = _build(name, spec_dict, version)
        assert _sha(got) == want, (
            "golden %r drifted: compiler now emits %s\n(first lines: %r)"
            % (name, _sha(got), got.splitlines()[:6]))


def test_determinism_same_spec_same_gcode():
    for name, spec_dict, version, _want in GOLDENS:
        _s1, a = _build(name, spec_dict, version)
        _s2, b = _build(name, spec_dict, version)
        assert a == b
