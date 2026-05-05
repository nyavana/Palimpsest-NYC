/**
 * useWikipediaSummary — lazy fetch a Wikipedia page summary for a doc_id.
 *
 * Slug is taken from the `wikipedia:` prefix; non-wikipedia docs stay
 * `idle`. Concurrent callers share one in-flight Promise via a
 * module-level cache that lives for the page session.
 *
 * The endpoint is the public Wikipedia REST summary API; no key required.
 */

import { useEffect, useRef, useState } from "react";

const PREFIX = "wikipedia:";
const ENDPOINT = "https://en.wikipedia.org/api/rest_v1/page/summary";

export type WikipediaSummary = {
  title: string;
  extract: string;
  thumbnailUrl: string | null;
  pageUrl: string;
};

export type WikipediaFetchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; summary: WikipediaSummary }
  | { status: "error" };

const cache = new Map<string, Promise<WikipediaSummary>>();
const warned = new Set<string>();

export function __resetWikipediaCacheForTests(): void {
  cache.clear();
  warned.clear();
}

function slugFromDocId(docId: string | null): string | null {
  if (docId === null) return null;
  if (!docId.startsWith(PREFIX)) return null;
  const slug = docId.slice(PREFIX.length);
  return slug.length > 0 ? slug : null;
}

async function fetchSummary(slug: string): Promise<WikipediaSummary> {
  const url = `${ENDPOINT}/${encodeURIComponent(slug)}`;
  const response = await fetch(url, {
    headers: {
      Accept:
        'application/json; charset=utf-8; profile="https://www.mediawiki.org/wiki/Specs/Summary/1.4.2"',
    },
  });
  if (!response.ok) {
    throw new Error(`wikipedia summary HTTP ${response.status}`);
  }
  const body = (await response.json()) as {
    title?: string;
    extract?: string;
    thumbnail?: { source?: string };
    content_urls?: { desktop?: { page?: string } };
  };
  return {
    title: body.title ?? slug.replace(/_/g, " "),
    extract: body.extract ?? "",
    thumbnailUrl: body.thumbnail?.source ?? null,
    pageUrl: body.content_urls?.desktop?.page ?? `https://en.wikipedia.org/wiki/${encodeURIComponent(slug)}`,
  };
}

function getOrFetch(docId: string, slug: string): Promise<WikipediaSummary> {
  const existing = cache.get(docId);
  if (existing) return existing;
  const inFlight = fetchSummary(slug).catch((err) => {
    cache.delete(docId);
    if (!warned.has(docId)) {
      warned.add(docId);
      // eslint-disable-next-line no-console
      console.warn(`[wikipedia-summary] failed for ${docId}:`, err);
    }
    throw err;
  });
  cache.set(docId, inFlight);
  return inFlight;
}

export function useWikipediaSummary(docId: string | null): WikipediaFetchState {
  const [state, setState] = useState<WikipediaFetchState>({ status: "idle" });
  const abortedRef = useRef(false);

  useEffect(() => {
    abortedRef.current = false;
    const slug = slugFromDocId(docId);
    if (slug === null || docId === null) {
      setState({ status: "idle" });
      return;
    }

    setState({ status: "loading" });
    getOrFetch(docId, slug).then(
      (summary) => {
        if (abortedRef.current) return;
        setState({ status: "success", summary });
      },
      () => {
        if (abortedRef.current) return;
        setState({ status: "error" });
      },
    );

    return () => {
      abortedRef.current = true;
    };
  }, [docId]);

  return state;
}
