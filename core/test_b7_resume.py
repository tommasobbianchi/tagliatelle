"""B7 — stop / homing / re-registration / resume core: offline pytest (MASTER-DEV-PROMPT §10 B7).

Builds small deterministic compiled jobs (spec → compiler2 → gcode → replay), then walks the B7
acceptance lane: stop mid-job (audited), homing + new registration, resume from the START of the
interrupted operation (done ops dropped), gate the resume G-code, and produce the (unsaved) resume
recipe proposal. Every value is byte-stable; no hardware, no AI providers.
"""
from __future__ import annotations

import pytest

from compiler2 import compile_jobspec2
from jobspec2 import JobSpec2, migrate_020_to_030
from l8_b3 import build_spec
from mattarello import StopReason
from replay import replay_gcode
from b7_resume import (
    REG_MAX_MM,
    REG_RMS_MM,
    current_op_at,
    done_preview,
    gcode_sha256,
    homing_and_reregister,
    resume_gate,
    resume_gcode,
    resume_recipe_proposal,
    simulate_stop,
)

CONTOUR = [[20, 25], [180, 20], [185, 170], [15, 165]]
CONTOUR_R = [[round(p[0], 4), round(p[1], 4)] for p in CONTOUR]


def _interview(**over):
    iv = {
        "goal": "engrave a labeled material grid on plywood",
        "material": {"id": "plywood_3", "category": "safe", "thickness_mm": 3.0},
        "contour_mm": CONTOUR,
        "grid": {
            "axes": [
                {"axis": "x", "start": 0.0, "end": 60.0, "step": 30.0},   # 3 columns
                {"axis": "y", "start": 0.0, "end": 40.0, "step": 20.0},   # 3 rows
            ]
        },
        "params": {"power_pct": 30, "speed_mm_min": 3000, "passes": 1},
    }
    iv.update(over)
    return iv


def _grid_job():
    """3x3 labeled grid → 6 engraved label ops (all named `grid_lbl`, like the real compiler)."""
    spec = build_spec(_interview())
    gcode = compile_jobspec2(spec)
    replay = replay_gcode(gcode)
    assert replay.ok
    return spec, gcode, replay


def _two_rect_job():
    """Two cut rects with DISTINCT object ids → two ops (inner first, outline last)."""
    dump = {
        "schema_version": "0.2.0",
        "module": "laser_405",
        "job_type": "work",
        "material": {"id": "plywood_3", "category": "safe"},
        "params_version": "seed-405-v1",
        "workpiece": {
            "contour_mm": CONTOUR,
            "registration_rms_mm": 0.1,
            "registration_max_mm": 0.3,
        },
        "ops": [
            {"op": "add_rect", "id": "inner", "x": 40, "y": 30, "w": 40, "h": 20},
            {"op": "add_rect", "id": "outline", "x": 30, "y": 25, "w": 120, "h": 90},
            {"op": "set_pass", "target": "inner", "power_pct": 30, "speed_mm_min": 3000, "passes": 1},
            {"op": "set_pass", "target": "outline", "power_pct": 35, "speed_mm_min": 2500, "passes": 1},
        ],
    }
    spec = JobSpec2.model_validate(migrate_020_to_030(dump))
    gcode = compile_jobspec2(spec)
    replay = replay_gcode(gcode)
    assert replay.ok
    return spec, gcode, replay


def _split_ops(gcode: str) -> tuple[list, list]:
    """Split gcode at the `; obj=` boundaries (same rule as b7_resume) → (preamble, blocks)."""
    lines = gcode.splitlines()
    starts = [i for i, ln in enumerate(lines)
              if (s := ln.find(";")) != -1 and "obj=" in ln[s + 1:]]
    ends = starts[1:] + [len(lines)]
    return lines[: starts[0]], [lines[s:e] for s, e in zip(starts, ends)]


def _markers(gcode: str) -> int:
    return len(_split_ops(gcode)[1])


# ---------------------------------------------------------------------------
# jobs build + op/block alignment
# ---------------------------------------------------------------------------
def test_jobs_compile_and_ops_align_with_gcode_blocks():
    spec, gcode, replay = _grid_job()
    assert len(replay.ops) == 6                              # 3 row + 3 col engraved labels
    assert _markers(gcode) == len(replay.ops)                # resume split aligns 1:1
    assert all(o.time_min > 0 for o in replay.ops)
    assert round(sum(o.time_min for o in replay.ops), 6) == replay.total_time_min > 0

    _, gcode2, replay2 = _two_rect_job()
    assert [o.obj for o in replay2.ops] == ["inner", "outline"]   # cut order: inner → outline last
    assert _markers(gcode2) == 2


# ---------------------------------------------------------------------------
# replay boundary helpers
# ---------------------------------------------------------------------------
def test_current_op_at_maps_elapsed_minutes_to_the_operation_in_progress():
    spec, gcode, replay = _grid_job()
    ops = replay.ops

    # mid-op: the window [start, start + time) containing the elapsed time wins
    i, op = current_op_at(replay, replay.total_time_min / 2)
    assert 0 < i < len(ops) - 1 or i == len(ops) - 1         # some interior op
    assert op is ops[i]

    # exactly at a known op's midpoint (op 2 of the 6-op grid job)
    t2 = sum(o.time_min for o in ops[:2]) + ops[2].time_min / 2
    assert current_op_at(replay, t2) == (2, ops[2])

    # job start → the first timed op; job end → the last op
    i0, o0 = current_op_at(replay, 0.0)
    assert o0 is ops[i0] and o0.time_min > 0
    iend, oend = current_op_at(replay, replay.total_time_min)
    assert (iend, oend) == (len(ops) - 1, ops[len(ops) - 1])

    with pytest.raises(ValueError):
        current_op_at(replay, -0.1)


def test_done_preview_matches_the_replay():
    spec, gcode, replay = _grid_job()
    ops = replay.ops

    pv = done_preview(replay, 2)
    assert pv["done_ops"] == 2
    assert [d["index"] for d in pv["done_ops_list"]] == [0, 1]
    assert [d["obj"] for d in pv["done_ops_list"]] == [ops[0].obj, ops[1].obj]
    assert pv["completed_time_min"] == round(sum(o.time_min for o in ops[:2]), 6)
    assert pv["remaining_time_min"] == round(replay.total_time_min - pv["completed_time_min"], 6)
    assert pv["total_time_min"] == replay.total_time_min

    # stopping at the first op: nothing done, everything (re)run
    pv0 = done_preview(replay, 0)
    assert pv0["done_ops"] == 0 and pv0["done_ops_list"] == []
    assert pv0["completed_time_min"] == 0.0
    assert pv0["remaining_time_min"] == replay.total_time_min

    with pytest.raises(ValueError):
        done_preview(replay, len(ops))


# ---------------------------------------------------------------------------
# the simulated stop
# ---------------------------------------------------------------------------
def test_simulate_stop_appends_one_audit_entry_and_reports_the_stop_state():
    spec, gcode, replay = _grid_job()
    ops = replay.ops

    audit = []
    stop = simulate_stop(gcode, replay, 2, StopReason.LOST_CAMERA, audit=audit)
    assert len(audit) == 1                                  # exactly ONE audit entry
    e = audit[0]
    assert e == {
        "kind": "stop",
        "reason": "lost_camera",
        "op_index": 2,
        "at_time_min": round(sum(o.time_min for o in ops[:2]), 6),
    }
    assert stop["stopped"] is True
    assert stop["status"] == "stopped"
    assert stop["laser"] == "off"                           # fail-safe: the beam is off
    assert stop["reason"] == "lost_camera"
    assert stop["op_index"] == 2 and stop["op_obj"] == ops[2].obj
    assert stop["gcode_sha256"] == gcode_sha256(gcode)
    assert stop["done_preview"]["done_ops"] == 2

    # audit entries accumulate across stops, in order
    simulate_stop(gcode, replay, 3, StopReason.MOVED_WORKPIECE, audit=audit)
    assert [a["op_index"] for a in audit] == [2, 3]
    assert [a["reason"] for a in audit] == ["lost_camera", "moved_workpiece"]


def test_simulate_stop_reason_vocabulary_is_the_L5_one():
    spec, gcode, replay = _grid_job()
    audit = []
    stop = simulate_stop(gcode, replay, 0, "user", audit=audit)
    assert stop["reason"] == "user" and audit[0]["reason"] == "user"
    with pytest.raises(ValueError):
        simulate_stop(gcode, replay, 0, "not_a_stop_reason")
    with pytest.raises(ValueError):
        simulate_stop(gcode, replay, len(replay.ops), StopReason.USER)   # out-of-range op


# ---------------------------------------------------------------------------
# homing + new registration
# ---------------------------------------------------------------------------
def test_homing_and_reregister_returns_a_passing_new_registration():
    state = {"status": "stopped", "homed": False, "laser": "off"}

    r1 = homing_and_reregister(state, CONTOUR)
    assert r1["ok"] is True
    assert r1["homed"] is True
    assert r1["registration_rms_mm"] <= REG_RMS_MM
    assert r1["registration_max_mm"] <= REG_MAX_MM
    assert r1["reference_contour_mm"] == CONTOUR_R

    # deterministic: the same post-stop state + contour → the identical registration
    assert homing_and_reregister(state, CONTOUR) == r1


def test_homing_and_reregister_fails_closed_on_bad_input():
    with pytest.raises(ValueError):
        homing_and_reregister({"status": "stopped"}, [[0, 0], [10, 0]])   # < 3 points
    with pytest.raises(ValueError):
        homing_and_reregister({"status": "stopped"}, [[0, "a"]])          # non-numeric
    with pytest.raises(ValueError):
        homing_and_reregister("not-a-dict", CONTOUR)                      # state must be a dict


# ---------------------------------------------------------------------------
# resume G-code
# ---------------------------------------------------------------------------
def test_resume_gcode_excludes_done_ops_and_starts_the_interrupted_one_whole():
    spec, gcode, replay = _two_rect_job()
    ops = replay.ops
    assert [o.obj for o in ops] == ["inner", "outline"]

    g2, pv = resume_gcode(gcode, replay, 1)
    assert pv["ok"] is True
    assert pv["resumed_from_op_index"] == 1
    assert pv["resumed_obj"] == "outline" and pv["resumed_op"] == "cut"
    assert pv["skipped_ops"] == ["inner"]
    assert pv["resumed_ops"] == ["outline"]
    assert pv["skipped_time_min"] == round(ops[0].time_min, 6)
    assert pv["resumed_time_min"] == round(ops[1].time_min, 6)
    assert pv["n_ops_total"] == 2

    # the interrupted op, from its start; the completed one, dropped entirely
    assert _markers(gcode) == 2 and _markers(g2) == 1
    assert "obj=outline" in g2.split()
    assert "obj=inner" not in g2.split()

    # byte-level: preamble + one resume comment + exactly the original "outline" block
    pre1, blocks1 = _split_ops(gcode)
    pre2, blocks2 = _split_ops(g2)
    assert pre2 == pre1 + [
        "; B7 resume: skip 1 completed op(s); restart from outline (cut)"
    ]
    assert blocks2 == blocks1[1:]

    with pytest.raises(ValueError):
        resume_gcode(gcode, replay, 2)                                   # out of range
    with pytest.raises(ValueError):
        resume_gcode(gcode, replay, -1)


def test_resume_gcode_grid_job_resume_midway():
    spec, gcode, replay = _grid_job()
    assert _markers(gcode) == 6

    g3, pv = resume_gcode(gcode, replay, 3)
    assert pv["resumed_from_op_index"] == 3
    assert pv["skipped_ops"] == [o.obj for o in replay.ops[:3]]
    assert pv["resumed_ops"] == [o.obj for o in replay.ops[3:]]
    assert _markers(g3) == 3
    assert g3 != gcode

    # byte-level: same preamble+comment structure, op blocks 3..5 preserved
    pre1, blocks1 = _split_ops(gcode)
    pre3, blocks3 = _split_ops(g3)
    assert pre3 == pre1 + [
        "; B7 resume: skip 3 completed op(s); restart from grid_lbl (engrave)"
    ]
    assert blocks3 == blocks1[3:]


def test_resume_gcode_is_deterministic():
    spec, gcode, replay = _grid_job()
    g1, pv1 = resume_gcode(gcode, replay, 2)
    g2, pv2 = resume_gcode(gcode, replay, 2)
    assert g1 == g2 and pv1 == pv2
    assert gcode_sha256(g1) == gcode_sha256(g2)

    # two different jobs give different programs (no state leaking between calls)
    _, gcode_r, replay_r = _two_rect_job()
    gr, _ = resume_gcode(gcode_r, replay_r, 0)
    assert gr != g1


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------
def test_resume_gate_passes_a_valid_resume_and_reports_blockers():
    spec, gcode, replay = _two_rect_job()
    g2, _ = resume_gcode(gcode, replay, 0)
    assert resume_gate(g2) == []                                       # empty = ok to approve

    # an unsupported command / an off-bed move surface as blockers (the gate refuses)
    with_unsupported = resume_gate(g2 + "G28\n")
    assert with_unsupported and any("G28" in e for e in with_unsupported)
    assert resume_gate(gcode + "\nG1 X999 Y0 F1000\n")                 # beyond the 250 mm bed
    with pytest.raises(Exception):
        resume_gate(1)                                                 # not a string: fail closed


def test_resume_gate_flags_a_tampered_resume_program():
    spec, gcode, replay = _grid_job()
    g2, _ = resume_gcode(gcode, replay, 1)
    assert resume_gate(g2) == []
    bad = g2 + "G1 X-5 Y10 F1000\n"
    assert any("negative" in e for e in resume_gate(bad))


# ---------------------------------------------------------------------------
# the recipe proposal
# ---------------------------------------------------------------------------
def test_resume_recipe_proposal_shape_and_saved_only_on_approval():
    spec, gcode, replay = _grid_job()
    stop = simulate_stop(gcode, replay, 2, StopReason.MOVED_WORKPIECE)
    reg = homing_and_reregister(stop, CONTOUR)
    g2, pv = resume_gcode(gcode, replay, 2)

    base = {
        "material_id": "plywood_3",
        "params_version": "seed-405-v1",
        "z_mm": 220.0,
        "params": {"power_pct": 30, "speed_mm_min": 3000, "passes": 1, "power_cap": 60},
    }
    prop = resume_recipe_proposal(base, pv, reg)
    assert prop["type"] == "resume"
    assert prop["material_id"] == "plywood_3"
    assert prop["params_version"] == "seed-405-v1"
    assert prop["z_mm"] == 220.0
    assert prop["params"] == base["params"]
    assert prop["resume"] == pv                                       # the resume preview
    assert prop["resume"]["resumed_from_op_index"] == 2
    assert prop["registration"]["ok"] is True                         # the NEW registration
    assert prop["registration"]["reference_contour_mm"] == CONTOUR_R
    # proposed, NOT saved: saving is the approval step
    assert prop["approved"] is False
    assert prop["saved"] is False

    # deterministic for identical inputs
    assert resume_recipe_proposal(base, pv, reg) == resume_recipe_proposal(base, pv, reg)
    # copies: mutating the proposal never leaks into the caller's state
    prop["params"]["power_pct"] = 99
    assert base["params"]["power_pct"] == 30
    prop["resume"]["ok"] = False
    assert pv["ok"] is True

    with pytest.raises(TypeError):
        resume_recipe_proposal("nope", pv, reg)
    with pytest.raises(TypeError):
        resume_recipe_proposal(base, "nope", reg)


# ---------------------------------------------------------------------------
# the full B7 lane, in acceptance order
# ---------------------------------------------------------------------------
def test_b7_lane_stop_homing_resume_gate_proposal_in_order():
    spec, gcode, replay = _grid_job()
    ops = replay.ops

    # the job is mid-way: the elapsed minutes map to a known op
    elapsed = sum(o.time_min for o in ops[:3]) + ops[3].time_min / 2
    i, op = current_op_at(replay, elapsed)
    assert (i, op) == (3, ops[3])

    # stop (audited) → homing + new registration
    stop = simulate_stop(gcode, replay, i, StopReason.ALARM)
    assert stop["entry"]["kind"] == "stop" and stop["entry"]["reason"] == "alarm"
    reg = homing_and_reregister({"status": stop["status"], "homed": False}, CONTOUR)
    assert reg["ok"] is True and reg["homed"] is True

    # resume from the start of the interrupted op, through the gate
    g2, pv = resume_gcode(gcode, replay, i)
    assert pv["resumed_from_op_index"] == i
    assert resume_gate(g2) == []                       # cleared for the approval gate

    # the feedback's recipe proposal, still pending approval
    base = {
        "material_id": spec.material.id,
        "params_version": spec.params_version,
        "z_mm": 220.0,
        "params": {"power_pct": 30, "speed_mm_min": 3000, "passes": 1},
    }
    prop = resume_recipe_proposal(base, pv, reg)
    assert prop["type"] == "resume"
    assert prop["saved"] is False and prop["approved"] is False

    # and the whole lane is byte-stable on replay
    g2b, pvb = resume_gcode(gcode, replay, i)
    assert g2b == g2 and resume_gate(g2b) == [] and pvb == pv
