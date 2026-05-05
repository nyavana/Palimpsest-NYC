/**
 * SettingsModal — bring-your-own-key form.
 *
 * Plain Tailwind dialog (no headless-ui dependency). Captures the
 * user's API key, model, and optional base URL into sessionStorage.
 * Includes a "Test connection" button that exercises the configured
 * credentials end-to-end against a real /agent/ask call (single SSE
 * frame, then aborted) so misconfigurations surface before a real query.
 *
 * The key never leaves the browser except over the X-LLM-Credentials
 * header, never goes to localStorage (sessionStorage is the contract),
 * and never reaches console.log paths.
 */

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import {
  clearSavedCredentials,
  encodeCredentialsHeader,
  readSavedCredentials,
  writeSavedCredentials,
  type LlmCredentials,
} from "@/state/llmCredentials";

import { AlertTriangleIcon, CheckIcon, EyeIcon, EyeOffIcon, SpinnerIcon } from "./Icon";

const DEFAULT_BASE_URL = "https://openrouter.ai/api/v1";
const TEST_TIMEOUT_MS = 10_000;

type Props = {
  isOpen: boolean;
  onClose: () => void;
  /** When true, the user cannot dismiss the modal until they save creds. */
  required: boolean;
  /** Server-suggested defaults for placeholders. */
  defaults?: { base_url?: string; model?: string | null };
  /** Called after credentials are saved (or cleared) so the parent can refresh. */
  onCredentialsChange: (creds: LlmCredentials | null) => void;
  /** API base URL the test-connection button should hit (defaults to /api). */
  apiBaseUrl?: string;
};

type TestStatus =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "ok" }
  | { kind: "error"; message: string };

export function SettingsModal({
  isOpen,
  onClose,
  required,
  defaults,
  onCredentialsChange,
  apiBaseUrl = "/api",
}: Props) {
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [testStatus, setTestStatus] = useState<TestStatus>({ kind: "idle" });
  const dialogRef = useRef<HTMLDivElement | null>(null);

  // Hydrate form fields from sessionStorage when the modal opens.
  useEffect(() => {
    if (!isOpen) return;
    const saved = readSavedCredentials();
    setApiKey(saved?.api_key ?? "");
    setModel(saved?.model ?? "");
    setBaseUrl(saved?.base_url ?? "");
    setShowKey(false);
    setTestStatus({ kind: "idle" });
  }, [isOpen]);

  // Esc to close — but only if not required.
  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape" && !required) {
      e.preventDefault();
      onClose();
    }
  };

  if (!isOpen) return null;

  const trimmedKey = apiKey.trim();
  const trimmedModel = model.trim();
  const trimmedBaseUrl = baseUrl.trim();
  const formValid = trimmedKey.length > 0 && trimmedModel.length > 0;

  const buildCreds = (): LlmCredentials => ({
    api_key: trimmedKey,
    model: trimmedModel,
    ...(trimmedBaseUrl.length > 0 ? { base_url: trimmedBaseUrl } : {}),
  });

  const handleSave = (e: FormEvent) => {
    e.preventDefault();
    if (!formValid) return;
    const creds = buildCreds();
    writeSavedCredentials(creds);
    onCredentialsChange(creds);
    onClose();
  };

  const handleClear = () => {
    clearSavedCredentials();
    setApiKey("");
    setModel("");
    setBaseUrl("");
    setTestStatus({ kind: "idle" });
    onCredentialsChange(null);
  };

  const handleTest = async () => {
    if (!formValid) return;
    setTestStatus({ kind: "running" });
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), TEST_TIMEOUT_MS);
    try {
      const resp = await fetch(`${apiBaseUrl}/agent/ask`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
          "X-LLM-Credentials": encodeCredentialsHeader(buildCreds()),
        },
        body: JSON.stringify({ q: "Say 'ok'." }),
        signal: controller.signal,
      });
      if (!resp.ok) {
        let detail: string | undefined;
        try {
          const body = (await resp.json()) as { detail?: { error?: string; message?: string } };
          detail = body.detail?.message ?? body.detail?.error;
        } catch {
          detail = undefined;
        }
        setTestStatus({
          kind: "error",
          message: `${resp.status} ${resp.statusText}${detail ? ` — ${detail}` : ""}`,
        });
        return;
      }
      // Read just enough bytes to confirm the stream opened cleanly, then bail.
      const reader = resp.body?.getReader();
      if (reader) {
        await reader.read();
        controller.abort();
      }
      setTestStatus({ kind: "ok" });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        // Either our intentional bail after a frame, or the timeout.
        setTestStatus((prev) => (prev.kind === "running" ? { kind: "error", message: "Timed out." } : prev));
        return;
      }
      const message = err instanceof Error ? err.message : "test_failed";
      setTestStatus({ kind: "error", message });
    } finally {
      clearTimeout(timeout);
    }
  };

  const baseUrlPlaceholder = defaults?.base_url ?? DEFAULT_BASE_URL;
  const modelPlaceholder = defaults?.model ?? "openai/gpt-5.4-mini";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 px-4 py-8 backdrop-blur-sm"
      onKeyDown={handleKeyDown}
      onClick={(e) => {
        if (e.target === e.currentTarget && !required) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        className="w-full max-w-md rounded-lg border border-hairline bg-parchment shadow-xl"
      >
        <div className="border-b border-hairline px-5 py-4">
          <h2 id="settings-title" className="font-serif text-h2 font-semibold text-ink">
            LLM Settings
          </h2>
          <p className="mt-1 text-small text-ink-muted">
            Your API key is stored only for this browser session. Closing the tab clears it.
          </p>
        </div>

        <form className="space-y-4 px-5 py-4" onSubmit={handleSave}>
          <Field label="API key" htmlFor="settings-api-key" required>
            <div className="relative">
              <input
                id="settings-api-key"
                type={showKey ? "text" : "password"}
                autoComplete="off"
                spellCheck={false}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-or-v1-..."
                className="w-full rounded border border-hairline bg-parchment px-3 py-2 pr-10 font-mono text-mono text-ink placeholder:text-ink-muted focus:border-ink/30 focus:outline-none focus:ring-2 focus:ring-ink/40"
              />
              <button
                type="button"
                aria-label={showKey ? "Hide API key" : "Show API key"}
                aria-pressed={showKey}
                onClick={() => setShowKey((v) => !v)}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-ink-muted hover:text-ink focus:outline-none focus:ring-2 focus:ring-ink/40"
              >
                {showKey ? <EyeOffIcon className="text-base" /> : <EyeIcon className="text-base" />}
              </button>
            </div>
          </Field>

          <Field label="Model" htmlFor="settings-model" required>
            <input
              id="settings-model"
              type="text"
              autoComplete="off"
              spellCheck={false}
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={modelPlaceholder}
              className="w-full rounded border border-hairline bg-parchment px-3 py-2 font-mono text-mono text-ink placeholder:text-ink-muted focus:border-ink/30 focus:outline-none focus:ring-2 focus:ring-ink/40"
            />
          </Field>

          <Field label="Base URL (optional)" htmlFor="settings-base-url">
            <input
              id="settings-base-url"
              type="text"
              autoComplete="off"
              spellCheck={false}
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={baseUrlPlaceholder}
              className="w-full rounded border border-hairline bg-parchment px-3 py-2 font-mono text-mono text-ink placeholder:text-ink-muted focus:border-ink/30 focus:outline-none focus:ring-2 focus:ring-ink/40"
            />
            <p className="mt-1 text-small text-ink-muted">
              For OpenAI-compatible endpoints (OpenRouter, local proxy, custom gateway).
            </p>
          </Field>

          <TestStatusLine status={testStatus} />

          <div className="flex flex-wrap items-center gap-2 pt-2">
            <button
              type="submit"
              disabled={!formValid}
              className="flex h-10 items-center gap-1.5 rounded bg-oxblood px-4 text-small font-medium text-parchment transition-colors hover:bg-oxblood-hover disabled:bg-ink-soft disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-ink/40 focus:ring-offset-2 focus:ring-offset-parchment"
            >
              Save
            </button>
            <button
              type="button"
              disabled={!formValid || testStatus.kind === "running"}
              onClick={handleTest}
              className="flex h-10 items-center gap-1.5 rounded border border-hairline bg-parchment px-4 text-small font-medium text-ink hover:bg-parchment-deep disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-ink/40"
            >
              {testStatus.kind === "running" ? <SpinnerIcon className="text-base" /> : null}
              Test connection
            </button>
            <span className="flex-1" />
            <button
              type="button"
              onClick={handleClear}
              className="flex h-10 items-center gap-1.5 rounded px-3 text-small text-ink-muted hover:text-ink focus:outline-none focus:ring-2 focus:ring-ink/40"
            >
              Clear
            </button>
            {!required ? (
              <button
                type="button"
                onClick={onClose}
                className="flex h-10 items-center gap-1.5 rounded px-3 text-small text-ink hover:bg-parchment-deep focus:outline-none focus:ring-2 focus:ring-ink/40"
              >
                Cancel
              </button>
            ) : null}
          </div>
        </form>
      </div>
    </div>
  );
}

function Field({
  label,
  htmlFor,
  required,
  children,
}: {
  label: string;
  htmlFor: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="mb-1 block text-small font-medium text-ink">
        {label}
        {required ? <span className="ml-1 text-oxblood">*</span> : null}
      </label>
      {children}
    </div>
  );
}

function TestStatusLine({ status }: { status: TestStatus }) {
  if (status.kind === "idle") return null;
  if (status.kind === "running") {
    return (
      <p className="flex items-center gap-1.5 text-small text-ink-muted">
        <SpinnerIcon className="text-base" /> Testing connection…
      </p>
    );
  }
  if (status.kind === "ok") {
    return (
      <p className="flex items-center gap-1.5 text-small text-emerald-700">
        <CheckIcon className="text-base" /> Connection OK.
      </p>
    );
  }
  return (
    <p className="flex items-start gap-1.5 text-small text-oxblood">
      <AlertTriangleIcon className="mt-0.5 text-base" />
      <span>Test failed: {status.message}</span>
    </p>
  );
}
