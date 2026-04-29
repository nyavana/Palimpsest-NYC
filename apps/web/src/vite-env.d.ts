/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_MAP_ENGINE?: "maplibre" | "google-3d";
  readonly VITE_GOOGLE_MAP_TILES_API_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
