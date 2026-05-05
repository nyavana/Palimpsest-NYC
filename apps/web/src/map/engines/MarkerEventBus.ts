/**
 * MarkerEventBus — DOM-only helper for marker hover/click events.
 *
 * Lives in `engines/` because it's an implementation detail of
 * `MaplibreEngine.addMarkers`. Pulled out as its own helper so the event
 * logic (especially the hover state machine) can be unit-tested in JSDOM
 * without instantiating a real maplibre map.
 */

import type { LatLng, MarkerEvent, Unsubscribe } from "../types";

type AttachedMarker = {
  layerId: string;
  markerId: string;
  el: HTMLElement;
  at: LatLng;
  cleanup: () => void;
};

export class MarkerEventBus {
  private markers = new Map<string, AttachedMarker>();
  private hovered: { layerId: string; markerId: string } | null = null;
  private hoverCbs = new Set<(e: MarkerEvent | null) => void>();
  private clickCbs = new Set<(e: MarkerEvent) => void>();

  attach(layerId: string, markerId: string, el: HTMLElement, at: LatLng): void {
    const key = this.keyOf(layerId, markerId);
    this.detach(key);

    const onEnter = () => {
      // Fire only if this is a new marker focus (suppress duplicate enters).
      if (this.hovered?.layerId === layerId && this.hovered.markerId === markerId) {
        return;
      }
      this.hovered = { layerId, markerId };
      this.emitHover({ layerId, markerId, at });
    };
    const onLeave = () => {
      if (this.hovered?.layerId === layerId && this.hovered.markerId === markerId) {
        this.hovered = null;
        this.emitHover(null);
      }
      // Otherwise a different marker has already taken focus — no-op.
    };
    const onClick = () => {
      this.emitClick({ layerId, markerId, at });
    };

    el.addEventListener("mouseenter", onEnter);
    el.addEventListener("mouseleave", onLeave);
    el.addEventListener("click", onClick);

    this.markers.set(key, {
      layerId,
      markerId,
      el,
      at,
      cleanup: () => {
        el.removeEventListener("mouseenter", onEnter);
        el.removeEventListener("mouseleave", onLeave);
        el.removeEventListener("click", onClick);
      },
    });
  }

  detachAll(): void {
    for (const m of this.markers.values()) {
      m.cleanup();
    }
    this.markers.clear();
    if (this.hovered !== null) {
      this.hovered = null;
      this.emitHover(null);
    }
  }

  onHover(cb: (e: MarkerEvent | null) => void): Unsubscribe {
    this.hoverCbs.add(cb);
    return () => {
      this.hoverCbs.delete(cb);
    };
  }

  onClick(cb: (e: MarkerEvent) => void): Unsubscribe {
    this.clickCbs.add(cb);
    return () => {
      this.clickCbs.delete(cb);
    };
  }

  private detach(key: string): void {
    const existing = this.markers.get(key);
    if (existing) {
      existing.cleanup();
      this.markers.delete(key);
    }
  }

  private keyOf(layerId: string, markerId: string): string {
    return `${layerId} ${markerId}`;
  }

  private emitHover(e: MarkerEvent | null): void {
    for (const cb of this.hoverCbs) {
      cb(e);
    }
  }

  private emitClick(e: MarkerEvent): void {
    for (const cb of this.clickCbs) {
      cb(e);
    }
  }
}
