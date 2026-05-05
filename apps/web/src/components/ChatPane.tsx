/**
 * ChatPane — composes the aside column from the session state.
 *
 * Owns the agent session and feeds slices of state into the dumb child
 * components. The walk is rendered on the map by App's effect; this pane
 * only renders the timeline + fly-to controls.
 *
 * V1.1 (BYOK): the pane receives byokRequired + a handler to open the
 * Settings modal. When BYOK is required and no credentials are present,
 * the composer is disabled with a CTA pointing at Settings.
 */

import type { LlmCredentials } from "@/state/llmCredentials";
import { useAgentSession } from "@/state/useAgentSession";

import { CitationList } from "./CitationList";
import { Composer } from "./Composer";
import { NarrationStream } from "./NarrationStream";
import { SettingsButton, type SettingsStatus } from "./SettingsButton";
import { WalkTimeline } from "./WalkTimeline";
import { WarningBanner } from "./WarningBanner";

type Props = {
  /** Hook factory injected so App can share the session with MapView. */
  session: ReturnType<typeof useAgentSession>;
  /** Whether the server requires user credentials (no env key configured). */
  byokRequired: boolean;
  /** The user's saved credentials, or null when not set. */
  credentials: LlmCredentials | null;
  /** Open the LLM settings modal. */
  onOpenSettings: () => void;
};

export function ChatPane({ session, byokRequired, credentials, onOpenSettings }: Props) {
  const { state, ask, cancel } = session;
  const busy = state.status === "asking" || state.status === "streaming";
  const composerLocked = byokRequired && credentials === null;

  const status: SettingsStatus = credentials !== null ? "user" : byokRequired ? "missing" : "server";

  const handleAsk = (q: string) => ask(q, credentials ?? undefined);

  return (
    <div className="flex h-full flex-col bg-parchment">
      <header className="flex items-start justify-between gap-3 border-b border-hairline px-4 py-4">
        <div className="space-y-1">
          <h2 className="font-serif text-display font-semibold text-ink">Ask Palimpsest</h2>
          <p className="text-small text-ink-muted">
            Walking tours of Morningside Heights & the Upper West Side, grounded in the public-domain
            archive.
          </p>
        </div>
        <SettingsButton status={status} onClick={onOpenSettings} />
      </header>

      <div className="flex-1 overflow-y-auto">
        <NarrationStream state={state} />
        <WarningBanner warnings={state.warnings} />
        <CitationList
          citations={state.citations}
          walk={state.walk}
          verified={state.result?.verified ?? null}
        />
        <WalkTimeline walk={state.walk} />
      </div>

      {composerLocked ? (
        <div className="border-t border-hairline px-4 py-3">
          <button
            type="button"
            onClick={onOpenSettings}
            className="flex w-full items-center justify-center gap-2 rounded border border-dashed border-oxblood/40 bg-oxblood/5 px-3 py-3 text-small font-medium text-oxblood transition-colors hover:bg-oxblood/10 focus:outline-none focus:ring-2 focus:ring-ink/40"
          >
            Set up your API key in Settings to start chatting
          </button>
        </div>
      ) : (
        <Composer busy={busy} onAsk={handleAsk} onCancel={cancel} />
      )}
    </div>
  );
}
