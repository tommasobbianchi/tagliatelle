"""B7 — deterministic stop / homing / re-registration / resume core (MASTER-DEV-PROMPT §10 B7).

After a simulated mid-job stop, the acceptance path is:
  1. `simulate_stop`            — the stop in the L5 Watchdog/fault style (a `StopReason`, one audit entry);
  2. `homing_and_reregister`    — homing + a NEW registration against the workpiece reference contour;
  3. `resume_gcode`             — G-code that re-runs from the START of the interrupted operation
                                  (fully-completed ops are dropped, the interrupted one restarts whole);
  4. `resume_gate`              — the deterministic simulator gate on the resume G-code (blockers, empty = ok);
  5. `resume_recipe_proposal`   — the recipe proposal for the resumed job, to approve (and only then save).

Deterministic and offline: stdlib + pydantic + the already-merged deterministic core
(`replay`, `simulator`) + the L5 `mattarello` `StopReason` vocabulary only. No model/provider
imports, no threads, no wall clock, no real hardware. Same inputs → byte-stable resume G-code.

The operation boundary is the same one `replay.replay_gcode` uses: a `; obj=<id>` comment starts an
operation block, so the resume split of the compiled G-code is aligned 1:1 with the replay's `Op`s.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import zlib
from math import isfinite
from pathlib import Path

# ---- make the sibling `tools/` package importable (core/ is not a python package) ----
_CORE_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = str(_CORE_DIR.parent / "tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from jobspec import FOCAL_Z_MM          # noqa: E402
from replay import Op, ReplayResult     # noqa: E402
from simulator import simulate_gcode    # noqa: E402
from mattarello import StopReason       # noqa: E402

__all__ = [
    "REG_RMS_MM",
    "REG_MAX_MM",
    "gcode_sha256",
    "current_op_at",
    "done_preview",
    "simulate_stop",
    "homing_and_reregister",
    "resume_gcode",
    "resume_gate",
    "resume_recipe_proposal",
]

#: Per-job registration thresholds (mm) — the calib register gate defaults (tools/executor/calib.py).
REG_RMS_MM = 0.5
REG_MAX_MM = 1.0

_OBJ = re.compile(r"obj=(\S+)")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def gcode_sha256(gcode: str) -> str:
    """Stable digest of a G-code program (determinism / audit reference)."""
    return hashlib.sha256(gcode.encode("utf-8")).hexdigest()


def _ops(replay: ReplayResult) -> list[Op]:
    ops = list(getattr(replay, "ops", None) or [])
    if not ops:
        raise ValueError("replay has no ops — nothing to progress, stop or resume")
    return ops


def _check_index(op_index: int, n: int) -> None:
    if not (isinstance(op_index, int) and not isinstance(op_index, bool)) or not (0 <= op_index < n):
        raise ValueError("op_index %s out of range (replay has %d ops)" % (op_index, n))


def _as_stop_reason(reason) -> StopReason:
    """Normalize a stop reason to the L5 `mattarello.StopReason` vocabulary (fail closed on unknown)."""
    if isinstance(reason, StopReason):
        return reason
    if isinstance(reason, str):
        try:
            return StopReason(reason)
        except ValueError:
            pass
    raise ValueError(
        "stop_reason must be a mattarello StopReason or one of: %s"
        % ", ".join(s.value for s in StopReason)
    )


def _op_block_starts(gcode: str) -> list[int]:
    """0-based line indices where an operation block starts — the same `; obj=<id>` boundary rule
    `replay.replay_gcode` uses to delimit ops, so blocks and `replay.ops` align 1:1 for compiler G-code."""
    out: list[int] = []
    for i, raw in enumerate(gcode.splitlines()):
        semi = raw.find(";")
        if semi != -1 and _OBJ.search(raw[semi + 1:]):
            out.append(i)
    return out


# ---------------------------------------------------------------------------
# 1) replay boundary helpers
# ---------------------------------------------------------------------------
def current_op_at(replay: ReplayResult, progress_min: float) -> tuple[int, Op]:
    """Which operation was in progress at `progress_min` (elapsed job minutes).

    The replay's ops carry per-op `time_min`; the op in progress is the one whose
    `[start, start + time_min)` window contains the elapsed time. Elapsed time beyond the
    total clamps to the last op (the job "ended" inside it); a negative progress is a caller error.
    Zero-time ops are skipped by the window test and resolved by the start boundary.
    """
    ops = _ops(replay)
    p = float(progress_min)
    if not isfinite(p) or p < 0.0:
        raise ValueError("progress_min must be a finite number >= 0 (got %s)" % (progress_min,))
    starts: list[float] = []
    acc = 0.0
    for o in ops:
        starts.append(acc)
        acc += o.time_min
    for i in range(len(ops)):
        if ops[i].time_min > 0 and starts[i] <= p < starts[i] + ops[i].time_min:
            return i, ops[i]
    for i in range(len(ops)):
        if starts[i] >= p:
            return i, ops[i]
    return len(ops) - 1, ops[-1]


def done_preview(replay: ReplayResult, op_index: int) -> dict:
    """What is already done, as of stopping with op `op_index` in progress (its start resumes).

    {done_ops, done_ops_list, completed_time_min, remaining_time_min, total_time_min} —
    `done_ops` is the count of fully-completed operations (those before the interrupted one) and
    `remaining_time_min` is the time the resume G-code will spend (includes the interrupted op).
    """
    ops = _ops(replay)
    _check_index(op_index, len(ops))
    completed = round(sum(o.time_min for o in ops[:op_index]), 6)
    total = round(float(replay.total_time_min), 6)
    return {
        "done_ops": op_index,
        "done_ops_list": [
            {"index": i, "obj": o.obj, "op": o.op, "time_min": o.time_min}
            for i, o in enumerate(ops[:op_index])
        ],
        "completed_time_min": completed,
        "remaining_time_min": round(total - completed, 6),
        "total_time_min": total,
    }


# ---------------------------------------------------------------------------
# 2) the simulated stop (L5 Watchdog/fault style) — records state + one audit entry
# ---------------------------------------------------------------------------
def simulate_stop(gcode: str, replay: ReplayResult, at_op_index: int, stop_reason, audit: list | None = None) -> dict:
    """Record the simulated stop during op `at_op_index`, in the L5 stop style.

    The stop reason must be (or normalize to) one of the L5 `mattarello.StopReason` values.
    Exactly ONE audit entry is appended (to `audit` when given, else a fresh list):
    `{kind: "stop", reason, op_index, at_time_min}` where `at_time_min` is the completed time at
    the start of the interrupted op (the only determinate stop time once only the op index is
    known). The stop state is fail-safe: the laser is reported off. Same inputs → same state.
    """
    ops = _ops(replay)
    _check_index(at_op_index, len(ops))
    reason = _as_stop_reason(stop_reason)
    at_time_min = round(sum(o.time_min for o in ops[:at_op_index]), 6)

    entry = {
        "kind": "stop",
        "reason": reason.value,
        "op_index": at_op_index,
        "at_time_min": at_time_min,
    }
    if audit is None:
        audit = []
    audit.append(entry)

    return {
        "ok": True,
        "stopped": True,
        "status": "stopped",
        "laser": "off",
        "reason": reason.value,
        "op_index": at_op_index,
        "op_obj": ops[at_op_index].obj,
        "at_time_min": at_time_min,
        "entry": entry,
        "audit": audit,
        "audit_len": len(audit),
        "gcode_sha256": gcode_sha256(gcode) if isinstance(gcode, str) else None,
        "done_preview": done_preview(replay, at_op_index),
    }


# ---------------------------------------------------------------------------
# 3) homing + NEW registration (deterministic fake of the calib register gate)
# ---------------------------------------------------------------------------
def _validate_contour(ref_contour_mm) -> list[list[float]]:
    """The workpiece reference contour: >= 3 finite (x, y) pairs, rounded for a stable digest."""
    if isinstance(ref_contour_mm, str) or ref_contour_mm is None:
        raise ValueError("ref_contour_mm must be a list of (x, y) points")
    pts: list[list[float]] = []
    for p in ref_contour_mm:
        try:
            x, y = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            raise ValueError("ref_contour_mm point %r is not a finite (x, y) pair" % (p,))
        if not (isfinite(x) and isfinite(y)):
            raise ValueError("ref_contour_mm point %r is not finite" % (p,))
        pts.append([round(x, 4), round(y, 4)])
    if len(pts) < 3:
        raise ValueError("ref_contour_mm needs >= 3 corner points for registration (got %d)" % len(pts))
    return pts


def homing_and_reregister(session_state: dict, ref_contour_mm) -> dict:
    """Homing + a NEW registration after the stop (deterministic stand-in for executor/calib.py's
    `register` gate, which needs a live camera and therefore cannot run offline here).

    `session_state` is the post-stop state (any dict; typically the `simulate_stop` result or
    `{"status": "stopped", "homed": False}`). The new registration residual is a deterministic
    function of the reference contour (CRC over the rounded corners): a small, in-threshold
    rms/max pair, so a sane registration passes its gate. Returns
    `{registration_rms_mm, registration_max_mm, reference_contour_mm, ok}` (+ `homed` and the two
    gate thresholds). Same inputs → identical result.
    """
    if not isinstance(session_state, dict):
        raise ValueError("session_state must be a dict (the post-stop state)")
    pts = _validate_contour(ref_contour_mm)

    crc = zlib.crc32(json.dumps(pts).encode("utf-8"))
    rms = round(0.05 + ((crc & 0xFF) + 1) * 0.0005, 4)          # 0.051 .. 0.1285 mm — in gate
    mx = round(rms + 0.10 + ((crc >> 8) & 0xFF) * 0.0005, 4)    # <= 0.3885 mm — in gate
    ok = rms <= REG_RMS_MM and mx <= REG_MAX_MM

    return {
        "ok": bool(ok),
        "homed": True,
        "registration_rms_mm": rms,
        "registration_max_mm": mx,
        "reference_contour_mm": pts,
        "rms_limit_mm": REG_RMS_MM,
        "max_limit_mm": REG_MAX_MM,
    }


# ---------------------------------------------------------------------------
# 4) resume G-code: from the START of the interrupted op (done ops dropped)
# ---------------------------------------------------------------------------
def resume_gcode(gcode: str, replay: ReplayResult, op_index: int) -> tuple[str, dict]:
    """Emit G-code that re-runs from the START of op `op_index`.

    The compiled program is split at the same `; obj=` boundaries the replay uses: the preamble
    (units/absolute + header) is kept, operation blocks strictly before `op_index` are dropped,
    and the interrupted block is included whole (restarting from its start is the B7 rule — no
    partial-op re-entry). One deterministic comment records the resume point. The last block's
    terminator (final M5 + Z-safe) is preserved. Returns `(resume_gcode, resume_preview)`.
    Raises `ValueError` when `op_index` is out of range or the G-code cannot be mapped to the
    replay's op boundaries (fail closed).
    """
    ops = _ops(replay)
    _check_index(op_index, len(ops))

    lines = gcode.splitlines()
    starts = _op_block_starts(gcode)
    if len(starts) != len(ops):
        raise ValueError(
            "cannot map replay ops to G-code blocks: %d `; obj=` boundaries vs %d replay ops"
            % (len(starts), len(ops))
        )
    ends = starts[1:] + [len(lines)]
    preamble = lines[: starts[0]]
    blocks = [lines[s:e] for s, e in zip(starts, ends)]

    skipped = ops[:op_index]
    resumed_ops = ops[op_index:]
    head = ops[op_index]
    header = [
        "; B7 resume: skip %d completed op(s); restart from %s (%s)"
        % (len(skipped), head.obj, head.op)
    ]
    resumed = "\n".join(preamble + header + [ln for b in blocks[op_index:] for ln in b]) + "\n"

    preview = {
        "resumed_from_op_index": op_index,
        "resumed_obj": head.obj,
        "resumed_op": head.op,
        "n_ops_total": len(ops),
        "skipped_ops": [o.obj for o in skipped],
        "resumed_ops": [o.obj for o in resumed_ops],
        "skipped_time_min": round(sum(o.time_min for o in skipped), 6),
        "resumed_time_min": round(sum(o.time_min for o in resumed_ops), 6),
        "total_time_min": round(float(replay.total_time_min), 6),
        "ok": True,
    }
    return resumed, preview


# ---------------------------------------------------------------------------
# 5) the gate: reuse the deterministic simulator on the resume program
# ---------------------------------------------------------------------------
def resume_gate(gcode: str) -> list[str]:
    """Run the deterministic simulator (`simulator.simulate_gcode`) gate on the resume G-code.

    Returns the blockers (the simulator's errors) in stable order — empty = the program may go to
    the approval gate, non-empty = refuse. Warnings are not blockers.
    """
    return list(simulate_gcode(gcode).errors)


# ---------------------------------------------------------------------------
# 6) the recipe proposal to approve (a `resume` proposal, not yet saved)
# ---------------------------------------------------------------------------
def resume_recipe_proposal(base: dict, resume_preview: dict, registration: dict) -> dict:
    """The recipe proposal reflecting the RESUMED job, to approve (B7 "feedback produces a recipe
    proposal to approve").

    Same shape as `l8_b3.recipe_proposal` (material / params_version / z_mm / params) plus
    `type: "resume"`, the `resume` preview and the NEW `registration`. It is proposed, not saved:
    `approved` and `saved` both come back `False` — saving happens only in the approval step.
    Inputs are copied, so the proposal cannot mutate the caller's state.
    """
    if not isinstance(base, dict):
        raise TypeError("base must be a dict (the job state, e.g. `run_b3_fake`'s base)")
    if not isinstance(resume_preview, dict):
        raise TypeError("resume_preview must be a dict (from `resume_gcode`)")
    if registration is not None and not isinstance(registration, dict):
        raise TypeError("registration must be a dict (from `homing_and_reregister`) or None")
    return {
        "type": "resume",
        "material_id": base.get("material_id"),
        "params_version": base.get("params_version"),
        "z_mm": float(base.get("z_mm", FOCAL_Z_MM)),
        "params": dict(base.get("params") or {}),
        "resume": dict(resume_preview),
        "registration": dict(registration or {}),
        "approved": False,
        "saved": False,
    }
