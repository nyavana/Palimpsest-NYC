import type { Config } from "tailwindcss";

import { fontFamily, fontSize, motion, palette, radius } from "./src/styles/tokens";

/**
 * Palimpsest NYC Tailwind theme.
 *
 * The values come from `src/styles/tokens.ts` so the brief in
 * `docs/frontend/ui-design-brief.md` and the runtime CSS stay in lockstep.
 * Components consume these via classes (e.g. `bg-parchment`, `text-ink`,
 * `font-serif text-display`) rather than importing tokens.ts directly.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        serif: [...fontFamily.serif],
        sans: [...fontFamily.sans],
        mono: [...fontFamily.mono],
      },
      colors: {
        ...palette,
        // Source-type chips read their color from inline styles
        // (because the value is data-driven), so we only expose the palette
        // tokens that are spelled in classnames.
      },
      fontSize: {
        display: fontSize.display as unknown as [string, { lineHeight: string }],
        h2: fontSize.h2 as unknown as [string, { lineHeight: string }],
        body: fontSize.body as unknown as [string, { lineHeight: string }],
        small: fontSize.small as unknown as [string, { lineHeight: string }],
        mono: fontSize.mono as unknown as [string, { lineHeight: string }],
      },
      borderRadius: {
        DEFAULT: radius.DEFAULT,
        sm: radius.DEFAULT,
        md: radius.DEFAULT,
        lg: radius.DEFAULT,
      },
      transitionDuration: {
        fast: motion.durFast,
        base: motion.durBase,
        slow: motion.durSlow,
      },
      transitionTimingFunction: {
        out: motion.easeOut,
        in: motion.easeIn,
      },
      maxWidth: {
        prose: "60ch",
      },
      boxShadow: {
        // The map's floating header is the only place a shadow is allowed.
        chip: "0 1px 8px rgba(0, 0, 0, 0.12)",
      },
    },
  },
  plugins: [],
} satisfies Config;
