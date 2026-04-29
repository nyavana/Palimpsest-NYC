/**
 * CitationList — vertical list of CitationCards. Empty until the agent emits
 * `event: citations`.
 */

import type { Citation, PlannedStop } from "@/state/types";

import { CitationCard } from "./CitationCard";

type Props = {
  citations: Citation[];
  walk: PlannedStop[];
  verified: boolean | null;
};

export function CitationList({ citations, walk, verified }: Props) {
  if (citations.length === 0) {
    return null;
  }

  // Best-effort: pull human-readable place names from the walk stops so the
  // citation card can show a real title rather than a slugified doc_id.
  const titles = new Map(walk.map((s) => [s.doc_id, s.name] as const));

  return (
    <section className="space-y-3 border-t border-hairline px-4 py-4">
      <header className="flex items-baseline justify-between gap-3">
        <h3 className="font-serif text-h2 text-ink">Citations</h3>
        {verified !== null && (
          <span
            className={`font-mono text-mono uppercase tracking-wide ${
              verified ? "text-success" : "text-ochre"
            }`}
          >
            {verified ? "verified" : "unverified"}
          </span>
        )}
      </header>

      <ul className="space-y-2">
        {citations.map((c) => (
          <li key={`${c.doc_id}#${c.retrieval_turn}#${c.span}`}>
            <CitationCard citation={c} title={titles.get(c.doc_id)} />
          </li>
        ))}
      </ul>
    </section>
  );
}
