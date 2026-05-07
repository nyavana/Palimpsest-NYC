/**
 * WalkTimeline — numbered list of stops along the planned walk, with a
 * fly-to button per stop, a per-leg turn-by-turn disclosure, and a footer
 * total of distance + duration. The `MapEngine` handle comes from the
 * `MapEngineProvider`; the engine instance is the only thing that knows
 * how to animate the map, so this component never imports an engine
 * directly.
 *
 * Spec: design brief §4.7; route extension per `agent-route-planning`
 * spec §map-engine "Walk frame consumer renders LineString geometry +
 * steps" and §agent-tools "plan_walk tool output contract".
 *
 * Stop 0 has no incoming leg, so its disclosure is omitted.
 *
 * The component intentionally takes minimal liberties with the existing
 * design system: no new colors, shadows, or icons beyond a chevron added
 * to the existing `Icon.tsx` set; the disclosure indent (`pl-10`) aligns
 * the steps list under the stop's text column rather than its badge, and
 * uses the existing `font-mono text-mono` voice already established for
 * distance labels.
 */

import { useState } from "react";

import type { PlannedRoute, PlannedStop, RouteLeg } from "@/state/types";
import { useMapEngineHandle } from "@/state/MapEngineContext";
import { useTourFocus } from "@/state/TourFocusContext";
import { WALK_MS_PER_STEP } from "@/styles/tokens";

import { ChevronRightIcon, CrosshairIcon } from "./Icon";

type Props = {
  walk: PlannedRoute | null;
};

const DEFAULT_FLYTO_ZOOM = 17.5;

/**
 * Render a leg distance + ETA pair. Used by the disclosure trigger when an
 * incoming leg is available; falls back to the legacy `leg_distance_m`
 * straight-line haversine distance carried on the stop itself.
 */
function formatLegSummary(distanceM: number, durationS?: number): string {
  const meters = Math.round(distanceM);
  const minutes =
    durationS !== undefined
      ? Math.max(1, Math.round(durationS / 60))
      : Math.max(1, Math.round(distanceM / WALK_MS_PER_STEP));
  return `${meters} m  ·  ~${minutes} min`;
}

/** Per-step distance label, right-aligned next to the instruction text. */
function formatStepDistance(distanceM: number): string {
  return `${Math.round(distanceM)} m`;
}

/** "Total · 1.2 km · ~15 min" — kilometers to one decimal once we hit 1 km. */
function formatTotals(distanceM: number, durationS: number): string {
  const distanceLabel = distanceM >= 1000 ? `${(distanceM / 1000).toFixed(1)} km` : `${Math.round(distanceM)} m`;
  const minutes = Math.max(1, Math.round(durationS / 60));
  return `Total  ·  ${distanceLabel}  ·  ~${minutes} min`;
}

export function WalkTimeline({ walk }: Props) {
  const handle = useMapEngineHandle();
  const { focus, focusDocId } = useTourFocus();
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

  if (walk === null || walk.stops.length === 0) return null;

  const stops = walk.stops;
  const legs: RouteLeg[] = walk.legs ?? [];
  const tspOptimized = walk.stop_ordering === "tsp_optimized";
  const hasTotals = walk.total_distance_m !== undefined && walk.total_duration_s !== undefined;

  const flyTo = (stop: PlannedStop) => {
    const engine = handle.get();
    if (engine === null) return;
    focusDocId(stop.doc_id);
    void engine.flyTo(
      {
        center: { lat: stop.lat, lng: stop.lon },
        zoom: DEFAULT_FLYTO_ZOOM,
        pitch: 60,
      },
      1200,
    );
  };

  const toggleExpanded = (index: number) => {
    setExpandedIndex((cur) => (cur === index ? null : index));
  };

  return (
    <section className="space-y-3 border-t border-hairline px-4 py-4">
      <header className="flex items-baseline justify-between gap-3">
        <h3 className="font-serif text-h2 text-ink">Walk</h3>
        {tspOptimized && (
          <span className="font-mono text-mono uppercase tracking-wide text-ink-muted">
            tsp-optimized
          </span>
        )}
      </header>
      <ol className="space-y-1">
        {stops.map((stop) => {
          const active = stop.doc_id === focus.docId;
          const expanded = stop.index === expandedIndex;
          // Stop 0 has no incoming leg; for index >= 1 we look up legs[i-1].
          // If the routed-tool result didn't include legs (legacy V1 walk),
          // fall back to the haversine `leg_distance_m` carried on the stop.
          const incomingLeg: RouteLeg | undefined =
            stop.index >= 1 ? legs[stop.index - 1] : undefined;
          const legDistanceM = incomingLeg?.distance_m ?? stop.leg_distance_m;
          const legDurationS = incomingLeg?.duration_s;
          const hasDisclosure = incomingLeg !== undefined && incomingLeg.steps.length > 0;
          const legSummary =
            legDistanceM !== undefined && legDistanceM > 0
              ? formatLegSummary(legDistanceM, legDurationS)
              : null;

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

              {legSummary !== null && (
                <div className="pl-12 pr-2">
                  {hasDisclosure ? (
                    <button
                      type="button"
                      onClick={() => toggleExpanded(stop.index)}
                      aria-expanded={expanded}
                      aria-controls={`walk-steps-${stop.index}`}
                      className="flex w-full items-center gap-2 rounded py-1 text-left font-mono text-mono text-ink-muted transition-colors duration-fast ease-out hover:text-ink-soft focus:outline-none focus:ring-2 focus:ring-ink/40 focus:ring-offset-2 focus:ring-offset-parchment"
                    >
                      <span>{legSummary}</span>
                      <ChevronRightIcon
                        aria-hidden="true"
                        className={`text-base transition-transform duration-fast ease-out ${
                          expanded ? "rotate-90" : ""
                        }`}
                      />
                    </button>
                  ) : (
                    <span className="block py-1 font-mono text-mono text-ink-muted">
                      {legSummary}
                    </span>
                  )}

                  {hasDisclosure && expanded && incomingLeg && (
                    <ol
                      id={`walk-steps-${stop.index}`}
                      aria-label={`Turn-by-turn instructions for stop ${stop.index + 1}`}
                      className="mt-1 space-y-1 pb-1"
                    >
                      {incomingLeg.steps.map((step, i) => (
                        <li
                          key={`${stop.index}:${i}:${step.maneuver_type}`}
                          className="flex items-baseline gap-3"
                        >
                          <span
                            className="w-5 shrink-0 font-mono text-mono text-ink-muted"
                            aria-hidden="true"
                          >
                            {i + 1}.
                          </span>
                          <span className="min-w-0 flex-1 font-serif text-small text-ink-soft">
                            {step.instruction}
                          </span>
                          <span className="shrink-0 font-mono text-mono text-ink-muted">
                            {formatStepDistance(step.distance_m)}
                          </span>
                        </li>
                      ))}
                    </ol>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
      {hasTotals && (
        <footer className="border-t border-hairline pt-3 font-mono text-mono uppercase tracking-wide text-ink-muted">
          {formatTotals(walk.total_distance_m as number, walk.total_duration_s as number)}
        </footer>
      )}
    </section>
  );
}
