/**
 * Per-browser-session storage for the user's LLM credentials.
 *
 * Lives in `sessionStorage` so the key is wiped when the tab/window
 * closes — switching browsers or devices forces re-entry, which is the
 * BYOK contract. Never use `localStorage` here: a key persisted to disk
 * survives across visits and would silently bill the original user.
 *
 * The credentials are sent to the API as the `X-LLM-Credentials` request
 * header, base64-encoded JSON. Headers (not query strings or bodies)
 * keep the key out of nginx access logs and browser history.
 */

const STORAGE_KEY = "palimpsest.llm.credentials";

export type LlmCredentials = {
  api_key: string;
  model: string;
  base_url?: string;
};

function isStringField(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isCredentialsShape(value: unknown): value is LlmCredentials {
  if (typeof value !== "object" || value === null) return false;
  const obj = value as Record<string, unknown>;
  if (!isStringField(obj.api_key)) return false;
  if (!isStringField(obj.model)) return false;
  if ("base_url" in obj && obj.base_url !== undefined && !isStringField(obj.base_url)) {
    return false;
  }
  return true;
}

export function readSavedCredentials(): LlmCredentials | null {
  try {
    const raw = globalThis.sessionStorage?.getItem(STORAGE_KEY);
    if (raw === null || raw === undefined) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (!isCredentialsShape(parsed)) {
      // Corrupt or stale shape — drop it so the UI can re-prompt cleanly.
      globalThis.sessionStorage?.removeItem(STORAGE_KEY);
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function writeSavedCredentials(creds: LlmCredentials): void {
  try {
    const payload: LlmCredentials = {
      api_key: creds.api_key,
      model: creds.model,
      ...(creds.base_url !== undefined && creds.base_url !== ""
        ? { base_url: creds.base_url }
        : {}),
    };
    globalThis.sessionStorage?.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // Ignore — sessionStorage may be unavailable (private mode).
  }
}

export function clearSavedCredentials(): void {
  try {
    globalThis.sessionStorage?.removeItem(STORAGE_KEY);
  } catch {
    // Ignore.
  }
}

/**
 * Encode credentials for the X-LLM-Credentials request header.
 * The header carries base64(JSON(...)) so the value survives byte-level
 * transport without escaping concerns.
 */
export function encodeCredentialsHeader(creds: LlmCredentials): string {
  const payload: LlmCredentials = {
    api_key: creds.api_key,
    model: creds.model,
    ...(creds.base_url !== undefined && creds.base_url !== ""
      ? { base_url: creds.base_url }
      : {}),
  };
  const json = JSON.stringify(payload);
  if (typeof btoa === "function") {
    // btoa needs binary-safe input; UTF-8 strings are fine for our shape
    // (API keys, model IDs, URLs are all ASCII).
    return btoa(json);
  }
  // Node fallback for tests — globalThis.Buffer is available under jsdom.
  const buffer = (globalThis as { Buffer?: { from: (s: string) => { toString: (e: string) => string } } }).Buffer;
  if (buffer !== undefined) {
    return buffer.from(json).toString("base64");
  }
  throw new Error("base64 encoder unavailable");
}

export const _STORAGE_KEY_FOR_TESTS = STORAGE_KEY;
