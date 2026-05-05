import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

// Node 25 ships an experimental built-in `localStorage` that shadows jsdom's
// implementation but lacks the standard Storage methods (clear/setItem/etc.).
// Install a minimal in-memory Storage shim so tests have a working API.
class MemoryStorage implements Storage {
  private store = new Map<string, string>();
  get length(): number {
    return this.store.size;
  }
  clear(): void {
    this.store.clear();
  }
  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) as string) : null;
  }
  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
  removeItem(key: string): void {
    this.store.delete(key);
  }
  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }
}

if (typeof globalThis.localStorage?.clear !== "function") {
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    writable: true,
    value: new MemoryStorage(),
  });
}

if (typeof globalThis.sessionStorage?.clear !== "function") {
  Object.defineProperty(globalThis, "sessionStorage", {
    configurable: true,
    writable: true,
    value: new MemoryStorage(),
  });
}

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  vi.restoreAllMocks();
});
