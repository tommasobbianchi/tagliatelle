import type { DoorProps } from "./config";
import { findDoor } from "./config";
import DoorBase from "./DoorBase";

export default function ImportDoor(props: DoorProps) {
  return <DoorBase {...props} config={findDoor("import")} />;
}
