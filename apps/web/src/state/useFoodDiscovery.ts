import { useCallback, useMemo, useState } from "react";

import type { FoodCandidate } from "./types";

const FOOD_QUERY_RE =
  /\b(eat|food|hungry|lunch|dinner|breakfast|brunch|coffee|cafe|restaurant|ramen|pizza|sushi|burger|dumpling|dumplings|dessert|bakery|bar|pub)\b/i;

type FoodDiscoveryStatus = "idle" | "loading" | "ready" | "error";

type SearchFoodArgs = {
  query: string;
  near?: [number, number];
  radiusM?: number;
  limit?: number;
};

type FoodDiscoveryResponse = {
  query: string;
  results: FoodCandidate[];
};

export type FoodDiscoveryState = {
  query: string | null;
  status: FoodDiscoveryStatus;
  results: FoodCandidate[];
  error: string | null;
};

export type UseFoodDiscovery = {
  state: FoodDiscoveryState;
  search: (args: SearchFoodArgs) => Promise<void>;
  clear: () => void;
  hasResults: boolean;
};

const initialState: FoodDiscoveryState = {
  query: null,
  status: "idle",
  results: [],
  error: null,
};

export function looksLikeFoodQuery(query: string): boolean {
  return FOOD_QUERY_RE.test(query);
}

export function useFoodDiscovery(baseUrl = "/api"): UseFoodDiscovery {
  const [state, setState] = useState<FoodDiscoveryState>(initialState);

  const clear = useCallback(() => {
    setState(initialState);
  }, []);

  const search = useCallback(
    async ({ query, near, radiusM = 1200, limit = 5 }: SearchFoodArgs) => {
      const trimmed = query.trim();
      if (trimmed.length === 0) return;

      setState({
        query: trimmed,
        status: "loading",
        results: [],
        error: null,
      });

      try {
        const resp = await fetch(`${baseUrl}/food/discover`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
          },
          body: JSON.stringify({
            query: trimmed,
            ...(near !== undefined ? { near } : {}),
            radius_m: radiusM,
            limit,
          }),
        });

        if (!resp.ok) {
          throw new Error(`food discovery failed (${resp.status})`);
        }

        const payload = (await resp.json()) as FoodDiscoveryResponse;
        setState({
          query: payload.query,
          status: "ready",
          results: payload.results,
          error: null,
        });
      } catch (err) {
        setState({
          query: trimmed,
          status: "error",
          results: [],
          error: err instanceof Error ? err.message : "food discovery failed",
        });
      }
    },
    [baseUrl],
  );

  const hasResults = useMemo(
    () => state.status === "ready" && state.results.length > 0,
    [state.results.length, state.status],
  );

  return { state, search, clear, hasResults };
}
