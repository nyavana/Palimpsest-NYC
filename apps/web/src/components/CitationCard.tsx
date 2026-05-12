/**
 * CitationCard — renders one Citation with the locked five-field contract
 * visible on the surface. The chip color comes from `sourceTypeColor`
 * (per-source brand palette, not a Palimpsest token).
 *
 * Spec: design brief §4.6.
 */

import { useEffect, useRef } from "react";

import { sourceTypeColor } from "@/styles/tokens";
import type { Citation } from "@/state/types";

import { CrosshairIcon, ExternalLinkIcon } from "./Icon";

type Props = {
  citation: Citation;
  /** Best-effort title pulled from doc_id. */
  title?: string;
  active?: boolean;
  focusVersion?: number;
  onFocus?: () => void;
};

function titleFromDocId(docId: string): string {
  // doc_id format: `<source>:<slug>` → take the trailing slug, replace `_`
  // with spaces. Falls back to the raw doc_id for unfamiliar shapes.
  const idx = docId.indexOf(":");
  const slug = idx >= 0 ? docId.slice(idx + 1) : docId;
  return slug.replace(/_/g, " ").trim() || docId;
}

export function CitationCard({
  citation,
  title,
  active = false,
  focusVersion = 0,
  onFocus,
}: Props) {
  const chipColor = sourceTypeColor[citation.source_type];
  const shown = title ?? titleFromDocId(citation.doc_id);
  const ref = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!active) return;
    ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [active, focusVersion]);

  return (
    <article
      ref={ref}
      className={`space-y-2 rounded border bg-parchment-deep px-4 py-3 transition-colors ${
        active
          ? "border-archival-blue shadow-[0_0_0_1px_rgba(83,100,192,0.22)]"
          : "border-hairline"
      }`}
    >
      <header className="flex items-center gap-2">
        <span
          className="rounded px-1.5 py-0.5 font-mono text-mono uppercase tracking-wide text-white"
          style={{ backgroundColor: chipColor }}
        >
          {citation.source_type}
        </span>
        {onFocus !== undefined && (
          <button
            type="button"
            onClick={onFocus}
            className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded border transition-colors focus:outline-none focus:ring-2 focus:ring-ink/40 focus:ring-offset-2 focus:ring-offset-parchment-deep ${
              active
                ? "border-archival-blue bg-archival-blue/10 text-archival-blue"
                : "border-hairline text-ink-muted hover:bg-parchment hover:text-ink"
            }`}
            aria-label={`Show ${shown} on the map`}
            title="Show on map"
          >
            <CrosshairIcon className="text-small" />
          </button>
        )}
        <a
          href={citation.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex-1 truncate font-serif text-body font-semibold text-archival-blue underline-offset-4 visited:text-archival-blue-visited hover:underline focus:outline-none focus:ring-2 focus:ring-ink/40 focus:ring-offset-2 focus:ring-offset-parchment-deep"
          title={shown}
        >
          {shown}
          <ExternalLinkIcon className="ml-1 inline-block align-[-2px] text-small" />
        </a>
      </header>

      <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 font-mono text-mono text-ink-muted">
        <dt className="uppercase tracking-wide text-ink-muted">doc_id</dt>
        <dd className="select-all break-all text-ink-soft">{citation.doc_id}</dd>

        <dt className="uppercase tracking-wide text-ink-muted">span</dt>
        <dd className="text-ink-soft">{citation.span}</dd>

        <dt className="uppercase tracking-wide text-ink-muted">turn</dt>
        <dd className="text-ink-soft">{citation.retrieval_turn}</dd>
      </dl>
    </article>
  );
}
