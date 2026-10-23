import type { ComponentType } from "react";
import { useState } from "react";
import { DOORS, type DoorProps, type Mode } from "./doors/config";
import ImportDoor from "./doors/ImportDoor";
import DescribeDoor from "./doors/DescribeDoor";
import RelaunchDoor from "./doors/RelaunchDoor";
import MaterialTestDoor from "./doors/MaterialTestDoor";
import Workbench from "./workbench/Workbench";
import { makeSampleSpec } from "./spec";
import { makeSampleA1 } from "./a1";

const DOOR_COMPONENTS: Record<Mode, ComponentType<DoorProps>> = {
  import: ImportDoor,
  describe: DescribeDoor,
  relaunch: RelaunchDoor,
  "material-test": MaterialTestDoor,
};

export default function App() {
  const [mode, setMode] = useState<Mode | null>(null);
  // the ONE shared document: every door opens the same job spec
  const [spec] = useState(() => makeSampleSpec());

  if (mode === null) {
    return (
      <div className="start">
        <header>
          <h1>TaglIAtelle</h1>
          <p>
            Un documento, un banco. Quattro porte entrano, ogni porta
            preconfigura pannelli e strumenti.
          </p>
        </header>
        <div className="doors">
          {DOORS.map((config) => {
            const Door = DOOR_COMPONENTS[config.mode];
            return <Door key={config.mode} config={config} onEnter={setMode} />;
          })}
        </div>
      </div>
    );
  }

  // A1 (door "import"): the deterministic core proposal is confirmed over the
  // preview. Until the Python → UI data channel exists, the sample document
  // stands in for the core's import_svg output (identical contract shape).
  const a1Doc = mode === "import" ? makeSampleA1() : null;

  return (
    <Workbench mode={mode} spec={spec} onBack={() => setMode(null)} a1Doc={a1Doc} />
  );
}
