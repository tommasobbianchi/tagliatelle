"""Job Spec schema v0: the only contract between gate, compiler, simulator, RPi agent and frontend.
A schema change is a deliberate event: bump SCHEMA_VERSION and add a migration, never edit in place.
No model/provider imports here (project rule: nothing after the gate may touch the AI provider)."""
import hashlib, json
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.2.0"
BED_MM = 250.0   # A250 usable area; the module descriptor will narrow this per plugin
FOCAL_Z_MM = 220.0  # A250 max Z (measured in task zero); depth is relative to focus


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Pt = tuple[float, float]


class Material(_M):                 # declared by the human, never inferred by the camera
    id: str
    category: Literal["safe", "risky", "forbidden"]


class Workpiece(_M):                # frozen reality: measured once, the compiler never re-reads the camera
    contour_mm: list[Pt] = Field(min_length=3)
    registration_rms_mm: float
    registration_max_mm: float


class Resolved(_M):                 # filled by the resolver before the gate
    x: float
    y: float
    w: float | None = None
    h: float | None = None


class AddText(_M):
    op: Literal["add_text"] = "add_text"
    id: str
    text: str = Field(min_length=1, max_length=200)
    font: str
    font_version: str
    height_mm: float = Field(gt=0, le=BED_MM)
    x: float = Field(ge=0, le=BED_MM)
    y: float = Field(ge=0, le=BED_MM)


class AddRect(_M):
    op: Literal["add_rect"] = "add_rect"
    id: str
    x: float = Field(ge=0, le=BED_MM)
    y: float = Field(ge=0, le=BED_MM)
    w: float = Field(gt=0, le=BED_MM)
    h: float = Field(gt=0, le=BED_MM)


class CenterOnWorkpiece(_M):
    op: Literal["center_on_workpiece"] = "center_on_workpiece"
    target: str
    resolved: Resolved | None = None


class FitToWorkpiece(_M):
    op: Literal["fit_to_workpiece"] = "fit_to_workpiece"
    target: str
    margin_mm: float = Field(ge=0, le=BED_MM)
    resolved: Resolved | None = None


class SetPass(_M):                  # laser only; the safety validator re-checks limits against the material YAML
    op: Literal["set_pass"] = "set_pass"
    target: str
    power_pct: float = Field(ge=0, le=100)
    speed_mm_min: float = Field(gt=0, le=6000)
    passes: int = Field(ge=1, le=50)


class SetTool(_M):                  # E1.0 vector: which tool-head/module applies; the module descriptor validates
    op: Literal["set_tool"] = "set_tool"
    target: str
    tool: str                        # e.g. "laser_405_10w"; validated against module capabilities
    focus_z_mm: float = Field(ge=0, le=FOCAL_Z_MM)   # focal height, default material thickness handling in compiler


class SetDepth(_M):                 # E1.0 vector: engraving/cut depth (Z offset from focus), multi-pass depth
    op: Literal["set_depth"] = "set_depth"
    target: str
    depth_mm: float = Field(ge=-50.0, le=50.0)      # negative = engrave below focus
    multi_pass_depth_mm: float = Field(ge=0, le=50.0)  # 0 = single pass


Op = Annotated[Union[AddText, AddRect, CenterOnWorkpiece, FitToWorkpiece, SetPass, SetTool, SetDepth],
                Field(discriminator="op")]


class JobSpec(_M):
    schema_version: Literal["0.2.0"] = SCHEMA_VERSION
    module: Literal["laser_405", "laser_1064", "cnc"]
    job_type: Literal["work", "calibration"]
    material: Material
    params_version: str                       # version of the material/params YAML used
    workpiece: Workpiece
    ops: list[Op] = Field(min_length=1)
    locked: list[str] = []                    # dotted paths the human touched; the AI may propose, never overwrite

    @model_validator(mode="after")
    def _check(self):
        if self.module != "laser_405":
            raise ValueError("v0 implements laser_405 only (laser_1064 and cnc arrive as plugins)")
        ids = [o.id for o in self.ops if o.op in ("add_text", "add_rect")]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate object id")
        for o in self.ops:
            if o.op in ("center_on_workpiece", "fit_to_workpiece", "set_pass", "set_tool", "set_depth") \
                    and o.target not in ids:
                raise ValueError("%s targets unknown object %r" % (o.op, o.target))
        return self


def canonical(spec: JobSpec) -> bytes:
    return json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def spec_hash(spec: JobSpec) -> str:
    return hashlib.sha256(canonical(spec)).hexdigest()


def gate_blockers(spec: JobSpec) -> list[str]:
    """Why this spec cannot go to the approval gate yet (empty = ready)."""
    out = [o.op + ":" + o.target + " unresolved" for o in spec.ops
           if o.op in ("center_on_workpiece", "fit_to_workpiece") and o.resolved is None]
    if spec.material.category == "forbidden":
        out.append("forbidden material " + spec.material.id)
    if not any(o.op == "set_pass" for o in spec.ops):
        out.append("no set_pass: laser power/speed undefined")
    return out
