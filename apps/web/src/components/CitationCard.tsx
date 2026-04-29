/**
 * CitationCard — renders one Citation with the locked five-field contract
 * visible on the surface. The chip color comes from `sourceTypeColor`
 * (per-source brand palette, not a Palimpsest token).
 *
 * Spec: design brief §4.6.
 */

import { sourceTypeColor } from "@/styles/tokens";
import type { Citation } from "@/state/types";

import { ExternalLinkIcon } from "./Icon";

type Props = {
  citation: Citation;
  /** Best-effort title pulled from doc_id. */
  title?: string;
};

function titleFromDocId(docId: string): string {
  // doc_id format: `<source>:<slug>` → take the trailing slug, replace `_`
  // with spaces. Falls back to the raw doc_id for unfamiliar shapes.
  const idx = docId.indexOf(":");
  const slug = idx >= 0 ? docId.slice(idx + 1) : docId;
  return slug.replace(/_/g, " ").trim() || docId;
}

export function CitationCard({ citation, title }: Props) {
  const chipColor = sourceTypeColor[citation.source_type];
  const shown = title ?? titleFromDocId(citation.doc_id);

  return (
    <article className="space-y-2 rounded border border-hairline bg-parchment-deep px-4 py-3">
      <header className="flex items-center gap-2">
        <span
          className="rounded px-1.5 py-0.5 font-mono text-mono uppercase tracking-wide text-white"
          style={{ backgroundColor: chipColor }}
        >
          {citation.source_type}
        </span>
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
