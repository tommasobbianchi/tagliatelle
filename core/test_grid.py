"""Tests for the deterministic material-grid geometry generator (core/grid.py).

Pins the contract the compiler and the shared hash rely on: the same `add_material_grid` op
always yields byte-identical numbers, and the engraved row/col labels sit adjacent to the grid.
"""
import json

import pytest

from jobspec2 import AddMaterialGrid, MaterialGridAxis
from grid import generate_grid, axis_positions, LABEL_HEIGHT_MM


def _op(**kw):
    base = dict(
        id="g1",
        axes=[dict(axis="x", start=10, end=40, step=10),
              dict(axis="y", start=10, end=20, step=10)],
        row_labels=["A", "B"], col_labels=["1", "2", "3", "4"],
        x=30, y=40,
    )
    base.update(kw)
    return AddMaterialGrid.model_validate(base)


def test_axis_positions_exact_and_deterministic():
    # 10..40 step 10 -> 10,20,30,40 (4 points). Exact-interval count, no float drift.
    assert axis_positions(10, 40, 10) == [10.0, 20.0, 30.0, 40.0]
    assert axis_positions(0, 0, 5) == [0.0]
    assert axis_positions(0, 9, 4) == [0.0, 4.0, 8.0]
    with pytest.raises(ValueError):
        axis_positions(0, 10, 0)


def test_generate_grid_deterministic():
    a = generate_grid(_op())
    b = generate_grid(_op())
    # byte-identical, JSON-serializable (frozen numbers inside the hash)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    v = _op()
    assert generate_grid(v) == a


def test_cell_count_and_centers():
    g = generate_grid(_op())
    # x: 4 cols (10,20,30,40), y: 2 rows (10,20) -> 8 cells
    assert g["n_cells"] == 8
    assert len(g["cell_centers"]) == 8
    assert g["n_labels"] == len(g["labels"]["columns"]) + len(g["labels"]["rows"])
    # cell size is the (minimum) step
    assert g["cell_w"] == 10.0 and g["cell_h"] == 10.0 and g["cell_size"] == 10.0
    # each centre is a lattice point + half-step; 30+10+5=45 (x=30, axis 10), 40+10+5=55 (y=40, axis 10)
    assert [45.0, 55.0] in g["cell_centers"]


def test_labels_adjacent_to_grid():
    g = generate_grid(_op())
    gx, gy = g["origin"]
    min_x = g["x_positions"][0]
    min_y = g["y_positions"][0]

    # row labels sit to the LEFT of the grid (smaller X than the first column)
    for lab in g["labels"]["rows"]:
        assert lab["x"] < min_x
        assert lab["row"] is not None

    # column labels sit BELOW the grid (smaller Y than the first row)
    for lab in g["labels"]["columns"]:
        assert lab["y"] < min_y
        assert lab["col"] is not None

    # label placeholders carry a positive, deterministic size
    assert all(lab["width"] > 0 and lab["height"] == LABEL_HEIGHT_MM
               for lab in g["labels"]["rows"] + g["labels"]["columns"])
    assert gx > 0 and gy > 0


def test_labels_use_provided_text():
    g = generate_grid(_op())
    assert [lab["text"] for lab in g["labels"]["rows"]] == ["A", "B"]
    assert [lab["text"] for lab in g["labels"]["columns"]] == ["1", "2", "3", "4"]


def test_missing_labels_fall_back_to_numbers():
    g = generate_grid(_op(row_labels=[], col_labels=[]))
    assert [lab["text"] for lab in g["labels"]["rows"]] == ["1", "2"]
    assert [lab["text"] for lab in g["labels"]["columns"]] == ["1", "2", "3", "4"]


def test_different_steps_cell_size_is_min():
    op = _op(axes=[dict(axis="x", start=0, end=20, step=5),
                   dict(axis="y", start=0, end=20, step=2)])
    g = generate_grid(op)
    assert g["cell_w"] == 5.0 and g["cell_h"] == 2.0
    assert g["cell_size"] == 2.0
    assert g["n_cells"] == 55  # 0,5,10,15,20 (5 cols) x 0,2,...,20 (11 rows)
