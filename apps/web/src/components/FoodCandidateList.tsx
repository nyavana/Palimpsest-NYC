import type { FoodCandidate } from "@/state/types";
import { useTourFocus } from "@/state/TourFocusContext";

import { FoodCandidateCard } from "./FoodCandidateCard";

type Props = {
  query: string | null;
  status: "idle" | "loading" | "ready" | "error";
  results: FoodCandidate[];
  error: string | null;
  onChoose: (candidate: FoodCandidate) => void;
};

export function FoodCandidateList({ query, status, results, error, onChoose }: Props) {
  const { focus, focusDocId } = useTourFocus();

  if (status === "idle") return null;

  return (
    <section className="space-y-3 border-t border-hairline px-4 py-4">
      <header className="flex items-baseline justify-between gap-3">
        <div className="space-y-1">
          <h3 className="font-serif text-h2 text-ink">Food Picks</h3>
          {query !== null ? (
            <p className="text-small text-ink-muted">For "{query}"</p>
          ) : null}
        </div>
        {status === "loading" ? (
          <span className="font-mono text-mono uppercase tracking-wide text-ink-muted">
            searching
          </span>
        ) : null}
      </header>

      {status === "error" ? (
        <p className="rounded border border-ochre/30 bg-ochre/5 px-3 py-2 font-serif text-small text-ink-soft">
          {error ?? "Couldn't load food suggestions right now."}
        </p>
      ) : null}

      {status === "ready" && results.length === 0 ? (
        <p className="rounded border border-hairline bg-parchment-deep px-3 py-2 font-serif text-small text-ink-soft">
          No nearby matches yet. Try a cuisine, mood, or meal like "ramen", "coffee", or
          "cheap lunch".
        </p>
      ) : null}

      {results.length > 0 ? (
        <ul className="space-y-2">
          {results.map((candidate) => (
            <li key={candidate.doc_id}>
              <FoodCandidateCard
                candidate={candidate}
                active={focus.docId === candidate.doc_id}
                focusVersion={focus.version}
                onShowOnMap={() => focusDocId(candidate.doc_id)}
                onChoose={() => onChoose(candidate)}
              />
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
