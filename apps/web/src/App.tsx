/**
 * Palimpsest NYC shell — map fills the main pane, chat lives in the aside.
 *
 * Both panes consume the same `useAgentSession()` so the chat reads agent
 * state and the map can draw the walk that the agent's citations resolved
 * to (via plan_walk on the server).
 *
 * The MapEngine handle is shared via `MapEngineProvider` so the walk
 * timeline's "fly to" buttons can animate the same map instance that
 * MapView mounted, without breaking the engine boundary.
 *
 * V1.1 (BYOK): on mount, the app fetches /config to learn whether the
 * server runs in BYOK-required mode. If so AND the user hasn't already
 * saved credentials in this browser session, the SettingsModal opens
 * automatically and the composer is disabled until credentials exist.
 */

import { useEffect, useRef, useState } from "react";

import { ChatPane } from "@/components/ChatPane";
import { MapView } from "@/components/MapView";
import { SettingsModal } from "@/components/SettingsModal";
import {
  readSavedCredentials,
  type LlmCredentials,
} from "@/state/llmCredentials";
import { MapEngineProvider } from "@/state/MapEngineContext";
import { TourFocusProvider } from "@/state/TourFocusContext";
import { useAgentSession } from "@/state/useAgentSession";
import { useFoodDiscovery } from "@/state/useFoodDiscovery";
import { useServerConfig } from "@/state/useServerConfig";

export default function App() {
  const session = useAgentSession();
  const foodDiscovery = useFoodDiscovery();
  const { config } = useServerConfig();
  const [credentials, setCredentials] = useState<LlmCredentials | null>(() => readSavedCredentials());
  const [settingsOpen, setSettingsOpen] = useState(false);
  const autoOpenedRef = useRef(false);

  // Auto-open settings once when we first learn the server is BYOK-required
  // and we have no saved credentials. The ref guard makes this idempotent
  // even though the effect depends on values that change.
  const byokRequired = config?.byok_required ?? false;
  useEffect(() => {
    if (config === null) return;
    if (autoOpenedRef.current) return;
    if (byokRequired && credentials === null) {
      autoOpenedRef.current = true;
      setSettingsOpen(true);
    }
  }, [config, byokRequired, credentials]);

  return (
    <TourFocusProvider>
      <MapEngineProvider>
        <div className="flex h-full w-full flex-col lg:flex-row">
          <main className="relative h-[55vh] w-full flex-1 lg:h-full">
            <MapView
              walk={session.state.walk}
              citations={session.state.citations}
              candidates={foodDiscovery.state.results}
            />
            <header className="pointer-events-none absolute left-4 top-4 rounded bg-ink/85 px-3 py-2 font-serif text-parchment shadow-chip backdrop-blur-sm">
              <h1 className="text-h2 font-semibold leading-tight">Palimpsest NYC</h1>
              <p className="text-small font-sans opacity-80">
                Walking tours of Morningside Heights & UWS
              </p>
            </header>
          </main>
          <aside className="h-[45vh] w-full border-l border-hairline lg:h-full lg:w-[28rem]">
            <ChatPane
              session={session}
              foodDiscovery={foodDiscovery}
              byokRequired={byokRequired}
              credentials={credentials}
              onOpenSettings={() => setSettingsOpen(true)}
            />
          </aside>
        </div>
        <SettingsModal
          isOpen={settingsOpen}
          onClose={() => setSettingsOpen(false)}
          required={byokRequired && credentials === null}
          defaults={
            config?.defaults
              ? { base_url: config.defaults.base_url, model: config.defaults.model }
              : undefined
          }
          onCredentialsChange={(next) => setCredentials(next)}
        />
      </MapEngineProvider>
    </TourFocusProvider>
  );
}
