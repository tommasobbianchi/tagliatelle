"""L8 · B3 vertical — acceptance #2/#3/#4 (offline, deterministic, fake machine).

Extends `core/test_l8_b3.py` (acceptance #1) with the three remaining B3 acceptance items:

  * #2 preview–machine parity  — the replay shows *exactly* the compiled trajectories: every
    G-code XY move appears in the replay at the same coordinate, in the same order, within
    tolerance, and the replay has no extra moves.
  * #3 fault injection          — silent telemetry / moved marker / moved workpiece / lost camera,
    each stops the machine with its own L5 `StopReason` *and* appends one audit record.
  * #4 safety refusals          — unknown material / risky-without-declaration / power-above-cap /
    emission-without-user, each refused *before* any machine interaction (no server, no gcode).

Offline and deterministic: no AI-provider imports, no real network, no wall clock, no threads.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from l8_b3 import (
    assert_preview_machine_parity,
    build_spec,
    run_b3_fake,
    safety_blockers,
)
from compiler2 import compile_jobspec2
from replay import replay_gcode
from faults import FAULTS, FAULT_REASONS, FaultHarness, inject_fault, sample_telemetry

CONTOUR = [[20, 25], [180, 20], [185, 170], [15, 165]]

#: Fixed clock for the audit entry timestamps (so the harness output is byte-stable).
FIXED = datetime(2026, 1, 1, 0, 0, 0)


def _iv(**over):
    iv = {
        "goal": "engrave a labeled material grid on plywood",
        "material": {"id": "plywood_3", "category": "safe", "thickness_mm": 3.0},
        "contour_mm": CONTOUR,
        "grid": {"axes": [
            {"axis": "x", "start": 0.0, "end": 120.0, "step": 30.0},
            {"axis": "y", "start": 0.0, "end": 60.0, "step": 20.0},
        ]},
        "params": {"power_pct": 30, "speed_mm_min": 3000, "passes": 1},
        "cell": {"x": 95, "y": 62},
        "approved": True,
    }
    iv.update(over)
    return iv


def _fake_replay(*moves):
    """A minimal replay-shaped object (one op, N moves) to drive the parity checker in isolation."""
    op = SimpleNamespace(moves=[SimpleNamespace(x2=x, y2=y) for (x, y) in moves])
    return SimpleNamespace(ops=[op])


# ---------------------------------------------------------------------------
# acceptance #2 — preview machine parity
# ---------------------------------------------------------------------------
def test_parity_matches_the_compiled_gcode_in_the_happy_path():
    """run_b3_fake reports parity.ok for its own compiled gcode vs the replay it produces."""
    r = run_b3_fake(_iv())
    assert r["ok"] is True
    p = r["preview"]["parity"]
    assert p["ok"] is True and p["diffs"] == []
    assert p["n_gcode"] == p["n_replay"] and p["n_gcode"] > 0


def test_parity_matches_directly_for_compile_and_replay():
    spec = build_spec(_iv())
    gcode = compile_jobspec2(spec)
    replay = replay_gcode(gcode)
    p = assert_preview_machine_parity(gcode, replay)
    assert p["ok"] is True and p["diffs"] == []
    # tolerance must actually matter: at 1e-9 we only pass because the two agree exactly.
    assert assert_preview_machine_parity(gcode, replay, tol_mm=1e-9)["ok"] is True


def test_parity_fails_when_the_machine_goes_beyond_the_preview():
    """A G-code move the replay does not show = a real parity violation (no extra moves allowed)."""
    spec = build_spec(_iv())
    gcode = compile_jobspec2(spec)
    replay = replay_gcode(gcode)

    tampered = gcode + "\nG90\nG0 X99999.0 Y99999.0\n"   # one move beyond the preview
    p = assert_preview_machine_parity(tampered, replay)
    assert p["ok"] is False
    assert p["n_gcode"] == p["n_replay"] + 1
    assert any(d["kind"] == "missing_replay" for d in p["diffs"])


def test_parity_reports_coordinate_mismatch_extra_and_missing_moves():
    """All three diff kinds are reported deterministically when the two sequences diverge."""
    gcode = "G90\nG0 X10.0 Y10.0\nG0 X20.0 Y20.0"        # moves: (10,10) then (20,20)

    assert assert_preview_machine_parity(gcode, _fake_replay((10.0, 10.0), (20.0, 20.0)))["ok"] is True

    p_mis = assert_preview_machine_parity(gcode, _fake_replay((10.0, 10.0), (21.0, 20.0)))
    assert not p_mis["ok"] and any(d["kind"] == "mismatch" and d["index"] == 1 for d in p_mis["diffs"])

    p_miss = assert_preview_machine_parity(gcode, _fake_replay((10.0, 10.0)))
    assert not p_miss["ok"] and any(d["kind"] == "missing_replay" for d in p_miss["diffs"])

    p_extra = assert_preview_machine_parity(gcode, _fake_replay((10.0, 10.0), (20.0, 20.0), (30.0, 30.0)))
    assert not p_extra["ok"] and any(d["kind"] == "extra_replay" for d in p_extra["diffs"])


# ---------------------------------------------------------------------------
# acceptance #3 — fault injection: stop AND audit, deterministic per fault
# ---------------------------------------------------------------------------
def test_faults_are_exactly_the_four_stable_stop_reasons():
    assert FAULTS == ("silent_telemetry", "moved_marker", "moved_workpiece", "lost_camera")
    values = [FAULT_REASONS[f].value for f in FAULTS]
    assert values == list(FAULTS)          # each fault maps to its own stable value
    assert len(set(values)) == len(values)  # ... and the four are all distinct


def test_each_fault_stops_and_audits_its_own_reason():
    for fault in FAULTS:
        harness = FaultHarness(clock=lambda: FIXED, timeout=8.0)
        res = harness.inject(fault, sample_telemetry(fault))

        assert res["stopped"] is True, fault
        assert res["reason_value"] == fault, (fault, res["reason_value"])
        assert res["audit_len"] == 1

        entry = res["entry"]
        assert entry["fault"] == fault
        assert entry["stop_reason"] == fault
        assert entry["halt"], "the halt path was never exercised for %s" % fault
        assert entry["halt"][0]["kind"] == "injector"          # the (injected) halt actually fired
        assert entry["date"] == FIXED.isoformat()              # deterministic timestamp
        assert res["entry"] is harness.audit[-1]              # the audit record is durably appended


def test_inject_fault_one_shot_matches_the_harness():
    """The one-shot convenience returns the same stop reason + one audit entry as the harness."""
    for fault in FAULTS:
        res = inject_fault(fault, clock=lambda: FIXED)
        assert res["stopped"] is True and res["reason_value"] == fault
        assert res["audit_len"] == 1 and res["entry"]["stop_reason"] == fault


def test_healthy_readings_never_stop():
    """The fail-safe only trips when the threshold is actually crossed — a green reading stops nothing."""
    harness = FaultHarness(clock=lambda: FIXED)
    healthy_marker = {"registered_mm": (95.0, 62.0), "measured_mm": (95.0, 62.0)}   # 0 mm drift
    healthy_wp = {"registered_mm": (30.0, 10.0), "current_mm": (30.0, 10.0)}        # 0 mm deviation
    healthy_cam = {"camera_ok": True}
    silent_ok = {"telemetry_up": True}

    assert harness.inject("moved_marker", healthy_marker)["stopped"] is False
    assert harness.inject("moved_workpiece", healthy_wp)["stopped"] is False
    assert harness.inject("lost_camera", healthy_cam)["stopped"] is False
    assert harness.inject("silent_telemetry", silent_ok)["stopped"] is False
    assert harness.audit == []          # no audit entry for a single healthy reading


# ---------------------------------------------------------------------------
# acceptance #4 — safety refusals (each before any machine interaction)
# ---------------------------------------------------------------------------
def _assert_refused_before_machine(r, label):
    assert r["ok"] is False
    assert r["gate"]["blocked"] is True
    assert any(b.startswith(label + ":") for b in r["gate"]["blockers"]), r["gate"]["blockers"]
    # refused *before* any machine interaction: no session, no gcode, no active job, no recipe
    assert r["session"] is None and r["gcode"] is None and r["active_job"] is None
    assert r["cell"] is None and r["recipe"] is None and r["recipe_saved"] is False
    assert r["refusal"] is not None and "refused before machine interaction" in r["refusal"]


def test_refuse_unknown_material_before_machine():
    mat = {"id": "pvc_10", "category": "safe", "thickness_mm": 10.0}   # id not in the library
    r = run_b3_fake(_iv(material=mat))
    _assert_refused_before_machine(r, "unknown_material")


def test_refuse_risk_blocked_without_declaration_before_machine():
    mat = {"id": "acrylic_dark_3", "category": "risky", "thickness_mm": 3.0}   # registered, risky
    r = run_b3_fake(_iv(material=mat))
    _assert_refused_before_machine(r, "risk_blocked_without_declaration")
    # the refusal is caused by the *missing declaration*: present one and the block clears (power 30 <= 40 cap).
    ok = run_b3_fake(_iv(material=mat, declaration="I accept the risk of engraving this acrylic"))
    assert ok["ok"] is True and not any(b.startswith("risk_blocked") for b in ok["gate"]["blockers"])


def test_refuse_power_above_cap_before_machine():
    r = run_b3_fake(_iv(params={"power_pct": 70, "speed_mm_min": 3000, "passes": 1}))   # 70 > 60 safe cap
    _assert_refused_before_machine(r, "power_above_cap")


def test_refuse_emission_denied_without_user_before_machine():
    r = run_b3_fake(_iv(user_present=False))   # an emitting job with no user-present confirmation
    _assert_refused_before_machine(r, "emission_denied_without_user")


def test_safety_blockers_are_pre_machine_and_ordered():
    """safety_blockers is a pure, ordered pre-machine predicate (no server, no gcode)."""
    # baseline safe material: no safety blockers
    assert safety_blockers(_iv(), build_spec(_iv())) == []

    iv = _iv(material={"id": "acrylic_dark_3", "category": "risky", "thickness_mm": 3.0},
             params={"power_pct": 45})   # risky, no declaration, and above the 40% risky cap
    b = safety_blockers(iv, build_spec(iv))
    labels = [x.split(":", 1)[0] for x in b]
    assert "risk_blocked_without_declaration" in labels
    assert "power_above_cap" in labels
    # stable order: risk (2) precedes power (3)
    assert labels.index("risk_blocked_without_declaration") < labels.index("power_above_cap")
