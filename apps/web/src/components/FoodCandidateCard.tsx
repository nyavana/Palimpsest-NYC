import { useEffect, useMemo, useRef } from "react";

import type { FoodCandidate } from "@/state/types";

import { CheckIcon, CrosshairIcon, ExternalLinkIcon } from "./Icon";

type Props = {
  candidate: FoodCandidate;
  active?: boolean;
  focusVersion?: number;
  onShowOnMap: () => void;
  onChoose: () => void;
};

function formatDistance(distanceM: number | null): string | null {
  if (distanceM === null) return null;
  if (distanceM >= 1000) return `${(distanceM / 1000).toFixed(1)} km`;
  return `${Math.round(distanceM)} m`;
}

export function FoodCandidateCard({
  candidate,
  active = false,
  focusVersion = 0,
  onShowOnMap,
  onChoose,
}: Props) {
  const ref = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!active) return;
    ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [active, focusVersion]);

  const meta = useMemo(() => {
    const bits: string[] = [];
    if (candidate.cuisine) bits.push(candidate.cuisine.replace(/;/g, ", "));
    if (candidate.amenity) bits.push(candidate.amenity.replace(/_/g, " "));
    const distance = formatDistance(candidate.distance_m);
    if (distance) bits.push(distance);
    return bits.join(" - ");
  }, [candidate.amenity, candidate.cuisine, candidate.distance_m]);

  return (
    <article
      ref={ref}
      className={`space-y-3 rounded border px-4 py-3 transition-colors ${
        active
          ? "border-archival-blue bg-parchment shadow-[0_0_0_1px_rgba(83,100,192,0.18)]"
          : "border-hairline bg-parchment-deep"
      }`}
    >
      <header className="space-y-1">
        <div className="flex items-start justify-between gap-3">
          <h4 className="min-w-0 flex-1 font-serif text-body font-semibold text-ink">
            {candidate.name}
          </h4>
          <a
            href={candidate.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 text-archival-blue hover:underline focus:outline-none focus:ring-2 focus:ring-ink/40"
            aria-label={`Open source for ${candidate.name}`}
          >
            <ExternalLinkIcon className="text-base" />
          </a>
        </div>
        {meta.length > 0 ? (
          <p className="font-mono text-mono uppercase tracking-wide text-ink-muted">{meta}</p>
        ) : null}
      </header>

      <p className="font-serif text-small leading-snug text-ink-soft">{candidate.why}</p>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onShowOnMap}
          className={`inline-flex items-center gap-1 rounded border px-2.5 py-1.5 font-serif text-small transition-colors focus:outline-none focus:ring-2 focus:ring-ink/40 ${
            active
              ? "border-archival-blue bg-archival-blue/10 text-archival-blue"
              : "border-hairline text-ink-soft hover:bg-parchment"
          }`}
        >
          <CrosshairIcon className="text-small" />
          Show on map
        </button>
        <button
          type="button"
          onClick={onChoose}
          className="inline-flex items-center gap-1 rounded bg-oxblood px-2.5 py-1.5 font-serif text-small text-parchment transition-colors hover:bg-oxblood-hover focus:outline-none focus:ring-2 focus:ring-ink/40"
        >
          <CheckIcon className="text-small" />
          Choose this place
        </button>
      </div>
    </article>
  );
}
