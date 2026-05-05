/**
 * `useServerConfig` — fetches GET /config once on mount.
 *
 * The frontend uses this to decide whether to:
 * - require BYOK (auto-open SettingsModal, disable composer until creds), or
 * - treat user-supplied credentials as an optional override.
 *
 * Returns a stable shape with `loading=true` until the fetch resolves.
 * On network failure, surfaces `error` and falls back to a permissive
 * default (byokRequired=false) so a transient backend hiccup doesn't
 * lock out a user with valid env-key deployments.
 */

import { useEffect, useState } from "react";

export type ServerConfig = {
  byok_required: boolean;
  byok_supported: boolean;
  defaults: {
    base_url: string;
    model: string | null;
  };
};

export type UseServerConfigResult = {
  config: ServerConfig | null;
  loading: boolean;
  error: string | null;
};

const DEFAULT_BASE_URL = "/api";

export function useServerConfig(apiBaseUrl: string = DEFAULT_BASE_URL): UseServerConfigResult {
  const [config, setConfig] = useState<ServerConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    (async () => {
      try {
        const resp = await fetch(`${apiBaseUrl}/config`, {
          signal: controller.signal,
          headers: { Accept: "application/json" },
        });
        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}`);
        }
        const body = (await resp.json()) as ServerConfig;
        if (!cancelled) {
          setConfig(body);
          setError(null);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        const message = err instanceof Error ? err.message : "config_fetch_failed";
        setError(message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [apiBaseUrl]);

  return { config, loading, error };
}
