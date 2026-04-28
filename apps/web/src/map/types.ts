/**
 * Shared map types — backend-agnostic.
 *
 * These types live outside the engines module so app code may import them
 * freely. They describe the data the application speaks; engines translate
 * to and from the underlying library's own types.
 */

export type LatLng = {
  lat: number;
  lng: number;
};

export type Viewport = {
  center: LatLng;
  zoom: number;
  /** Bearing in degrees clockwise from north. */
  bearing?: number;
  /** Pitch in degrees, 0 = top-down. */
  pitch?: number;
};

export type Marker = {
  id: string;
  position: LatLng;
  label?: string;
  icon?: "pin" | "star" | "flag" | "photo";
  color?: string;
};

export type PathStyle = {
  color?: string;
  widthPx?: number;
  dashed?: boolean;
  opacity?: number;
};

export type Unsubscribe = () => void;

/** Engine identifier — read from `VITE_MAP_ENGINE`. */
export type MapEngineKind = "maplibre" | "google-3d";
