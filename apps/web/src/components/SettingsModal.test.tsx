import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  _STORAGE_KEY_FOR_TESTS,
  readSavedCredentials,
  writeSavedCredentials,
} from "@/state/llmCredentials";

import { SettingsModal } from "./SettingsModal";

beforeEach(() => {
  sessionStorage.clear();
  // jsdom may not have a real fetch — install a no-op spy each test.
  vi.spyOn(globalThis, "fetch");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SettingsModal", () => {
  it("renders nothing when isOpen=false", () => {
    render(
      <SettingsModal
        isOpen={false}
        onClose={() => {}}
        required={false}
        onCredentialsChange={() => {}}
      />,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("hydrates form fields from sessionStorage when opened", () => {
    writeSavedCredentials({ api_key: "sk-saved", model: "openai/gpt-4o", base_url: "https://x.test" });
    render(
      <SettingsModal isOpen={true} onClose={() => {}} required={false} onCredentialsChange={() => {}} />,
    );
    const apiKey = screen.getByLabelText(/API key/i, { selector: "input" }) as HTMLInputElement;
    const model = screen.getByLabelText(/Model/i) as HTMLInputElement;
    const baseUrl = screen.getByLabelText(/Base URL/i) as HTMLInputElement;
    expect(apiKey.value).toBe("sk-saved");
    expect(model.value).toBe("openai/gpt-4o");
    expect(baseUrl.value).toBe("https://x.test");
  });

  it("Save button is disabled until both api_key and model are filled", async () => {
    const user = userEvent.setup();
    render(
      <SettingsModal isOpen={true} onClose={() => {}} required={true} onCredentialsChange={() => {}} />,
    );
    const save = screen.getByRole("button", { name: /^Save$/ });
    expect(save).toBeDisabled();

    await user.type(screen.getByLabelText(/API key/i, { selector: "input" }), "sk-1");
    expect(save).toBeDisabled();

    await user.type(screen.getByLabelText(/Model/i), "openai/gpt");
    expect(save).toBeEnabled();
  });

  it("Save writes to sessionStorage and notifies parent", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onClose = vi.fn();
    render(
      <SettingsModal isOpen={true} onClose={onClose} required={false} onCredentialsChange={onChange} />,
    );

    await user.type(screen.getByLabelText(/API key/i, { selector: "input" }), "sk-new");
    await user.type(screen.getByLabelText(/Model/i), "anthropic/claude");
    await user.click(screen.getByRole("button", { name: /^Save$/ }));

    expect(readSavedCredentials()).toEqual({
      api_key: "sk-new",
      model: "anthropic/claude",
    });
    expect(onChange).toHaveBeenCalledWith({ api_key: "sk-new", model: "anthropic/claude" });
    expect(onClose).toHaveBeenCalled();
  });

  it("Clear removes credentials and notifies parent with null", async () => {
    const user = userEvent.setup();
    writeSavedCredentials({ api_key: "k", model: "m" });
    const onChange = vi.fn();
    render(
      <SettingsModal isOpen={true} onClose={() => {}} required={false} onCredentialsChange={onChange} />,
    );

    await user.click(screen.getByRole("button", { name: /^Clear$/ }));
    expect(sessionStorage.getItem(_STORAGE_KEY_FOR_TESTS)).toBeNull();
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("password field toggles visibility when the eye button is clicked", async () => {
    const user = userEvent.setup();
    render(
      <SettingsModal isOpen={true} onClose={() => {}} required={false} onCredentialsChange={() => {}} />,
    );
    const apiKey = screen.getByLabelText(/API key/i, { selector: "input" }) as HTMLInputElement;
    expect(apiKey.type).toBe("password");
    await user.click(screen.getByRole("button", { name: /Show API key/i }));
    expect(apiKey.type).toBe("text");
  });

  it("Cancel button is hidden when required=true", () => {
    render(
      <SettingsModal isOpen={true} onClose={() => {}} required={true} onCredentialsChange={() => {}} />,
    );
    expect(screen.queryByRole("button", { name: /^Cancel$/ })).toBeNull();
  });

  it("Cancel button is shown when required=false", () => {
    render(
      <SettingsModal isOpen={true} onClose={() => {}} required={false} onCredentialsChange={() => {}} />,
    );
    expect(screen.getByRole("button", { name: /^Cancel$/ })).toBeInTheDocument();
  });

  it("Test connection sends X-LLM-Credentials header and reports OK on 200", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.mocked(globalThis.fetch);
    fetchSpy.mockResolvedValueOnce(
      new Response(new ReadableStream({ start: (c) => c.close() }), { status: 200 }),
    );

    render(
      <SettingsModal isOpen={true} onClose={() => {}} required={true} onCredentialsChange={() => {}} />,
    );

    await user.type(screen.getByLabelText(/API key/i, { selector: "input" }), "sk-test");
    await user.type(screen.getByLabelText(/Model/i), "x/y");
    await user.click(screen.getByRole("button", { name: /Test connection/i }));

    await waitFor(() => expect(screen.getByText(/Connection OK/i)).toBeInTheDocument());

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-LLM-Credentials"]).toBeDefined();
    const decoded = JSON.parse(atob(headers["X-LLM-Credentials"] as string));
    expect(decoded.api_key).toBe("sk-test");
    expect(decoded.model).toBe("x/y");
  });

  it("Test connection surfaces server error detail on non-2xx response", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.mocked(globalThis.fetch);
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: { error: "byok_required", message: "no key" } }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      }),
    );

    render(
      <SettingsModal isOpen={true} onClose={() => {}} required={true} onCredentialsChange={() => {}} />,
    );
    await user.type(screen.getByLabelText(/API key/i, { selector: "input" }), "sk-test");
    await user.type(screen.getByLabelText(/Model/i), "x/y");
    await user.click(screen.getByRole("button", { name: /Test connection/i }));

    await waitFor(() => expect(screen.getByText(/Test failed/i)).toBeInTheDocument());
  });
});
