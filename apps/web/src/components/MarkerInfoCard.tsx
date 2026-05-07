/**
 * MarkerInfoCard — popup card rendered into the engine's popup container
 * via createPortal. Two variants:
 *   - "hover": small preview, name only.
 *   - "pinned": full card with chip, body (Wikipedia thumbnail+extract,
 *     citation span fallback, or name-only when there's no citation),
 *     external-link footer, and a close button.
 */

import { sourceTypeColor } from "@/styles/tokens";
import type { Citation, PlannedStop } from "@/state/types";
import { useWikipediaSummary } from "@/state/useWikipediaSummary";

import { EyeIcon, ExternalLinkIcon } from "./Icon";

type Props = {
  variant: "hover" | "pinned";
  stop: PlannedStop;
  citation: Citation | null;
  onClose: () => void;
  onRevealCitation?: () => void;
  bodyText?: string | null;
};

export function MarkerInfoCard({
  variant,
  stop,
  citation,
  onClose,
  onRevealCitation,
  bodyText,
}: Props) {
  if (variant === "hover") {
    return (
      <div className="flex max-w-[220px] items-center gap-2 rounded border border-hairline bg-parchment px-3 py-2 shadow-md">
        <NumberBadge index={stop.index} />
        <span className="truncate font-serif text-body text-ink">{stop.name}</span>
      </div>
    );
  }

  return (
    <article className="w-[300px] space-y-3 rounded border border-hairline bg-parchment p-3 shadow-md">
      <header className="flex items-start gap-2">
        <NumberBadge index={stop.index} />
        <h3 className="min-w-0 flex-1 font-serif text-body font-semibold leading-tight text-ink">
          {stop.name}
        </h3>
        <button
          type="button"
          aria-label="Close popup"
          onClick={onClose}
          className="shrink-0 rounded px-1 text-ink-muted hover:text-ink focus:outline-none focus:ring-2 focus:ring-ink/40"
        >
          ×
        </button>
      </header>

      {citation !== null && (
        <div>
          <span
            className="rounded px-1.5 py-0.5 font-mono text-mono uppercase tracking-wide text-white"
            style={{ backgroundColor: sourceTypeColor[citation.source_type] }}
          >
            {citation.source_type}
          </span>
        </div>
      )}

      <PinnedBody stop={stop} citation={citation} bodyText={bodyText} />

      {citation !== null && (
        <footer className="flex items-center gap-2">
          {onRevealCitation !== undefined && (
            <button
              type="button"
              onClick={onRevealCitation}
              className="inline-flex items-center gap-1 rounded border border-hairline px-2 py-1 font-serif text-small text-ink-soft transition-colors hover:bg-parchment-deep focus:outline-none focus:ring-2 focus:ring-ink/40"
            >
              <EyeIcon className="text-small" />
              Reveal citation
            </button>
          )}
          <a
            href={citation.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 font-serif text-small text-archival-blue underline-offset-4 hover:underline focus:outline-none focus:ring-2 focus:ring-ink/40"
          >
            View source <ExternalLinkIcon className="text-small" />
          </a>
        </footer>
      )}
    </article>
  );
}

function NumberBadge({ index }: { index: number }) {
  return (
    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-hairline bg-parchment-deep font-serif text-small font-semibold text-ink">
      {index + 1}
    </span>
  );
}

function PinnedBody({
  stop,
  citation,
  bodyText,
}: {
  stop: PlannedStop;
  citation: Citation | null;
  bodyText?: string | null;
}) {
  const isWikipedia = stop.doc_id.startsWith("wikipedia:");
  const fetchState = useWikipediaSummary(isWikipedia ? stop.doc_id : null);

  if (citation === null) {
    if (bodyText === undefined || bodyText === null || bodyText.trim().length === 0) {
      return null;
    }
    return <p className="font-serif text-small leading-snug text-ink-soft">{bodyText}</p>;
  }

  if (isWikipedia) {
    if (fetchState.status === "loading") {
      return (
        <div role="status" aria-label="Loading Wikipedia summary" className="space-y-2">
          <span className="block h-3 w-11/12 rounded bg-hairline motion-safe:animate-pulse" />
          <span className="block h-3 w-10/12 rounded bg-hairline motion-safe:animate-pulse" />
          <span className="block h-3 w-9/12 rounded bg-hairline motion-safe:animate-pulse" />
        </div>
      );
    }
    if (fetchState.status === "success") {
      return (
        <div className="flex gap-3">
          {fetchState.summary.thumbnailUrl !== null && (
            <img
              src={fetchState.summary.thumbnailUrl}
              alt={fetchState.summary.title}
              className="h-24 w-24 shrink-0 rounded border border-hairline object-cover"
              loading="lazy"
            />
          )}
          <p className="flex-1 font-serif text-small leading-snug text-ink-soft">
            {fetchState.summary.extract}
          </p>
        </div>
      );
    }
    // idle (e.g. transient before useEffect runs) or error → fall through to span fallback.
  }

  return <p className="font-serif text-small italic leading-snug text-ink-soft">{citation.span}</p>;
}
