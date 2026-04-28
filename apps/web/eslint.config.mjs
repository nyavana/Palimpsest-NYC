// ESLint flat config for Palimpsest web.
//
// Critical rule: no-restricted-imports blocks direct `maplibre-gl` imports
// from anywhere outside `src/map/engines/`. This enforces the MapEngine
// abstraction from the map-engine capability spec and preserves the v2
// upgrade path to Google Photorealistic 3D Tiles.

import js from "@eslint/js";
import tseslint from "@typescript-eslint/eslint-plugin";
import tsparser from "@typescript-eslint/parser";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";

export default [
  { ignores: ["dist", "node_modules", ".vite"] },
  {
    ...js.configs.recommended,
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      parser: tsparser,
      ecmaVersion: 2022,
      sourceType: "module",
      globals: {
        window: "readonly",
        document: "readonly",
        console: "readonly",
        process: "readonly",
        HTMLElement: "readonly",
        HTMLDivElement: "readonly",
      },
    },
    plugins: {
      "@typescript-eslint": tseslint,
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...tseslint.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
      // MapEngine abstraction guard — see specs/map-engine/spec.md
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "maplibre-gl",
              message:
                "Import MapEngine from '@/map' instead. Only files under\nsrc/map/engines/ may import maplibre-gl directly.",
            },
          ],
        },
      ],
    },
  },
  {
    // Relax the rule inside the engines module itself
    files: ["src/map/engines/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": "off",
    },
  },
];