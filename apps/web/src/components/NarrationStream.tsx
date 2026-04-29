/**
 * NarrationStream — renders the agent's terminal narration plus a small
 * "thinking" ticker (turn N · last tool name) above it while streaming.
 *
 * Spec: design brief §4.5.
 */

import type { SessionState } from "@/state/useAgentSession";

import { LoadingSkeleton } from "./LoadingSkeleton";

type Props = {
  state: SessionState;
};

export function NarrationStream({ state }: Props) {
  const { status, turn, lastToolCall, narration, question } = state;

  if (status === "idle") {
    return (
      <section className="space-y-3 px-4 py-4 text-ink">
        <h3 className="font-serif text-h2 text-ink">Narration</h3>
        <p className="text-small text-ink-muted">
          Ask a question to start a walk. Try{" "}
          <em className="font-serif italic">
            &ldquo;Tell me about a gothic cathedral in Morningside Heights&rdquo;
          </em>
          .
        </p>
      </section>
    );
  }

  return (
    <section className="space-y-3 px-4 py-4">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="font-serif text-h2 text-ink">Narration</h3>
        {status !== "done" && status !== "error" && (
          <span className="font-mono text-mono uppercase tracking-wide text-ink-muted">
            turn {turn || 1}
            {lastToolCall ? ` · ${lastToolCall.name}` : ""}
          </span>
        )}
      </div>

      {question !== null && (
        <p className="font-serif text-small italic text-ink-soft">&ldquo;{question}&rdquo;</p>
      )}

      {narration.length === 0 && (status === "asking" || status === "streaming") ? (
        <LoadingSkeleton />
      ) : narration.length > 0 ? (
        <p className="max-w-prose whitespace-pre-line font-serif text-body leading-relaxed text-ink">
          {narration}
        </p>
      ) : null}
    </section>
  );
}
