import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MapEngineProvider } from "@/state/MapEngineContext";
import { TourFocusProvider } from "@/state/TourFocusContext";
import type { UseAgentSession } from "@/state/useAgentSession";
import type { UseFoodDiscovery } from "@/state/useFoodDiscovery";

import { ChatPane } from "./ChatPane";

function makeSession(): UseAgentSession {
  return {
    state: {
      history: [],
      status: "idle",
      question: null,
      turn: 0,
      lastToolCall: null,
      narration: "",
      citations: [],
      walk: null,
      warnings: [],
      result: null,
    },
    ask: vi.fn(),
    cancel: vi.fn(),
    reset: vi.fn(),
  };
}

function makeFoodDiscovery(): UseFoodDiscovery {
  return {
    state: {
      query: null,
      status: "idle",
      results: [],
      error: null,
    },
    search: vi.fn().mockResolvedValue(undefined),
    clear: vi.fn(),
    hasResults: false,
  };
}

beforeEach(() => {
  sessionStorage.clear();
});

describe("ChatPane composer gating", () => {
  it("shows the composer when BYOK is not required", () => {
    render(
      <TourFocusProvider>
        <MapEngineProvider>
          <ChatPane
            session={makeSession()}
            foodDiscovery={makeFoodDiscovery()}
            byokRequired={false}
            credentials={null}
            onOpenSettings={() => {}}
          />
        </MapEngineProvider>
      </TourFocusProvider>,
    );
    expect(screen.getByRole("button", { name: /Ask/i })).toBeInTheDocument();
    expect(screen.queryByText(/Set up your API key/i)).toBeNull();
  });

  it("shows a CTA instead of the composer when BYOK is required and no creds saved", () => {
    render(
      <TourFocusProvider>
        <MapEngineProvider>
          <ChatPane
            session={makeSession()}
            foodDiscovery={makeFoodDiscovery()}
            byokRequired={true}
            credentials={null}
            onOpenSettings={() => {}}
          />
        </MapEngineProvider>
      </TourFocusProvider>,
    );
    expect(screen.getByText(/Set up your API key in Settings/i)).toBeInTheDocument();
    // The Composer's submit button is absent.
    expect(screen.queryByRole("button", { name: /^Ask$/i })).toBeNull();
  });

  it("shows the composer when BYOK is required AND credentials are present", () => {
    render(
      <TourFocusProvider>
        <MapEngineProvider>
          <ChatPane
            session={makeSession()}
            foodDiscovery={makeFoodDiscovery()}
            byokRequired={true}
            credentials={{ api_key: "sk-1", model: "openai/x" }}
            onOpenSettings={() => {}}
          />
        </MapEngineProvider>
      </TourFocusProvider>,
    );
    expect(screen.getByRole("button", { name: /Ask/i })).toBeInTheDocument();
  });

  it("renders the 'your keys' status pill when credentials are present", () => {
    render(
      <TourFocusProvider>
        <MapEngineProvider>
          <ChatPane
            session={makeSession()}
            foodDiscovery={makeFoodDiscovery()}
            byokRequired={false}
            credentials={{ api_key: "k", model: "m" }}
            onOpenSettings={() => {}}
          />
        </MapEngineProvider>
      </TourFocusProvider>,
    );
    expect(screen.getByText(/your keys/i)).toBeInTheDocument();
  });

  it("renders the 'no keys' status pill when BYOK required and no creds", () => {
    render(
      <TourFocusProvider>
        <MapEngineProvider>
          <ChatPane
            session={makeSession()}
            foodDiscovery={makeFoodDiscovery()}
            byokRequired={true}
            credentials={null}
            onOpenSettings={() => {}}
          />
        </MapEngineProvider>
      </TourFocusProvider>,
    );
    expect(screen.getByText(/no keys/i)).toBeInTheDocument();
  });

  it("renders the 'server keys' status pill when env-key mode and no user creds", () => {
    render(
      <TourFocusProvider>
        <MapEngineProvider>
          <ChatPane
            session={makeSession()}
            foodDiscovery={makeFoodDiscovery()}
            byokRequired={false}
            credentials={null}
            onOpenSettings={() => {}}
          />
        </MapEngineProvider>
      </TourFocusProvider>,
    );
    expect(screen.getByText(/server keys/i)).toBeInTheDocument();
  });

  it("routes food-intent prompts into food discovery instead of agent ask", async () => {
    const session = makeSession();
    const foodDiscovery = makeFoodDiscovery();

    render(
      <TourFocusProvider>
        <MapEngineProvider>
          <ChatPane
            session={session}
            foodDiscovery={foodDiscovery}
            byokRequired={false}
            credentials={null}
            onOpenSettings={() => {}}
          />
        </MapEngineProvider>
      </TourFocusProvider>,
    );

    await userEvent.type(screen.getByLabelText(/Ask Palimpsest a question/i), "I want ramen");
    await userEvent.click(screen.getByRole("button", { name: /^Ask$/i }));

    expect(foodDiscovery.search).toHaveBeenCalledWith({
      query: "I want ramen",
      near: [40.8075, -73.9626],
    });
    expect(session.ask).not.toHaveBeenCalled();
  });
});
