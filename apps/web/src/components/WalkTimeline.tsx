/**
 * WalkTimeline — numbered list of stops along the planned walk, with a
 * fly-to button per stop. The `MapEngine` handle comes from the
 * `MapEngineProvider`; the engine instance is the only thing that knows
 * how to animate the map, so this component never imports an engine
 * directly.
 *
 * Spec: design brief §4.7.
 */

import { useState } from "react";

import type { PlannedStop } from "@/state/types";
import { useMapEngineHandle } from "@/state/MapEngineContext";
import { WALK_MS_PER_STEP } from "@/styles/tokens";

import { CrosshairIcon } from "./Icon";

type Props = {
  stops: PlannedStop[];
};

const DEFAULT_FLYTO_ZOOM = 17.5;

function formatLeg(leg_distance_m: number): string | null {
  if (leg_distance_m <= 0) return null;
  const meters = Math.round(leg_distance_m);
  const minutes = Math.max(1, Math.round(leg_distance_m / WALK_MS_PER_STEP));
  return `${meters} m  ·  ~${minutes} min`;
}

export function WalkTimeline({ stops }: Props) {
  const handle = useMapEngineHandle();
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  if (stops.length === 0) return null;

  const flyTo = (stop: PlannedStop) => {
    const engine = handle.get();
    if (engine === null) return;
    setActiveIndex(stop.index);
    void engine.flyTo(
      {
        center: { lat: stop.lat, lng: stop.lon },
        zoom: DEFAULT_FLYTO_ZOOM,
        pitch: 60,
      },
      1200,
    );
  };

  return (
    <section className="space-y-3 border-t border-hairline px-4 py-4">
      <h3 className="font-serif text-h2 text-ink">Walk</h3>
      <ol className="space-y-1">
        {stops.map((stop) => {
          const active = stop.index === activeIndex;
          const leg = formatLeg(stop.leg_distance_m);
          return (
            <li key={`${stop.index}:${stop.doc_id}`}>
              <button
                type="button"
                onClick={() => flyTo(stop)}
                className={`group flex w-full items-start gap-3 rounded px-2 py-2 text-left transition-colors duration-fast ease-out focus:outline-none focus:ring-2 focus:ring-ink/40 focus:ring-offset-2 focus:ring-offset-parchment ${
                  active ? "bg-parchment-deep" : "hover:bg-parchment-deep/60"
                }`}
                aria-label={`Fly to stop ${stop.index + 1}: ${stop.name}`}
              >
                <span
                  className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full font-serif text-small font-semibold ${
                    active
                      ? "bg-oxblood text-parchment"
                      : "border border-hairline bg-parchment text-ink"
                  }`}
                >
                  {stop.index + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-serif text-body text-ink">
                    {stop.name}
                  </span>
                  {leg !== null && (
                    <span className="block font-mono text-mono text-ink-muted">{leg}</span>
                  )}
                </span>
                <span
                  className={`flex h-7 w-7 shrink-0 items-center justify-center rounded text-base text-ink-soft transition-opacity duration-fast ease-out ${
                    active ? "opacity-100" : "opacity-60 group-hover:opacity-100"
                  }`}
                  aria-hidden="true"
                >
                  <CrosshairIcon />
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
