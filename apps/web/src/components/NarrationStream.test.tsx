import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SessionState } from "@/state/useAgentSession";

import { NarrationStream } from "./NarrationStream";

function makeState(overrides: Partial<SessionState> = {}): SessionState {
  return {
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
    ...overrides,
  };
}

describe("NarrationStream", () => {
  it("renders prior turns above the active question in a multi-turn session", () => {
    render(
      <NarrationStream
        state={makeState({
          status: "done",
          question: "Make it shorter",
          narration: "Here's a shorter version.",
          history: [
            {
              question: "Tell me about Riverside Church",
              narration: "Riverside Church is a landmark overlooking the Hudson.",
              citations: [],
              walk: null,
              warnings: [],
              result: null,
              status: "done",
            },
          ],
        })}
      />,
    );

    expect(screen.getByText("“Tell me about Riverside Church”")).toBeInTheDocument();
    expect(
      screen.getByText("Riverside Church is a landmark overlooking the Hudson."),
    ).toBeInTheDocument();
    expect(screen.getByText("“Make it shorter”")).toBeInTheDocument();
    expect(screen.getByText("Here's a shorter version.")).toBeInTheDocument();
  });
});
