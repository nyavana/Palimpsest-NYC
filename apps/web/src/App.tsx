import { MapView } from "@/components/MapView";
import { ChatPane } from "@/components/ChatPane";

/**
 * Palimpsest NYC shell — map on the left, chat pane on the right.
 *
 * The map is rendered via the MapEngine abstraction, so the concrete
 * engine (MapLibre today, Google Photorealistic 3D Tiles later) is
 * selected from `VITE_MAP_ENGINE` and swappable in a single factory file.
 */
export default function App() {
  return (
    <div className="flex h-full w-full flex-row">
      <main className="relative flex-1">
        <MapView />
        <header className="pointer-events-none absolute left-4 top-4 rounded bg-ink/80 px-3 py-2 font-serif text-parchment shadow">
          <h1 className="text-lg">Palimpsest NYC</h1>
          <p className="text-xs opacity-70">Walking tours of Morningside Heights & UWS</p>
        </header>
      </main>
      <aside className="w-96 border-l border-ink/10 bg-parchment p-4">
        <ChatPane />
      </aside>
    </div>
  );
}
