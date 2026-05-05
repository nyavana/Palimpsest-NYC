import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MapEngineProvider } from "@/state/MapEngineContext";
import type { UseAgentSession } from "@/state/useAgentSession";

import { ChatPane } from "./ChatPane";

function makeSession(): UseAgentSession {
  return {
    state: {
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

beforeEach(() => {
  sessionStorage.clear();
});

describe("ChatPane composer gating", () => {
  it("shows the composer when BYOK is not required", () => {
    render(
      <MapEngineProvider>
        <ChatPane
          session={makeSession()}
          byokRequired={false}
          credentials={null}
          onOpenSettings={() => {}}
        />
      </MapEngineProvider>,
    );
    expect(screen.getByRole("button", { name: /Ask/i })).toBeInTheDocument();
    expect(screen.queryByText(/Set up your API key/i)).toBeNull();
  });

  it("shows a CTA instead of the composer when BYOK is required and no creds saved", () => {
    render(
      <MapEngineProvider>
        <ChatPane
          session={makeSession()}
          byokRequired={true}
          credentials={null}
          onOpenSettings={() => {}}
        />
      </MapEngineProvider>,
    );
    expect(screen.getByText(/Set up your API key in Settings/i)).toBeInTheDocument();
    // The Composer's submit button is absent.
    expect(screen.queryByRole("button", { name: /^Ask$/i })).toBeNull();
  });

  it("shows the composer when BYOK is required AND credentials are present", () => {
    render(
      <MapEngineProvider>
        <ChatPane
          session={makeSession()}
          byokRequired={true}
          credentials={{ api_key: "sk-1", model: "openai/x" }}
          onOpenSettings={() => {}}
        />
      </MapEngineProvider>,
    );
    expect(screen.getByRole("button", { name: /Ask/i })).toBeInTheDocument();
  });

  it("renders the 'your keys' status pill when credentials are present", () => {
    render(
      <MapEngineProvider>
        <ChatPane
          session={makeSession()}
          byokRequired={false}
          credentials={{ api_key: "k", model: "m" }}
          onOpenSettings={() => {}}
        />
      </MapEngineProvider>,
    );
    expect(screen.getByText(/your keys/i)).toBeInTheDocument();
  });

  it("renders the 'no keys' status pill when BYOK required and no creds", () => {
    render(
      <MapEngineProvider>
        <ChatPane
          session={makeSession()}
          byokRequired={true}
          credentials={null}
          onOpenSettings={() => {}}
        />
      </MapEngineProvider>,
    );
    expect(screen.getByText(/no keys/i)).toBeInTheDocument();
  });

  it("renders the 'server keys' status pill when env-key mode and no user creds", () => {
    render(
      <MapEngineProvider>
        <ChatPane
          session={makeSession()}
          byokRequired={false}
          credentials={null}
          onOpenSettings={() => {}}
        />
      </MapEngineProvider>,
    );
    expect(screen.getByText(/server keys/i)).toBeInTheDocument();
  });
});
