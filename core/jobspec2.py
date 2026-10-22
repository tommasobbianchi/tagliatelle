"""Job Spec schema v0.3.0: migration from 0.2.0 and contract validation.

A schema change is a deliberate event: bump SCHEMA_VERSION, add a migration, and never
edit in place. This module holds the 0.2.0 → 0.3.0 migration and the new contract fields.

No model/provider imports here (project rule: nothing after the gate may touch the AI provider).
"""
from __future__ import annotations

import hashlib
import json

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---- old schema import (0.2.0) ----
from jobspec import (
    SCHEMA_VERSION as _OLD_VERSION,
    AddRect,
    AddText,
    BED_MM,
    CenterOnWorkpiece,
    FitToWorkpiece,
    JobSpec as _OldJobSpec,
    Material,
    Op as _OldOp,
    Resolved,
    SetDepth,
    SetPass,
    SetTool,
    Workpiece,
)

SCHEMA_VERSION = "0.3.0"

# ------------------------- new fields (0.3.0) -------------------------


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FrozenSketch(_M):
    """Frozen resolved profiles (numbers, inside the hash) + recipe-as-source
    so the document can be reopened and edited (SPEC §4.1)."""

    profiles: list[dict] = Field(default_factory=list)   # resolved curves/polygons
    recipe: dict = Field(default_factory=dict)            # kernel feature/variable list


class Layer(_M):
    """Operation = layer (SPEC §4.2). Colour + settings live here; the kernel
    stays pure geometry. Work order: engrave/fill -> inner cuts -> outer contour."""

    op: str                                            # engrave | fill | cut
    color: str = "#000000"
    settings: dict = Field(default_factory=dict)       # e.g. set_pass equivalent, kerf, passes


class WorkpieceConstraint(_M):
    kind: str                                          # centre | margin | tangent | ...
    value: float | None = None


class Workpiece2(_M):
    contour_mm: list[tuple[float, float]] = Field(min_length=3)
    registration_rms_mm: float
    registration_max_mm: float
    constraints: list[WorkpieceConstraint] = Field(default_factory=list)
    modified: bool = False                             # True if user corrected the detected contour


class MaterialGridAxis(_M):
    axis: str                                          # "x" | "y"
    start: float
    end: float
    step: float
    label: str = ""


class AddMaterialGrid(_M):
    op: Literal["add_material_grid"] = "add_material_grid"
    id: str
    axes: list[MaterialGridAxis] = Field(min_length=2, max_length=2)
    row_labels: list[str] = Field(default_factory=list)
    col_labels: list[str] = Field(default_factory=list)
    # engrave labels next to the grid
    label_font: str = "dejavu"
    label_font_version: str = "2.37"
    x: float = Field(ge=0, le=BED_MM)
    y: float = Field(ge=0, le=BED_MM)


class ExclusionMask(_M):
    """Already-worked zones (SPEC §4.5), drawn by the user; LLM may propose."""

    polygons: list[list[tuple[float, float]]] = Field(default_factory=list)
    source: str = "user"                               # user | llm_proposed


class ImportedBlock(_M):
    """Transformable imported block (SPEC §4.12): original preserved + hash."""

    original_hash: str
    x: float = 0.0
    y: float = 0.0
    rotation_deg: float = 0.0
    scale: float = 1.0
    nodes_unlocked: bool = False


NewOp = Annotated[Union[AddRect, AddText, CenterOnWorkpiece, FitToWorkpiece, SetPass, SetTool,
                          SetDepth, AddMaterialGrid], Field(discriminator="op")]


class JobSpec2(_M):
    schema_version: Literal["0.3.0"] = SCHEMA_VERSION
    module: Literal["laser_405", "laser_1064", "cnc"]
    job_type: Literal["work", "calibration"]
    material: Material
    params_version: str
    workpiece: Workpiece2
    ops: list[NewOp] = Field(min_length=1)
    locked: list[str] = []
    # new in 0.3.0
    sketch: FrozenSketch = Field(default_factory=FrozenSketch)
    layers: list[Layer] = Field(default_factory=list)
    exclusion_mask: ExclusionMask = Field(default_factory=ExclusionMask)
    imported_blocks: list[ImportedBlock] = Field(default_factory=list)
    variants: list[str] = Field(default_factory=list)   # branch ids; current = the doc itself

    @model_validator(mode="after")
    def _check(self):
        if self.module != "laser_405":
            raise ValueError("v0.3.0 implements laser_405 only (1064/CNC arrive as plugins)")
        ids = [o.id for o in self.ops if o.op in ("add_text", "add_rect", "add_material_grid")]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate object id")
        for o in self.ops:
            if o.op in ("center_on_workpiece", "fit_to_workpiece", "set_pass", "set_tool",
                        "set_depth") and o.target not in ids:
                raise ValueError("%s targets unknown object %r" % (o.op, o.target))
        return self


# ------------------------- migration 0.2.0 -> 0.3.0 -------------------------


def migrate_020_to_030(old_dump: dict) -> dict:
    """Deterministic migration of a 0.2.0 spec dump into a 0.3.0 spec dump.

    Purely additive: every existing field is preserved verbatim; only the new
    fields are filled with defaults. The result is a valid 0.3.0 spec.
    """
    if old_dump.get("schema_version") != _OLD_VERSION:
        raise ValueError("migration expects schema 0.2.0, got %r" % old_dump.get("schema_version"))
    new = dict(old_dump)
    new["schema_version"] = SCHEMA_VERSION
    # workpiece: add constraints + modified default
    wp = dict(new.get("workpiece", {}))
    wp.setdefault("constraints", [])
    wp.setdefault("modified", False)
    new["workpiece"] = wp
    # new defaulted fields
    new.setdefault("sketch", {"profiles": [], "recipe": {}})
    new.setdefault("layers", [])
    new.setdefault("exclusion_mask", {"polygons": [], "source": "user"})
    new.setdefault("imported_blocks", [])
    new.setdefault("variants", [])
    return new


def canonical2(spec: JobSpec2) -> bytes:
    return json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode()


def spec_hash2(spec: JobSpec2) -> str:
    return hashlib.sha256(canonical2(spec)).hexdigest()
