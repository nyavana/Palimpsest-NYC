/**
 * ChatPane — composes the aside column from the session state.
 *
 * Owns the agent session and feeds slices of state into the dumb child
 * components. The walk is rendered on the map by App's effect; this pane
 * only renders the timeline + fly-to controls.
 */

import { useAgentSession } from "@/state/useAgentSession";

import { CitationList } from "./CitationList";
import { Composer } from "./Composer";
import { NarrationStream } from "./NarrationStream";
import { WalkTimeline } from "./WalkTimeline";
import { WarningBanner } from "./WarningBanner";

type Props = {
  /** Hook factory injected so App can share the session with MapView. */
  session: ReturnType<typeof useAgentSession>;
};

export function ChatPane({ session }: Props) {
  const { state, ask, cancel } = session;
  const busy = state.status === "asking" || state.status === "streaming";

  return (
    <div className="flex h-full flex-col bg-parchment">
      <header className="space-y-1 border-b border-hairline px-4 py-4">
        <h2 className="font-serif text-display font-semibold text-ink">Ask Palimpsest</h2>
        <p className="text-small text-ink-muted">
          Walking tours of Morningside Heights & the Upper West Side, grounded in the public-domain
          archive.
        </p>
      </header>

      <div className="flex-1 overflow-y-auto">
        <NarrationStream state={state} />
        <WarningBanner warnings={state.warnings} />
        <CitationList
          citations={state.citations}
          walk={state.walk}
          verified={state.result?.verified ?? null}
        />
        <WalkTimeline stops={state.walk} />
      </div>

      <Composer busy={busy} onAsk={ask} onCancel={cancel} />
    </div>
  );
}
