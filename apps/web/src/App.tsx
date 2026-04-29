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
 */

import { ChatPane } from "@/components/ChatPane";
import { MapView } from "@/components/MapView";
import { MapEngineProvider } from "@/state/MapEngineContext";
import { useAgentSession } from "@/state/useAgentSession";

export default function App() {
  const session = useAgentSession();

  return (
    <MapEngineProvider>
      <div className="flex h-full w-full flex-col lg:flex-row">
        <main className="relative h-[55vh] w-full flex-1 lg:h-full">
          <MapView stops={session.state.walk} />
          <header className="pointer-events-none absolute left-4 top-4 rounded bg-ink/85 px-3 py-2 font-serif text-parchment shadow-chip backdrop-blur-sm">
            <h1 className="text-h2 font-semibold leading-tight">Palimpsest NYC</h1>
            <p className="text-small font-sans opacity-80">
              Walking tours of Morningside Heights & UWS
            </p>
          </header>
        </main>
        <aside className="h-[45vh] w-full border-l border-hairline lg:h-full lg:w-[28rem]">
          <ChatPane session={session} />
        </aside>
      </div>
    </MapEngineProvider>
  );
}
