import type { JobSpec, ShapeOp } from "../spec";
import { isShapeOp } from "../spec";

export interface PropertiesProps {
  spec: JobSpec;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

const fmt = (v: unknown): string =>
  typeof v === "string" ? v : JSON.stringify(v);

/**
 * Properties panel (left): the objects of the current Job Spec and the fields
 * of the selected one. Pure read of the shared document; edits (later, via
 * the kernel service) mutate the same object.
 */
export default function Properties({
  spec,
  selectedId,
  onSelect,
}: PropertiesProps) {
  const shapeOps: ShapeOp[] = spec.ops.filter(isShapeOp);
  const selected = shapeOps.find((o) => o.id === selectedId) ?? null;

  return (
    <div className="properties" data-testid="properties-panel">
      <h3>Oggetti</h3>
      <ul className="object-list" data-testid="object-list">
        {shapeOps.map((o) => (
          <li key={o.id}>
            <button
              type="button"
              data-testid={`object-${o.id}`}
              className={o.id === selectedId ? "selected" : undefined}
              onClick={() => onSelect(o.id)}
            >
              {o.id} <span className="op-kind">({o.op})</span>
            </button>
          </li>
        ))}
      </ul>

      {selected ? (
        <table className="prop-table" data-testid={`props-${selected.id}`}>
          <caption className="prop-caption">{selected.id}</caption>
          <tbody>
            {Object.entries(selected)
              .filter(([k]) => k !== "op")
              .map(([k, v]) => (
                <tr key={k} data-testid={`prop-${k}`}>
                  <th scope="row">{k}</th>
                  <td>{fmt(v)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      ) : (
        <p className="hint" data-testid="props-empty">
          Seleziona un oggetto per vedere i campi (Job Spec 0.3.0).
        </p>
      )}

      <h3>Material</h3>
      <table className="prop-table" data-testid="props-material">
        <tbody>
          <tr>
            <th scope="row">id</th>
            <td>{spec.material.id}</td>
          </tr>
          <tr>
            <th scope="row">category</th>
            <td>{spec.material.category}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
