import { useState } from "react";

/**
 * Minimal chat pane stub.
 *
 * Week 1: renders a disabled input with a placeholder.
 * Week 3: will stream agent responses over WebSocket (/agent/ask).
 */
export function ChatPane() {
  const [value, setValue] = useState("");

  return (
    <div className="flex h-full flex-col">
      <h2 className="mb-3 font-serif text-xl">Ask Palimpsest</h2>
      <p className="mb-4 text-sm text-ink/70">
        Type a place or ask for a walking tour. The agent loop ships in Week 3.
      </p>
      <div className="flex-1 overflow-y-auto rounded border border-ink/10 bg-white/50 p-3 text-sm">
        <em className="text-ink/50">No conversation yet.</em>
      </div>
      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          // eslint-disable-next-line no-console
          console.log("ask:", value);
          setValue("");
        }}
      >
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Take me on a walk near Columbia…"
          className="flex-1 rounded border border-ink/20 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ink/30"
        />
        <button
          type="submit"
          className="rounded bg-ink px-3 py-2 text-sm text-parchment hover:bg-ink/80"
        >
          Ask
        </button>
      </form>
    </div>
  );
}
