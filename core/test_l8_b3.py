"""L8 · B3 vertical — integration acceptance tests (offline, fake machine).

Happy path: run the full B3 path, assert all eight SPEC §10 #1 outputs are present, consistent and
that the result is deterministic across two runs. Failure path: a forbidden material is refused
*before* any machine interaction (no server, no G-code, no session).
"""
from __future__ import annotations

import pytest

from jobspec2 import JobSpec2
from l8_b3 import (
    choose_cell,
    build_spec,
    gate_blockers2,
    run_b3_fake,
    safe_origin,
    recipe_proposal,
)

CONTOUR = [[20, 25], [180, 20], [185, 170], [15, 165]]


def _iv(**over):
    iv = {
        "goal": "engrave a labeled material grid on plywood",
        "material": {"id": "plywood_3", "category": "safe", "thickness_mm": 3.0},
        "contour_mm": CONTOUR,
        "grid": {
            "axes": [
                {"axis": "x", "start": 0.0, "end": 120.0, "step": 30.0},
                {"axis": "y", "start": 0.0, "end": 60.0, "step": 20.0},
            ],
        },
        "params": {"power_pct": 30, "speed_mm_min": 3000, "passes": 1},
        "cell": {"x": 95, "y": 62},
        "approved": True,
    }
    iv.update(over)
    return iv


def _det(result):
    """The subset of the result whose values must be byte-identical across deterministic runs."""
    return (
        result["grid"],
        result["gcode"],
        result["gate"]["spec_hash2"],
        result["recipe"],
    )


# ---------------------------------------------------------------------------
# units: origin, gate, spec, cell, recipe
# ---------------------------------------------------------------------------
def test_safe_origin_stays_in_bounds_and_label_headroom():
    ox, oy = safe_origin(CONTOUR, 120.0, 60.0)
    assert ox >= 30.0 and oy >= 10.0          # room for the left/bottom engraved labels
    assert 0 <= ox <= 185 and 0 <= oy <= 170  # inside the contour bbox


def test_build_spec_is_valid_030_grid_and_set_pass():
    spec = build_spec(_iv())
    assert isinstance(spec, JobSpec2)
    assert spec.schema_version == "0.3.0"
    ops = [o.op for o in spec.ops]
    assert "add_material_grid" in ops and "set_pass" in ops
    # the grid's origin landed where safe_origin put it
    grid_op = next(o for o in spec.ops if o.op == "add_material_grid")
    ox, oy = safe_origin(CONTOUR, 120.0, 60.0)
    assert (grid_op.x, grid_op.y) == (ox, oy)


def test_gate_clear_for_safe_material():
    spec = build_spec(_iv())
    assert gate_blockers2(_iv(), spec) == []


def test_gate_blocks_forbidden_material():
    spec = build_spec(_iv(material={"id": "pvc_10", "category": "forbidden"}))
    assert any("forbidden" in b for b in gate_blockers2(_iv(material={"id": "pvc_10", "category": "forbidden"}), spec))


def test_gate_blocks_power_over_cap():
    iv = _iv(material={"id": "acrylic_dark_3", "category": "risky"}, params={"power_pct": 55})
    spec = build_spec(iv)
    assert any("cap" in b for b in gate_blockers2(iv, spec))


def test_choose_cell_nearest_and_labels():
    iv = _iv()
    spec = build_spec(iv)
    from grid import generate_grid
    grid = generate_grid(next(o for o in spec.ops if o.op == "add_material_grid"))
    base = {"grid": grid, "params": {"power_pct": 30, "speed_mm_min": 3000, "passes": 1}}
    cell = choose_cell(base, 95, 62)
    assert cell["row"] is not None and cell["col"] is not None
    assert cell["row_label"] is not None and cell["col_label"] is not None
    assert cell["cell_params"]["power_pct"] == 30


# ---------------------------------------------------------------------------
# happy path: all eight outputs present + correct, and deterministic
# ---------------------------------------------------------------------------
def test_run_b3_fake_happy_path_outputs():
    r = run_b3_fake(_iv())
    assert r["ok"] is True

    # (1) interview echoed
    assert r["interview"]["material"]["id"] == "plywood_3"

    # (2) grid with engraved labels
    g = r["grid"]
    assert g["n_cells"] == 5 * 4
    assert g["n_labels"] == 5 + 4
    assert len(g["labels"]["columns"]) == 5 and len(g["labels"]["rows"]) == 4

    # (3) replay preview with times
    p = r["preview"]
    assert p["n_ops"] > 0
    assert p["total_time_min"] > 0
    assert p["ok"] and p["errors"] == []

    # (5) gcode
    assert "M3" in r["gcode"] and r["gcode"].strip()

    # (6) active job
    assert r["active_job"] is True

    # (4) gate: unblocked + accepted (the Yes-tap happened)
    assert r["gate"]["blocked"] is False and r["gate"]["blockers"] == []
    assert r["gate"]["confirmed"] is True
    assert len(r["gate"]["spec_hash2"]) == 64

    # (7) simulated session: accepted, alive, watchdog NOT stopped, prepare/start reached the machine
    s = r["session"]
    assert s["accepted"] is True and s["alive"] is True and not s["lost"]
    assert s["watchdog_stopped"] is False
    assert "Prepare successfully" in s["prepare"]
    assert '"code": 0' in s["start"] and '"code": 0' in s["stop"]
    assert "POST /api/v1/prepare_print" in s["server_calls"]
    assert "session_event" not in s["events"] and any(e == "accepted" for e in s["events"])

    # (8) cell by typing coords + recipe saved after approval
    c = r["cell"]
    assert c["row"] is not None and c["col"] is not None
    assert c["row_label"] is not None and c["col_label"] is not None
    assert r["recipe"]["material_id"] == "plywood_3"
    assert r["recipe"]["params"]["power_pct"] == 30
    assert r["recipe_saved"] is True
    assert r["refusal"] is None


def test_run_b3_fake_is_deterministic_across_runs():
    r1 = run_b3_fake(_iv())
    r2 = run_b3_fake(_iv())
    assert _det(r1) == _det(r2)


def test_cell_not_saved_when_not_approved():
    r = run_b3_fake(_iv(approved=False))
    assert r["cell"] is not None                 # the cell can still be chosen
    assert r["recipe"] is None and r["recipe_saved"] is False


# ---------------------------------------------------------------------------
# failure path: refused before any machine interaction
# ---------------------------------------------------------------------------
def test_run_b3_fake_refuses_forbidden_before_machine():
    iv = _iv(
        material={"id": "pvc_10", "category": "forbidden", "thickness_mm": 10.0},
        params={"power_pct": 40},
    )
    r = run_b3_fake(iv)
    assert r["ok"] is False
    assert r["gate"]["blocked"] is True
    assert any("forbidden" in b for b in r["gate"]["blockers"])
    assert r["gate"]["confirmed"] is False
    # refused before any machine interaction: no session, no gcode, no recipe
    assert r["session"] is None
    assert r["gcode"] is None and r["active_job"] is None
    assert r["cell"] is None and r["recipe"] is None and r["recipe_saved"] is False
    assert r["refusal"] is not None and "refused before machine interaction" in r["refusal"]


def test_gate_refuse_is_pure_does_not_run_machine():
    # a purely deterministic refusal: no socket opened (the forbidden path must not start a server).
    iv = _iv(material={"id": "pvc_10", "category": "forbidden"})
    r = run_b3_fake(iv)
    assert r["session"] is None
    assert "server_calls" not in (r or {})
