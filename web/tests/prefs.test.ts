import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { load, save } from "../src/lib/prefs";

function fakeStorage() {
  const m = new Map<string, string>();
  return {
    map: m,
    getItem: (k: string) => (m.has(k) ? m.get(k)! : null),
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
  };
}

describe("prefs carry over from the Songbook name", () => {
  let store: ReturnType<typeof fakeStorage>;
  beforeEach(() => {
    store = fakeStorage();
    vi.stubGlobal("window", { localStorage: store });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("moves a songbook.* pref to tunealong.* on first read", () => {
    store.setItem("songbook.volume", "0.4");
    expect(load("volume", 1)).toBe(0.4);
    expect(store.map.has("songbook.volume")).toBe(false);
    expect(store.getItem("tunealong.volume")).toBe("0.4");
  });

  it("keeps a newer tunealong.* pref over the legacy one", () => {
    store.setItem("songbook.volume", "0.4");
    save("volume", 0.8);
    expect(load("volume", 1)).toBe(0.8);
    expect(store.map.has("songbook.volume")).toBe(false);
  });

  it("falls back when nothing is stored", () => {
    expect(load("groupBy", "artist")).toBe("artist");
  });
});
