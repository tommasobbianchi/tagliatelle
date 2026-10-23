/**
 * A1 · UI mirror of the deterministic import core (core/import_svg.py).
 *
 * The core's `svg_to_jobspec()` produces a 0.3.0 JobSpec2 whose
 * `sketch.profiles` carries one dict per proposed operation, in §4.2 order
 * (engrave/fill → inner cuts → outer contour LAST), and whose `layers` group
 * the operations by operation with their settings. This module mirrors only
 * that A1 subset, so the preview overlay (workbench/A1Overlay.tsx) can render
 * the proposal deterministically before any Python → UI data channel exists.
 *
 * The Python module is the single source of truth and is NOT modified here;
 * `makeSampleA1()` below is a deterministic synthetic document shaped exactly
 * like the core output (3 colours: black engrave, grey fill, red cuts —
 * inner cut + outer contour).
 */

export type A1Op = "engrave" | "fill" | "cut";

/** One colour layer of the proposal, with the visible laser settings. */
export interface A1Layer {
  op: A1Op;
  color: string; // normalised "#rrggbb"
  settings: {
    power_pct: number;
    speed_mm_min: number;
    passes: number;
    kerf_mm?: number; // cut layers only (recipe value)
  };
}

/** One proposed operation (a colour layer), in mm, already work-ordered. */
export interface A1Profile {
  op: A1Op;
  color: string; // "#rrggbb"
  id: string; // matches the add_rect op id (e.g. "s0")
  auto_closed: number[]; // path indices auto-closed (minimal gap)
  highlight_open: number[]; // path indices left open + highlighted (large gap)
  is_outer_contour: boolean; // true on exactly one profile (the last cut, §4.2)
  bbox_mm: [number, number, number, number]; // x, y, w, h
  /** All points of the profile in mm (per path, in order) — the core shape. */
  pts_mm: [number, number][];
  /**
   * Optional mirror extension (UI only): per-path point lists in mm, used to
   * style individual paths (open vs auto-closed). When absent, the overlay
   * draws the whole profile as one path and still renders the markers.
   */
  path_pts_mm?: [number, number][][];
}

/** The A1 proposal document: ordered profiles + layers + deduced extent. */
export interface A1Document {
  /** Ordered work: index === execution order (outer contour last, §4.2). */
  profiles: A1Profile[];
  layers: A1Layer[];
  /** Deduced workpiece extent in mm (from the SVG root dimensions). */
  width_mm: number;
  height_mm: number;
}

/**
 * Deterministic synthetic A1 document (no randomness, stable order):
 *  1. s0 engrave (black) — text-like open stroke, large gap → highlight_open
 *  2. s1 fill    (grey)   — panel loop whose minimal gap was auto-closed
 *  3. s2 cut     (red)    — inner 12×12 hole
 *  4. s3 cut     (red)    — outer contour 92×52, LAST (is_outer_contour)
 * Workpiece 100×60 mm.
 */
export function makeSampleA1(): A1Document {
  return {
    width_mm: 100,
    height_mm: 60,
    profiles: [
      {
        op: "engrave",
        color: "#000000",
        id: "s0",
        auto_closed: [],
        highlight_open: [0], // stroke ends ~19.8 mm from the start → kept open
        is_outer_contour: false,
        bbox_mm: [10, 8, 28, 14],
        pts_mm: [
          [10, 8],
          [38, 8],
          [24, 8],
          [24, 22],
        ],
        path_pts_mm: [
          [
            [10, 8],
            [38, 8],
            [24, 8],
            [24, 22],
          ],
        ],
      },
      {
        op: "fill",
        color: "#808080",
        id: "s1",
        auto_closed: [0], // open loop, 2 mm gap → auto-closed by the core
        highlight_open: [],
        is_outer_contour: false,
        bbox_mm: [50, 10, 40, 30],
        pts_mm: [
          [50, 10],
          [90, 10],
          [90, 40],
          [50, 40],
          [50, 12],
        ],
        path_pts_mm: [
          [
            [50, 10],
            [90, 10],
            [90, 40],
            [50, 40],
            [50, 12],
          ],
        ],
      },
      {
        op: "cut",
        color: "#ff0000",
        id: "s2",
        auto_closed: [],
        highlight_open: [],
        is_outer_contour: false,
        bbox_mm: [20, 30, 12, 12],
        pts_mm: [
          [20, 30],
          [32, 30],
          [32, 42],
          [20, 42],
        ],
        path_pts_mm: [
          [
            [20, 30],
            [32, 30],
            [32, 42],
            [20, 42],
          ],
        ],
      },
      {
        op: "cut",
        color: "#ff0000",
        id: "s3",
        auto_closed: [],
        highlight_open: [],
        is_outer_contour: true, // outer contour: ordered LAST (largest closed cut)
        bbox_mm: [4, 4, 92, 52],
        pts_mm: [
          [4, 4],
          [96, 4],
          [96, 56],
          [4, 56],
        ],
        path_pts_mm: [
          [
            [4, 4],
            [96, 4],
            [96, 56],
            [4, 56],
          ],
        ],
      },
    ],
    layers: [
      {
        op: "engrave",
        color: "#000000",
        settings: { power_pct: 30, speed_mm_min: 3000, passes: 1 },
      },
      {
        op: "fill",
        color: "#808080",
        settings: { power_pct: 40, speed_mm_min: 2000, passes: 1 },
      },
      {
        op: "cut",
        color: "#ff0000",
        settings: { power_pct: 50, speed_mm_min: 1200, passes: 1, kerf_mm: 0.2 },
      },
    ],
  };
}
