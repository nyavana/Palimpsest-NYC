/**
 * MaplibreEngine — the v1 default.
 *
 * Uses maplibre-gl with an OpenStreetMap raster style tweaked for 3D buildings
 * extruded from the OSM `building:levels` tag. Works entirely on free data and
 * requires no API key. This file is the only place in the codebase allowed to
 * import `maplibre-gl` directly — see eslint.config.mjs.
 */

import maplibregl, {
  LngLatBoundsLike,
  Map as MaplibreMap,
  Marker as MlMarker,
  Popup as MlPopup,
  StyleSpecification,
} from "maplibre-gl";

import { MapEngine, MapEngineLifecycleError } from "../MapEngine";
import type { LatLng, Marker, MarkerEvent, PathStyle, Unsubscribe, Viewport } from "../types";
import { MarkerEventBus } from "./MarkerEventBus";

// A minimal raster style using OSM tiles. Good enough for v1; upgraded later
// to a vector style with extruded buildings.
const BASE_STYLE: StyleSpecification = {
  version: 8,
  glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
      maxzoom: 19,
    },
  },
  layers: [
    {
      id: "osm",
      type: "raster",
      source: "osm",
    },
  ],
};

const PATH_LAYER_PREFIX = "path-";
const MARKER_LAYER_PREFIX = "markers-";

type MarkerLayer = { instances: MlMarker[] };

export class MaplibreEngine implements MapEngine {
  private map: MaplibreMap | null = null;
  private markerLayers = new Map<string, MarkerLayer>();
  private pathLayers = new Set<string>();
  private destroyed = false;
  private events = new MarkerEventBus();
  private popup: MlPopup | null = null;

  async init(container: HTMLElement, initialView: Viewport): Promise<void> {
    if (this.destroyed) {
      throw new MapEngineLifecycleError("MaplibreEngine is destroyed");
    }
    if (this.map !== null) {
      throw new MapEngineLifecycleError("MaplibreEngine already initialized");
    }

    const map = new maplibregl.Map({
      container,
      style: BASE_STYLE,
      center: [initialView.center.lng, initialView.center.lat],
      zoom: initialView.zoom,
      bearing: initialView.bearing ?? 0,
      pitch: initialView.pitch ?? 0,
      attributionControl: { compact: true },
    });

    map.addControl(new maplibregl.NavigationControl({}), "top-right");
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 100, unit: "metric" }), "bottom-left");

    await new Promise<void>((resolve) => {
      const handler = () => {
        map.off("load", handler);
        resolve();
      };
      map.on("load", handler);
    });

    this.map = map;
  }

  setViewport(v: Viewport): void {
    const map = this.requireMap();
    map.jumpTo({
      center: [v.center.lng, v.center.lat],
      zoom: v.zoom,
      bearing: v.bearing ?? 0,
      pitch: v.pitch ?? 0,
    });
  }

  async flyTo(target: Viewport, durationMs = 2000): Promise<void> {
    const map = this.requireMap();
    return new Promise<void>((resolve) => {
      map.once("moveend", () => resolve());
      map.flyTo({
        center: [target.center.lng, target.center.lat],
        zoom: target.zoom,
        bearing: target.bearing ?? 0,
        pitch: target.pitch ?? 0,
        duration: durationMs,
        essential: true,
      });
    });
  }

  addMarkers(layerId: string, markers: Marker[]): void {
    const map = this.requireMap();
    const layerKey = MARKER_LAYER_PREFIX + layerId;
    this.clearMarkers(layerId);
    const instances: MlMarker[] = [];
    for (const m of markers) {
      const el = document.createElement("div");
      el.className = "palimpsest-marker";
      el.style.width = "14px";
      el.style.height = "14px";
      el.style.borderRadius = "50%";
      el.style.background = m.color ?? "#1A1F3A";
      el.style.border = "2px solid #EDF1FD";
      el.style.boxShadow = "0 1px 4px rgba(0,0,0,0.3)";
      el.style.cursor = "pointer";
      if (m.label) {
        el.title = m.label;
      }
      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([m.position.lng, m.position.lat])
        .addTo(map);
      instances.push(marker);
      this.events.attach(layerId, m.id, el, m.position);
    }
    this.markerLayers.set(layerKey, { instances });
  }

  addPath(layerId: string, coords: LatLng[], style: PathStyle = {}): void {
    const map = this.requireMap();
    const sourceId = PATH_LAYER_PREFIX + layerId;
    this.clearPath(layerId);

    map.addSource(sourceId, {
      type: "geojson",
      data: {
        type: "Feature",
        properties: {},
        geometry: {
          type: "LineString",
          coordinates: coords.map((c) => [c.lng, c.lat]),
        },
      },
    });

    map.addLayer({
      id: sourceId,
      type: "line",
      source: sourceId,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": style.color ?? "#1A1F3A",
        "line-width": style.widthPx ?? 4,
        "line-opacity": style.opacity ?? 0.9,
        ...(style.dashed ? { "line-dasharray": [2, 2] } : {}),
      },
    });

    this.pathLayers.add(sourceId);
  }

  clearLayer(layerId: string): void {
    this.clearMarkers(layerId);
    this.clearPath(layerId);
  }

  private clearMarkers(layerId: string): void {
    if (this.map === null) return;
    const markerKey = MARKER_LAYER_PREFIX + layerId;
    const markerLayer = this.markerLayers.get(markerKey);
    if (markerLayer) {
      for (const m of markerLayer.instances) {
        m.remove();
      }
      this.markerLayers.delete(markerKey);
    }
    // Bus listeners were attached on the (now-removed) marker DOM nodes.
    // Maplibre's Marker.remove() detaches the elements from the DOM, but
    // our listeners remain on the orphaned nodes — they'll be garbage
    // collected when nothing else holds them. detachAll on destroy
    // handles the explicit teardown.
  }

  private clearPath(layerId: string): void {
    const map = this.map;
    if (map === null) return;
    const pathKey = PATH_LAYER_PREFIX + layerId;
    if (this.pathLayers.has(pathKey)) {
      if (map.getLayer(pathKey)) {
        map.removeLayer(pathKey);
      }
      if (map.getSource(pathKey)) {
        map.removeSource(pathKey);
      }
      this.pathLayers.delete(pathKey);
    }
  }

  onCameraChange(cb: (v: Viewport) => void): Unsubscribe {
    const map = this.requireMap();
    const handler = () => {
      const center = map.getCenter();
      cb({
        center: { lat: center.lat, lng: center.lng },
        zoom: map.getZoom(),
        bearing: map.getBearing(),
        pitch: map.getPitch(),
      });
    };
    map.on("moveend", handler);
    return () => {
      map.off("moveend", handler);
    };
  }

  onMarkerHover(cb: (e: MarkerEvent | null) => void): Unsubscribe {
    return this.events.onHover(cb);
  }

  onMarkerClick(cb: (e: MarkerEvent) => void): Unsubscribe {
    return this.events.onClick(cb);
  }

  setPopup(at: LatLng, el: HTMLElement, opts?: { offsetPx?: number }): void {
    const map = this.requireMap();
    if (this.popup !== null) {
      this.popup.remove();
      this.popup = null;
    }
    const popup = new maplibregl.Popup({
      closeOnClick: false,
      closeButton: false,
      offset: opts?.offsetPx ?? 14,
      maxWidth: "320px",
    });
    popup.setLngLat([at.lng, at.lat]).setDOMContent(el).addTo(map);
    this.popup = popup;
  }

  clearPopup(): void {
    if (this.popup !== null) {
      this.popup.remove();
      this.popup = null;
    }
  }

  destroy(): void {
    if (this.map !== null) {
      this.events.detachAll();
      this.clearPopup();
      for (const { instances } of this.markerLayers.values()) {
        for (const m of instances) {
          m.remove();
        }
      }
      this.markerLayers.clear();
      this.pathLayers.clear();
      this.map.remove();
      this.map = null;
    }
    this.destroyed = true;
  }

  // --- Internal helpers --------------------------------------------------

  private requireMap(): MaplibreMap {
    if (this.destroyed) {
      throw new MapEngineLifecycleError("MaplibreEngine is destroyed");
    }
    if (this.map === null) {
      throw new MapEngineLifecycleError("MaplibreEngine not yet initialized");
    }
    return this.map;
  }
}

// Re-exports used only to keep the bundler happy; not consumed externally.
export type { LngLatBoundsLike };
