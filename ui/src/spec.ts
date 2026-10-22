/**
 * Minimal typed mirror of Job Spec 0.3.0 (core/jobspec2.py): the subset the UI
 * manipulates. The Python schema stays the single source of truth; this file
 * mirrors it field-for-field where they overlap.
 *
 * Mirror of: Material, Workpiece, Layer, ExclusionMask, ImportedBlock,
 * FrozenSketch (0.3.0), and the op union (AddRect, AddText, AddMaterialGrid,
 * target ops) from core/jobspec.py + core/jobspec2.py.
 */

export const SCHEMA_VERSION = "0.3.0" as const;
export const BED_MM = 250; // A250 usable area (core/jobspec.py)

// ---- material / workpiece ---------------------------------------------------

export type MaterialCategory = "safe" | "risky" | "forbidden";

export interface Material {
  id: string;
  category: MaterialCategory;
}

export type Pt = [number, number];

export interface WorkpieceConstraint {
  kind: string; // centre | margin | tangent | ...
  value: number | null;
}

export interface Workpiece {
  contour_mm: Pt[]; // min 3 points, frozen reality
  registration_rms_mm: number;
  registration_max_mm: number;
  constraints: WorkpieceConstraint[];
  modified: boolean; // true once the user corrected the detected contour
}

// ---- 0.3.0 fields ------------------------------------------------------------

export interface FrozenSketch {
  profiles: unknown[]; // resolved curves/polygons (numbers, inside the hash)
  recipe: Record<string, unknown>; // kernel feature/variable list
}

export interface Layer {
  op: string; // engrave | fill | cut
  color: string;
  settings: Record<string, unknown>;
}

export interface ExclusionMask {
  polygons: Pt[][];
  source: "user" | "llm_proposed";
}

export interface ImportedBlock {
  original_hash: string;
  x: number;
  y: number;
  rotation_deg: number;
  scale: number;
  nodes_unlocked: boolean;
}

// ---- ops ---------------------------------------------------------------------

export interface Resolved {
  x: number;
  y: number;
  w: number | null;
  h: number | null;
}

export interface AddRectOp {
  op: "add_rect";
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface AddTextOp {
  op: "add_text";
  id: string;
  text: string;
  font: string;
  font_version: string;
  height_mm: number;
  x: number;
  y: number;
}

export interface MaterialGridAxis {
  axis: "x" | "y";
  start: number;
  end: number;
  step: number;
  label: string;
}

/** B3 deterministic grid primitive: geometry generated from (start, end, step);
 * rows/cols engraved next to the grid. */
export interface AddMaterialGridOp {
  op: "add_material_grid";
  id: string;
  axes: [MaterialGridAxis, MaterialGridAxis]; // one x, one y
  row_labels: string[];
  col_labels: string[];
  label_font: string;
  label_font_version: string;
  x: number;
  y: number;
}

export type TargetOpKind =
  | "center_on_workpiece"
  | "fit_to_workpiece"
  | "set_pass"
  | "set_tool"
  | "set_depth";

export interface TargetOp {
  op: TargetOpKind;
  target: string;
  resolved: Resolved | null;
}

export type ShapeOp = AddRectOp | AddTextOp | AddMaterialGridOp;
export type Op = ShapeOp | TargetOp;

export function isShapeOp(op: Op): op is ShapeOp {
  return "id" in op;
}

// ---- the document --------------------------------------------------------------

export interface JobSpec {
  schema_version: "0.3.0";
  module: "laser_405" | "laser_1064" | "cnc";
  job_type: "work" | "calibration";
  material: Material;
  params_version: string;
  workpiece: Workpiece;
  ops: Op[];
  locked: string[];
  sketch: FrozenSketch;
  layers: Layer[];
  exclusion_mask: ExclusionMask;
  imported_blocks: ImportedBlock[];
  variants: string[];
}

// ---- skeleton document (B3 vertical, first delivery) ---------------------------

export const B3_MATERIAL_GRID: AddMaterialGridOp = {
  op: "add_material_grid",
  id: "grid_power_speed",
  axes: [
    { axis: "x", start: 0, end: 3, step: 1, label: "speed" },
    { axis: "y", start: 0, end: 3, step: 1, label: "power" },
  ],
  row_labels: ["20", "40", "60", "80"], // power % per row
  col_labels: ["500", "800", "1200", "1600"], // speed mm/s per column
  label_font: "dejavu",
  label_font_version: "2.37",
  x: 30,
  y: 30,
};

/** The one shared workbench document for the skeleton. Every door opens this
 * same spec; doors only preconfigure panels/tools (see doors/config.ts). */
export function makeSampleSpec(): JobSpec {
  return {
    schema_version: SCHEMA_VERSION,
    module: "laser_405",
    job_type: "calibration",
    material: { id: "basswood-3mm", category: "safe" },
    params_version: "snapmaker-a250-laser-405@2026.10",
    workpiece: {
      contour_mm: [
        [10, 10],
        [240, 10],
        [240, 160],
        [10, 160],
      ],
      registration_rms_mm: 0.35,
      registration_max_mm: 0.6,
      constraints: [{ kind: "centre", value: null }],
      modified: false,
    },
    ops: [
      { op: "add_rect", id: "test_zone", x: 15, y: 15, w: 210, h: 130 },
      {
        op: "add_text",
        id: "title",
        text: "B3 potenza x velocita' griglia",
        font: "dejavu",
        font_version: "2.37",
        height_mm: 5,
        x: 18,
        y: 8,
      },
      B3_MATERIAL_GRID,
      { op: "center_on_workpiece", target: "grid_power_speed", resolved: null },
    ],
    locked: [],
    sketch: { profiles: [], recipe: {} },
    layers: [{ op: "engrave", color: "#000000", settings: { passes: 1 } }],
    exclusion_mask: { polygons: [], source: "user" },
    imported_blocks: [],
    variants: [],
  };
}
