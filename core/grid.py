"""Deterministic material-grid geometry generator (L2, SPEC §4.2 `add_material_grid`).

Pure and deterministic: the same `AddMaterialGrid` op always yields byte-identical numbers,
which is what the spec hash and the compiler rely on for reproducibility (SPEC principle #12,
same spec → same G-code). Stdlib + the sibling schema module only; no model/provider imports.

"Inside the hash, frozen": the returned dict contains only plain numbers (int/float), lists and
strings — no objects — so it is JSON-serializable and stable under canonical hashing.
"""
from __future__ import annotations

import math

from jobspec2 import AddMaterialGrid  # type: AddMaterialGrid (annotation only; we read attributes)

__all__ = ["generate_grid", "axis_positions", "LABEL_HEIGHT_MM", "LABEL_CHARS_W_MM", "LABEL_GAP_MM"]

# Deterministic engraved-label metrics (mm). A label is a rectangle of fixed height; its width
# scales with the number of characters so the placeholder stays proportional to the text.
LABEL_HEIGHT_MM: float = 4.0
LABEL_CHARS_W_MM: float = 2.4
LABEL_GAP_MM: float = 2.0          # deterministic gap between the grid and its labels

_EPS = 1e-9


def _r2(v: float) -> float:
    """Round to 2 decimals half-away-from-zero (matches compiler.py `_r2` convention)."""
    return math.copysign(math.floor(abs(v) * 100 + 0.5), v) / 100.0


def axis_positions(start: float, end: float, step: float) -> list[float]:
    """Deterministic lattice positions `start..end` inclusive, spaced by `step`.

    The count is exact-interval based (no float stepping drift):
        n = floor((end - start) / step) + 1,   positions = start + i * step
    so repeated calls always return the same list for the same inputs.
    """
    if step <= 0:
        raise ValueError("axis step must be > 0")
    n = int(math.floor((end - start) / step + _EPS)) + 1
    if n < 1:
        return []
    return [_r2(start + i * step) for i in range(n)]


def _label_rect(text: str) -> float:
    """Placeholder label width for a string of text: proportional to its length, min one char."""
    k = max(1, len(text))
    return _r2(k * LABEL_CHARS_W_MM)


def generate_grid(op: AddMaterialGrid) -> dict:
    """Deterministic geometry for an `add_material_grid` op.

    Returns (frozen/plain-JSON-able):
      * origin        grid origin (op.x, op.y) in bed mm
      * cell_w/cell_h cell step along x / y (the engraved cell size)
      * cell_size     the representative (minimum) cell side
      * x_positions / y_positions  absolute lattice points (op.x/y + axis positions)
      * cell_centers  [[x, y], ...]  centre of each grid cell
      * n_cells       cell count
      * labels        {columns: [..], rows: [..]}  engraved label positions next to the grid
      * n_labels      total engraved labels

    Label placement is deterministic and "next to the grid": column labels sit BELOW the grid
    (smaller Y), aligned to each column's centre; row labels sit to the LEFT (smaller X),
    aligned to each row's centre. The caller must leave a label margin outside the grid.
    """
    x_axis = next(a for a in op.axes if a.axis == "x")
    y_axis = next(a for a in op.axes if a.axis == "y")

    gx = _r2(op.x)
    gy = _r2(op.y)
    cell_w = _r2(x_axis.step)
    cell_h = _r2(y_axis.step)

    ax = [_r2(gx + p) for p in axis_positions(x_axis.start, x_axis.end, x_axis.step)]
    ay = [_r2(gy + p) for p in axis_positions(y_axis.start, y_axis.end, y_axis.step)]

    cell_centers = [[_r2(x + cell_w / 2.0), _r2(y + cell_h / 2.0)] for y in ay for x in ax]

    # ---- engraved labels next to the grid ----
    # column labels: below the grid, centred on each column's x
    columns = []
    for i, x in enumerate(ax):
        text = op.col_labels[i] if i < len(op.col_labels) else "%d" % (i + 1)
        cx = _r2(x + cell_w / 2.0)
        cy = _r2(gy - (LABEL_GAP_MM + LABEL_HEIGHT_MM / 2.0))
        columns.append({
            "text": text, "row": None, "col": i,
            "x": cx, "y": cy,
            "width": _label_rect(text), "height": LABEL_HEIGHT_MM,
        })
    # row labels: to the left of the grid, centred on each row's y
    rows = []
    for i, y in enumerate(ay):
        text = op.row_labels[i] if i < len(op.row_labels) else "%d" % (i + 1)
        cy = _r2(y + cell_h / 2.0)
        cx = _r2(gx - (LABEL_GAP_MM + _label_rect(text) / 2.0))
        rows.append({
            "text": text, "row": i, "col": None,
            "x": cx, "y": cy,
            "width": _label_rect(text), "height": LABEL_HEIGHT_MM,
        })

    return {
        "id": op.id,
        "origin": [gx, gy],
        "cell_w": cell_w,
        "cell_h": cell_h,
        "cell_size": _r2(min(cell_w, cell_h)),
        "x_positions": ax,
        "y_positions": ay,
        "cell_centers": cell_centers,
        "n_cells": len(ax) * len(ay),
        "labels": {"columns": columns, "rows": rows},
        "n_labels": len(columns) + len(rows),
    }
