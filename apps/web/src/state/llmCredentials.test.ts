import { beforeEach, describe, expect, it } from "vitest";

import {
  _STORAGE_KEY_FOR_TESTS,
  clearSavedCredentials,
  encodeCredentialsHeader,
  readSavedCredentials,
  writeSavedCredentials,
} from "./llmCredentials";

beforeEach(() => {
  sessionStorage.clear();
});

describe("readSavedCredentials", () => {
  it("returns null when storage is empty", () => {
    expect(readSavedCredentials()).toBeNull();
  });

  it("returns parsed credentials when storage holds a valid JSON shape", () => {
    sessionStorage.setItem(
      _STORAGE_KEY_FOR_TESTS,
      JSON.stringify({ api_key: "sk-1", model: "openai/gpt-4o", base_url: "https://x.test" }),
    );
    expect(readSavedCredentials()).toEqual({
      api_key: "sk-1",
      model: "openai/gpt-4o",
      base_url: "https://x.test",
    });
  });

  it("returns null and evicts entry when stored shape is invalid", () => {
    sessionStorage.setItem(_STORAGE_KEY_FOR_TESTS, JSON.stringify({ api_key: "k" }));
    expect(readSavedCredentials()).toBeNull();
    // Evicted so the UI re-prompts cleanly next time.
    expect(sessionStorage.getItem(_STORAGE_KEY_FOR_TESTS)).toBeNull();
  });

  it("returns null and does not throw on garbage JSON", () => {
    sessionStorage.setItem(_STORAGE_KEY_FOR_TESTS, "{not-json");
    expect(readSavedCredentials()).toBeNull();
  });

  it("does not require base_url", () => {
    writeSavedCredentials({ api_key: "k", model: "m" });
    expect(readSavedCredentials()).toEqual({ api_key: "k", model: "m" });
  });
});

describe("writeSavedCredentials", () => {
  it("round-trips api_key + model", () => {
    writeSavedCredentials({ api_key: "sk-abc", model: "anthropic/claude-haiku" });
    expect(readSavedCredentials()).toEqual({
      api_key: "sk-abc",
      model: "anthropic/claude-haiku",
    });
  });

  it("persists base_url when non-empty", () => {
    writeSavedCredentials({ api_key: "k", model: "m", base_url: "https://gw.example" });
    expect(readSavedCredentials()?.base_url).toBe("https://gw.example");
  });

  it("omits base_url when empty string", () => {
    writeSavedCredentials({ api_key: "k", model: "m", base_url: "" });
    const round = readSavedCredentials();
    expect(round).toEqual({ api_key: "k", model: "m" });
    expect(round?.base_url).toBeUndefined();
  });

  it("does NOT write to localStorage", () => {
    writeSavedCredentials({ api_key: "sk-keep-me-in-session", model: "m" });
    // Per BYOK contract, the key must not survive across browser sessions.
    expect(localStorage.getItem(_STORAGE_KEY_FOR_TESTS)).toBeNull();
  });
});

describe("clearSavedCredentials", () => {
  it("removes the entry", () => {
    writeSavedCredentials({ api_key: "k", model: "m" });
    clearSavedCredentials();
    expect(readSavedCredentials()).toBeNull();
  });

  it("does not throw when nothing is stored", () => {
    expect(() => clearSavedCredentials()).not.toThrow();
  });
});

describe("encodeCredentialsHeader", () => {
  it("base64-encodes a JSON payload that decodes back to input", () => {
    const header = encodeCredentialsHeader({ api_key: "sk-x", model: "m", base_url: "u" });
    const decoded = JSON.parse(atob(header)) as Record<string, string>;
    expect(decoded).toEqual({ api_key: "sk-x", model: "m", base_url: "u" });
  });

  it("omits base_url when empty", () => {
    const header = encodeCredentialsHeader({ api_key: "k", model: "m", base_url: "" });
    const decoded = JSON.parse(atob(header)) as Record<string, string>;
    expect(decoded.base_url).toBeUndefined();
  });
});
