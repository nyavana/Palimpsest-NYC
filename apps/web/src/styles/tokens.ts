/**
 * Palimpsest NYC — design tokens.
 *
 * Source of truth for the visual system. Mirrors `docs/frontend/ui-design-brief.md`.
 * The Tailwind config (`tailwind.config.ts`) extends its theme from these
 * values, so components consume them via Tailwind classes
 * (e.g. `bg-parchment`, `text-ink`, `text-archival-blue`) rather than
 * importing this module directly. The module is exported for the few cases
 * where a value is needed in TS (e.g. inline styles for source-type chips
 * that are dynamic).
 *
 * Token names are legacy from the v1 "parchment & ink" direction. The
 * current palette is the cool "twilight archive" set sourced from
 * `docs/assets/Color.webp`: `parchment` is now pale lavender, `ink` is a
 * deep indigo, `oxblood` is the primary plum, `archival-blue` is royal
 * indigo, and `ochre` carries the bright magenta accent. Names were kept
 * to avoid a 20+ file rename for cosmetic gain.
 */

export const palette = {
  parchment: "#EDF1FD",
  "parchment-deep": "#DDE3F4",
  ink: "#1A1F3A",
  "ink-soft": "#3D4566",
  "ink-muted": "#6A6F8C",
  hairline: "rgba(83, 100, 192, 0.18)",
  oxblood: "#77295D",
  "oxblood-hover": "#5A1E48",
  "archival-blue": "#5364C0",
  "archival-blue-visited": "#6B3380",
  ochre: "#C34FA2",
  success: "#4A8A6E",
} as const;

/** Per-source brand colors for the citation chip. Closed set — V1 contract. */
export const sourceTypeColor = {
  wikipedia: "#3366cc",
  wikidata: "#990000",
  osm: "#7ebc6f",
} as const;

export type SourceType = keyof typeof sourceTypeColor;

export const fontFamily = {
  serif: ['"IBM Plex Serif"', "Georgia", "serif"],
  sans: ['"Inter"', "system-ui", "sans-serif"],
  mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
} as const;

export const fontSize = {
  display: ["1.5rem", { lineHeight: "1.2" }],
  h2: ["1.25rem", { lineHeight: "1.35" }],
  body: ["0.9375rem", { lineHeight: "1.6" }],
  small: ["0.8125rem", { lineHeight: "1.5" }],
  mono: ["0.75rem", { lineHeight: "1.2" }],
} as const;

export const radius = {
  /** Single radius token; the editorial direction is sharp, not pill. */
  DEFAULT: "4px",
} as const;

export const motion = {
  durFast: "120ms",
  durBase: "200ms",
  durSlow: "1200ms",
  easeOut: "cubic-bezier(0.16, 1, 0.3, 1)",
  easeIn: "cubic-bezier(0.7, 0, 0.84, 0)",
} as const;

/** Walking pace used to convert leg distance (m) to minutes. */
export const WALK_MS_PER_STEP = 80; // metres per minute of walking
