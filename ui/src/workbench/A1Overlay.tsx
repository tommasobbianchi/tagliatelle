import { useState } from "react";
import type { A1Document, A1Profile } from "../a1";

export interface A1OverlayProps {
  /** The A1 proposal: profiles in §4.2 order (outer contour last) + layers. */
  doc: A1Document;
}

/** Mean of the points, in mm — badge/marker anchor. Deterministic. */
function centroid(pts: [number, number][]): [number, number] {
  if (pts.length === 0) return [0, 0];
  let sx = 0;
  let sy = 0;
  for (const [x, y] of pts) {
    sx += x;
    sy += y;
  }
  return [sx / pts.length, sy / pts.length];
}

/** Per-path points: prefer the mirror's path_pts_mm (UI extension); when
 * absent (pure core shape) the whole profile is one drawable path. */
function pathPts(p: A1Profile): [number, number][][] {
  if (p.path_pts_mm && p.path_pts_mm.length > 0) return p.path_pts_mm;
  return p.pts_mm.length > 0 ? [p.pts_mm] : [];
}

const toPoints = (pts: [number, number][]) =>
  pts.map(([x, y]) => `${x},${y}`).join(" ");

/**
 * A1 preview overlay (import door, SPEC §10 A1): the deterministic core
 * proposal rendered over the shared canvas — one numbered badge per ordered
 * profile (the work order, outer contour LAST and emphasised), per-path
 * attention markers (highlight_open = dashed + "!", auto_closed = closed
 * marker), a layer legend (colour chip + op + power/passes) and the local
 * confirmation step (proposal + deduced dimensions). Confirmation is local
 * component state only: no backend, no network.
 */
export default function A1Overlay({ doc }: A1OverlayProps) {
  const [proposalConfirmed, setProposalConfirmed] = useState(false);
  const [dimsConfirmed, setDimsConfirmed] = useState(false);

  return (
    <div className="a1-overlay" data-testid="a1-overlay">
      <svg
        className="a1-svg"
        data-testid="a1-svg"
        viewBox={`0 0 ${doc.width_mm} ${doc.height_mm}`}
        role="img"
        aria-label={`Anteprima della proposta A1 (${doc.profiles.length} operazioni in ordine)`}
      >
        {doc.profiles.map((p, i) => {
          const badge = p.pts_mm.length > 0 ? centroid(p.pts_mm) : null;
          return (
            <g
              key={p.id}
              className={
                p.is_outer_contour ? "a1-profile a1-profile-outer" : "a1-profile"
              }
              data-testid="a1-profile"
              data-id={p.id}
              data-op={p.op}
              data-outer={p.is_outer_contour ? "true" : "false"}
            >
              {pathPts(p).map((pts, j) => {
                const attention = p.highlight_open.includes(j);
                const closed = p.auto_closed.includes(j);
                const [mx, my] = centroid(pts);
                return (
                  <g key={j} data-path-index={j}>
                    <polyline
                      points={toPoints(pts)}
                      className={attention ? "a1-path a1-path-open" : "a1-path"}
                      data-testid={attention ? "a1-path-open" : undefined}
                      fill="none"
                      stroke={p.color}
                      strokeWidth={p.is_outer_contour ? 1.8 : 0.8}
                      strokeDasharray={attention ? "2 1.2" : undefined}
                    />
                    {closed && (
                      <g
                        className="a1-closed-marker"
                        data-testid="a1-closed-marker"
                      >
                        <title>percorso chiuso automaticamente (gap minimo)</title>
                        <circle cx={mx} cy={my} r={2.0} />
                        <circle cx={mx} cy={my} r={0.7} />
                      </g>
                    )}
                    {attention && pts.length > 0 && (
                      <g
                        className="a1-open-marker"
                        data-testid="a1-open-marker"
                      >
                        <title>percorso aperto: gap non minimo, in evidenza</title>
                        <circle cx={pts[0][0]} cy={pts[0][1]} r={2.4} />
                        <text
                          x={pts[0][0]}
                          y={pts[0][1]}
                          dy="1.0"
                          textAnchor="middle"
                          fontSize="3.2"
                        >
                          !
                        </text>
                      </g>
                    )}
                  </g>
                );
              })}
              {badge && (
                <g
                  className="a1-badge"
                  data-testid="a1-badge"
                  data-number={String(i + 1)}
                >
                  <title>
                    operazione {i + 1}: {p.op} {p.color}
                    {p.is_outer_contour ? " (contorno esterno, per ultima)" : ""}
                  </title>
                  <circle cx={badge[0]} cy={badge[1]} r={3.6} />
                  <text
                    x={badge[0]}
                    y={badge[1]}
                    dy="1.3"
                    textAnchor="middle"
                    fontSize="4.2"
                  >
                    {i + 1}
                  </text>
                </g>
              )}
            </g>
          );
        })}
      </svg>

      <section
        className="a1-legend"
        data-testid="a1-legend"
        aria-label="layer della proposta"
      >
        <h4>Layer</h4>
        <ul>
          {doc.layers.map((l) => (
            <li
              key={l.op}
              className="a1-layer"
              data-testid="a1-layer"
              data-op={l.op}
            >
              <span
                className="a1-chip"
                style={{ backgroundColor: l.color }}
                aria-hidden="true"
              />
              <span className="a1-layer-op">{l.op}</span>
              <span className="a1-layer-settings">
                {l.settings.power_pct} ·{" "}
                {l.settings.passes}
                {l.settings.passes === 1 ? " passata" : " passate"}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section
        className={
          proposalConfirmed || dimsConfirmed
            ? "a1-confirm a1-confirmed"
            : "a1-confirm"
        }
        data-testid="a1-confirm"
        aria-label="conferma della proposta"
      >
        <p className="a1-dims" data-testid="a1-dims">
          <strong>
            {doc.width_mm} × {doc.height_mm}
          </strong>{" "}
          mm dedotti dal file
          <span className="a1-state" role="status" data-testid="dims-state">
            {dimsConfirmed ? "· confermate" : "· non confermate"}
          </span>
          <button
            type="button"
            className={dimsConfirmed ? "btn-confirmed" : undefined}
            data-testid="confirm-dims"
            aria-pressed={dimsConfirmed}
            disabled={dimsConfirmed}
            onClick={() => setDimsConfirmed(true)}
          >
            {dimsConfirmed ? "✓ Dimensioni confermate" : "Conferma dimensioni"}
          </button>
        </p>
        <span className="a1-state" role="status" data-testid="proposal-state">
          {proposalConfirmed ? "proposta confermata" : "proposta non confermata"}
        </span>
        <button
          type="button"
          className={proposalConfirmed ? "btn-confirmed" : undefined}
          data-testid="confirm-proposal"
          aria-pressed={proposalConfirmed}
          disabled={proposalConfirmed}
          onClick={() => setProposalConfirmed(true)}
        >
          {proposalConfirmed ? "✓ Proposta confermata" : "Conferma proposta"}
        </button>
      </section>
    </div>
  );
}
