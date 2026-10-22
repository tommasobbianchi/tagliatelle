import type { JobSpec } from "../spec";

/**
 * The four doors (UX decision §12/§15/§20): Importa, Descrivi, Rilancia,
 * Prova materiale. A single workbench: every door leads to the same canvas
 * and the same document, preconfiguring panels/tools (here: preselection and
 * the intro message).
 *
 * UI strings are Italian (end-user of an Italian app); code/comments English.
 */

export type Mode = "import" | "describe" | "relaunch" | "material-test";

export interface DoorConfig {
  mode: Mode;
  title: string;
  blurb: string;
  /** Preselection on the shared document: which object the properties panel opens on. */
  preselectId: (spec: JobSpec) => string | null;
  /** First assistant message in the chat. */
  intro: string;
}

export interface DoorProps {
  config: DoorConfig;
  onEnter: (mode: Mode) => void;
}

function idIfPresent(spec: JobSpec, id: string): string | null {
  return spec.ops.some((op) => "id" in op && op.id === id) ? id : null;
}

export const DOORS: DoorConfig[] = [
  {
    mode: "import",
    title: "Importa",
    blurb: "Porta dentro file SVG/DXF, immagini, STEP/STL come blocco trasformabile.",
    preselectId: (spec) => idIfPresent(spec, "test_zone"),
    intro:
      "Saluti. Portate il file che volete lavorare — prima SVG/DXF, poi immagini, poi STEP/STL. Propongo le operazioni da colore e layer; voi le confermate sull'anteprima.",
  },
  {
    mode: "describe",
    title: "Descrivi",
    blurb: "Idea: l'LLM la costruisce con le primitive dello sketch, voi correggete.",
    preselectId: (spec) => idIfPresent(spec, "title"),
    intro:
      "Descrivetemi in parole il risultato che volete. Lo costruisco con le stesse primitive dello sketch che usate voi, e lo rifiniamo col trascinamento (solver al rilascio).",
  },
  {
    mode: "relaunch",
    title: "Rilancia",
    blurb: "Lavoro vecchio: nuovo spec derivato dal vecchio, nuovo hash, nuovo gate.",
    preselectId: (spec) => idIfPresent(spec, "test_zone"),
    intro:
      "Dimmi quale lavoro vuoi rilanciare. Derivo un nuovo spec dal vecchio — nuovo hash, nuovo gate — e lo riposiziono sul nuovo contorno.",
  },
  {
    mode: "material-test",
    title: "Prova materiale",
    blurb: "Prova guidata: griglia deterministica potenza x velocita' in area libera.",
    preselectId: (spec) => idIfPresent(spec, "grid_power_speed"),
    intro:
      "Che materiale, che spessore, e cosa vuoi misurare? Compilo una griglia deterministica potenza x velocita' in area libera del pezzo, con righe e colonne incise accanto.",
  },
];

export function findDoor(mode: Mode): DoorConfig {
  const door = DOORS.find((d) => d.mode === mode);
  if (!door) throw new Error(`unknown door mode: ${mode}`);
  return door;
}
