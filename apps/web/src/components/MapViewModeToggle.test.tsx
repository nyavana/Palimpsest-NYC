import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  MapViewModeToggle,
  readSavedViewMode,
  writeSavedViewMode,
  STORAGE_KEY,
} from "./MapViewModeToggle";

beforeEach(() => {
  localStorage.clear();
});

describe("readSavedViewMode", () => {
  it("returns 3d when storage is empty", () => {
    expect(readSavedViewMode()).toBe("3d");
  });

  it("returns 2d when stored as 2d", () => {
    localStorage.setItem(STORAGE_KEY, "2d");
    expect(readSavedViewMode()).toBe("2d");
  });

  it("returns 3d for invalid stored value", () => {
    localStorage.setItem(STORAGE_KEY, "garbage");
    expect(readSavedViewMode()).toBe("3d");
  });

  it("falls back to 3d when localStorage throws", () => {
    const original = globalThis.localStorage;
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      get() {
        throw new Error("private mode");
      },
    });
    try {
      expect(readSavedViewMode()).toBe("3d");
    } finally {
      Object.defineProperty(globalThis, "localStorage", { configurable: true, value: original });
    }
  });
});

describe("writeSavedViewMode", () => {
  it("writes the value to localStorage", () => {
    writeSavedViewMode("2d");
    expect(localStorage.getItem(STORAGE_KEY)).toBe("2d");
  });

  it("does not throw when localStorage is unavailable", () => {
    const original = globalThis.localStorage;
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      get() {
        throw new Error("private mode");
      },
    });
    try {
      expect(() => writeSavedViewMode("3d")).not.toThrow();
    } finally {
      Object.defineProperty(globalThis, "localStorage", { configurable: true, value: original });
    }
  });
});

describe("MapViewModeToggle", () => {
  it("renders both buttons with the active one marked", () => {
    render(<MapViewModeToggle mode="3d" onChange={() => {}} />);

    const btn3d = screen.getByRole("button", { name: /3d/i });
    const btn2d = screen.getByRole("button", { name: /2d/i });
    expect(btn3d).toHaveAttribute("aria-pressed", "true");
    expect(btn2d).toHaveAttribute("aria-pressed", "false");
  });

  it("invokes onChange with the new mode when the inactive button is clicked", async () => {
    const onChange = vi.fn();
    render(<MapViewModeToggle mode="3d" onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: /2d/i }));
    expect(onChange).toHaveBeenCalledWith("2d");
  });

  it("does not invoke onChange when the active button is clicked", async () => {
    const onChange = vi.fn();
    render(<MapViewModeToggle mode="3d" onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: /3d/i }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
