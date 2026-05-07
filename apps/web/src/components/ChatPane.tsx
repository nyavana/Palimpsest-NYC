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
import type { FoodCandidate } from "@/state/types";
import { looksLikeFoodQuery, type UseFoodDiscovery } from "@/state/useFoodDiscovery";
import { useAgentSession } from "@/state/useAgentSession";

import { CitationList } from "./CitationList";
import { Composer } from "./Composer";
import { FoodCandidateList } from "./FoodCandidateList";
import { NarrationStream } from "./NarrationStream";
import { SettingsButton, type SettingsStatus } from "./SettingsButton";
import { WalkTimeline } from "./WalkTimeline";
import { WarningBanner } from "./WarningBanner";

type Props = {
  /** Hook factory injected so App can share the session with MapView. */
  session: ReturnType<typeof useAgentSession>;
  foodDiscovery: UseFoodDiscovery;
  /** Whether the server requires user credentials (no env key configured). */
  byokRequired: boolean;
  /** The user's saved credentials, or null when not set. */
  credentials: LlmCredentials | null;
  /** Open the LLM settings modal. */
  onOpenSettings: () => void;
};

const DEFAULT_FOOD_NEAR: [number, number] = [40.8075, -73.9626];

function lastWalkPoint(session: ReturnType<typeof useAgentSession>): [number, number] | undefined {
  const stops = session.state.walk?.stops ?? [];
  const last = stops[stops.length - 1];
  if (last === undefined) return undefined;
  return [last.lat, last.lon];
}

function buildFoodFollowUp(
  candidate: FoodCandidate,
  originalQuery: string | null,
  session: ReturnType<typeof useAgentSession>,
): string {
  const currentWalkStops = session.state.walk?.stops ?? [];
  const lastStop = currentWalkStops[currentWalkStops.length - 1] ?? null;
  const queryContext =
    originalQuery !== null ? ` from my earlier food search for "${originalQuery}"` : "";
  const cuisine = candidate.cuisine ? ` (${candidate.cuisine.replace(/;/g, ", ")})` : "";
  const destinationHint = `The place is near ${candidate.lat.toFixed(4)}, ${candidate.lon.toFixed(4)}.`;

  if (lastStop !== null) {
    return [
      `I picked ${candidate.name}${cuisine}${queryContext}.`,
      `Please continue the walk from ${lastStop.name} to this place.`,
      destinationHint,
      "Use search_places to confirm the destination before planning the route, then explain the stop briefly.",
    ].join(" ");
  }

  return [
    `I picked ${candidate.name}${cuisine}${queryContext}.`,
    "Please plan a short walking route from Columbia University to this place.",
    destinationHint,
    "Use search_places to confirm the destination before planning the route, then explain briefly why it fits.",
  ].join(" ");
}

export function ChatPane({
  session,
  foodDiscovery,
  byokRequired,
  credentials,
  onOpenSettings,
}: Props) {
  const { state, ask, cancel } = session;
  const busy = state.status === "asking" || state.status === "streaming";
  const composerLocked = byokRequired && credentials === null;

  const status: SettingsStatus = credentials !== null ? "user" : byokRequired ? "missing" : "server";

  const handleAsk = (q: string) => {
    if (looksLikeFoodQuery(q)) {
      void foodDiscovery.search({
        query: q,
        near: lastWalkPoint(session) ?? DEFAULT_FOOD_NEAR,
      });
      return;
    }
    foodDiscovery.clear();
    ask(q, credentials ?? undefined);
  };

  const handleChooseCandidate = (candidate: FoodCandidate) => {
    const followUp = buildFoodFollowUp(candidate, foodDiscovery.state.query, session);
    foodDiscovery.clear();
    ask(followUp, credentials ?? undefined);
  };

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
        <FoodCandidateList
          query={foodDiscovery.state.query}
          status={foodDiscovery.state.status}
          results={foodDiscovery.state.results}
          error={foodDiscovery.state.error}
          onChoose={handleChooseCandidate}
        />
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
