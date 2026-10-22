import { useEffect, useRef } from "react";
import type { AddMaterialGridOp, JobSpec } from "../spec";
import { isShapeOp } from "../spec";
import type { PreviewLevel } from "./Workbench";

/** Internal fixed drawing surface; CSS scales it. Deterministic, no libs. */
const W = 800;
const H = 500;
const PAD = 36;

export interface CanvasProps {
  spec: JobSpec;
  selectedId: string | null;
  preview: PreviewLevel;
}

interface Bounds {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

function contentBounds(spec: JobSpec): Bounds {
  const b: Bounds = {
    x0: Infinity,
    y0: Infinity,
    x1: -Infinity,
    y1: -Infinity,
  };
  const grow = (x: number, y: number) => {
    b.x0 = Math.min(b.x0, x);
    b.y0 = Math.min(b.y0, y);
    b.x1 = Math.max(b.x1, x);
    b.y1 = Math.max(b.y1, y);
  };
  for (const [x, y] of spec.workpiece.contour_mm) grow(x, y);
  for (const op of spec.ops) {
    if (!isShapeOp(op)) continue;
    if (op.op === "add_rect") {
      grow(op.x, op.y);
      grow(op.x + op.w, op.y + op.h);
    } else if (op.op === "add_text") {
      grow(op.x, op.y);
      grow(op.x + op.text.length * op.height_mm * 0.6, op.y + op.height_mm);
    } else if (op.op === "add_material_grid") {
      const ax = op.axes.find((a) => a.axis === "x");
      const ay = op.axes.find((a) => a.axis === "y");
      if (!ax || !ay) continue;
      grow(op.x - 24, op.y); // room for row labels
      grow(op.x + (ax.end - ax.start), op.y + (ay.end - ay.start));
    }
  }
  if (!Number.isFinite(b.x0)) {
    return { x0: 0, y0: 0, x1: 1, y1: 1 };
  }
  return b;
}

function makeTransform(bounds: Bounds) {
  const bw = bounds.x1 - bounds.x0 || 1;
  const bh = bounds.y1 - bounds.y0 || 1;
  const scale = Math.min((W - 2 * PAD) / bw, (H - 2 * PAD) / bh);
  const ox = PAD + (W - 2 * PAD - bw * scale) / 2;
  const oy = PAD + (H - 2 * PAD - bh * scale) / 2;
  return {
    px: (x: number) => ox + (x - bounds.x0) * scale,
    py: (y: number) => oy + (y - bounds.y0) * scale,
    scale,
  };
}

function drawGrid(
  ctx: CanvasRenderingContext2D,
  g: AddMaterialGridOp,
  px: (x: number) => number,
  py: (y: number) => number,
  scale: number,
) {
  const ax = g.axes.find((a) => a.axis === "x");
  const ay = g.axes.find((a) => a.axis === "y");
  if (!ax || !ay) return;
  const cols = Math.max(1, Math.floor((ax.end - ax.start) / ax.step) + 1);
  const rows = Math.max(1, Math.floor((ay.end - ay.start) / ay.step) + 1);
  const x0 = px(g.x);
  const y0 = py(g.y);
  const gw = (ax.end - ax.start) * scale;
  const gh = (ay.end - ay.start) * scale;

  const line = (x1: number, y1: number, x2: number, y2: number) => {
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  };

  ctx.save();
  ctx.strokeStyle = "#0b7285";
  ctx.fillStyle = "#0b7285";
  ctx.lineWidth = 1;
  ctx.font = "11px monospace";

  for (let i = 0; i < cols; i++) {
    const x = x0 + i * ax.step * scale;
    line(x, y0, x, y0 + gh);
    if (g.col_labels[i]) {
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      ctx.fillText(g.col_labels[i], x, y0 - 4);
    }
  }
  for (let j = 0; j < rows; j++) {
    const y = y0 + j * ay.step * scale;
    line(x0, y, x0 + gw, y);
    if (g.row_labels[j]) {
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.fillText(g.row_labels[j], x0 - 5, y);
    }
  }
  ctx.restore();
}

function drawSpec(
  ctx: CanvasRenderingContext2D,
  spec: JobSpec,
  selectedId: string | null,
) {
  const { px, py, scale } = makeTransform(contentBounds(spec));
  ctx.clearRect(0, 0, W, H);

  // workpiece contour (frozen reality)
  ctx.strokeStyle = "#9aa0a6";
  ctx.lineWidth = 1.5;
  ctx.setLineDash([]);
  ctx.beginPath();
  spec.workpiece.contour_mm.forEach(([x, y], i) => {
    if (i === 0) ctx.moveTo(px(x), py(y));
    else ctx.lineTo(px(x), py(y));
  });
  ctx.closePath();
  ctx.stroke();

  for (const op of spec.ops) {
    if (!isShapeOp(op)) continue;
    const selected = op.id === selectedId;
    ctx.strokeStyle = selected ? "#ff7d1a" : "#1f2937";
    ctx.fillStyle = ctx.strokeStyle;
    ctx.lineWidth = selected ? 2.5 : 1.5;

    if (op.op === "add_rect") {
      ctx.strokeRect(px(op.x), py(op.y), op.w * scale, op.h * scale);
    } else if (op.op === "add_text") {
      const size = Math.max(8, op.height_mm * scale);
      ctx.font = `${size}px sans-serif`;
      ctx.textAlign = "left";
      ctx.textBaseline = "alphabetic";
      ctx.fillText(op.text, px(op.x), py(op.y) + size);
    } else if (op.op === "add_material_grid") {
      drawGrid(ctx, op, px, py, scale);
      if (selected) {
        // selected grid: outline its bounding area
        const ax = op.axes.find((a) => a.axis === "x");
        const ay = op.axes.find((a) => a.axis === "y");
        if (ax && ay) {
          ctx.strokeStyle = "#ff7d1a";
          ctx.lineWidth = 2.5;
          ctx.strokeRect(
            px(op.x),
            py(op.y),
            (ax.end - ax.start) * scale,
            (ay.end - ay.start) * scale,
          );
        }
      }
    }
  }
}

export default function Canvas({ spec, selectedId, preview }: CanvasProps) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return; // no canvas 2d in this DOM (e.g. jsdom): skip, tests assert the element
    drawSpec(ctx, spec, selectedId);
  }, [spec, selectedId]);

  return (
    <div className="canvas-wrap" data-testid="canvas-wrap">
      <canvas
        ref={ref}
        width={W}
        height={H}
        data-testid="canvas"
        aria-label="canvas di lavoro"
      />
      <div className="canvas-overlay" data-testid="canvas-overlay">
        {preview === "fast"
          ? "Anteprima veloce — geometrica, istantanea."
          : "Anteprima accurata — replay del G-code compilato in simulazione. " +
            "Segnaposto: si aggancia al replay del core (core/replay.py) via API."}
      </div>
    </div>
  );
}
