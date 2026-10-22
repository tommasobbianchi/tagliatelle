import type { DoorProps } from "./config";
import { findDoor } from "./config";
import DoorBase from "./DoorBase";

export default function DescribeDoor(props: DoorProps) {
  return <DoorBase {...props} config={findDoor("describe")} />;
}
