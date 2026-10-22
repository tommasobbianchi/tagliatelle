import type { DoorProps } from "./config";

/** Shared door card. The four concrete doors (one file each) only fix their mode. */
export default function DoorBase({ config, onEnter }: DoorProps) {
  return (
    <section className="door" data-testid={`door-${config.mode}`}>
      <h3>{config.title}</h3>
      <p className="door-blurb">{config.blurb}</p>
      <button type="button" onClick={() => onEnter(config.mode)}>
        {config.title}
      </button>
    </section>
  );
}
