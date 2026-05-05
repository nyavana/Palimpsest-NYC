import { describe, it, expect, vi } from "vitest";

import { MarkerEventBus } from "./MarkerEventBus";

function makeEl(): HTMLDivElement {
  return document.createElement("div");
}

describe("MarkerEventBus", () => {
  it("emits a click event with layerId, markerId, and at", () => {
    const bus = new MarkerEventBus();
    const onClick = vi.fn();
    bus.onClick(onClick);

    const el = makeEl();
    bus.attach("walk", "stop-0", el, { lat: 40.8, lng: -73.9 });
    el.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    expect(onClick).toHaveBeenCalledWith({
      layerId: "walk",
      markerId: "stop-0",
      at: { lat: 40.8, lng: -73.9 },
    });
  });

  it("emits hover events with the active marker, and null on leave", () => {
    const bus = new MarkerEventBus();
    const onHover = vi.fn();
    bus.onHover(onHover);

    const el = makeEl();
    bus.attach("walk", "stop-0", el, { lat: 1, lng: 2 });
    el.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
    el.dispatchEvent(new MouseEvent("mouseleave", { bubbles: true }));

    expect(onHover).toHaveBeenNthCalledWith(1, {
      layerId: "walk",
      markerId: "stop-0",
      at: { lat: 1, lng: 2 },
    });
    expect(onHover).toHaveBeenNthCalledWith(2, null);
  });

  it("emits one new hover event when moving from marker A to marker B", () => {
    const bus = new MarkerEventBus();
    const onHover = vi.fn();
    bus.onHover(onHover);

    const a = makeEl();
    const b = makeEl();
    bus.attach("walk", "a", a, { lat: 0, lng: 0 });
    bus.attach("walk", "b", b, { lat: 1, lng: 1 });

    a.dispatchEvent(new MouseEvent("mouseenter"));
    b.dispatchEvent(new MouseEvent("mouseenter"));
    a.dispatchEvent(new MouseEvent("mouseleave"));

    // Expect: A enter (hover=A), B enter (hover=B; A.leave is implicit), A.leave is no-op.
    expect(onHover).toHaveBeenCalledTimes(2);
    expect(onHover.mock.calls[0][0]).toEqual({ layerId: "walk", markerId: "a", at: { lat: 0, lng: 0 } });
    expect(onHover.mock.calls[1][0]).toEqual({ layerId: "walk", markerId: "b", at: { lat: 1, lng: 1 } });
  });

  it("detachAll removes all listeners and resets hover state", () => {
    const bus = new MarkerEventBus();
    const onHover = vi.fn();
    const onClick = vi.fn();
    bus.onHover(onHover);
    bus.onClick(onClick);

    const el = makeEl();
    bus.attach("walk", "stop-0", el, { lat: 0, lng: 0 });
    bus.detachAll();
    el.dispatchEvent(new MouseEvent("mouseenter"));
    el.dispatchEvent(new MouseEvent("click"));

    expect(onHover).not.toHaveBeenCalled();
    expect(onClick).not.toHaveBeenCalled();
  });

  it("unsubscribe stops calls", () => {
    const bus = new MarkerEventBus();
    const onClick = vi.fn();
    const off = bus.onClick(onClick);

    const el = makeEl();
    bus.attach("walk", "stop-0", el, { lat: 0, lng: 0 });
    off();
    el.dispatchEvent(new MouseEvent("click"));

    expect(onClick).not.toHaveBeenCalled();
  });
});
