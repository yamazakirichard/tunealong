import { describe, expect, it } from "vitest";

import table from "../../fixtures/cache_keys.json";
import { cacheKey, ENGINE, ENGINE_VERSION, snap } from "../src/lib/cacheKey";

describe("cacheKey", () => {
  it("uses the backend's engine and version", () => {
    expect([ENGINE, ENGINE_VERSION]).toEqual([table.engine, table.engine_version]);
  });

  it.each(table.cases)("$semitones st / $tempo× / bake=$bake_tempo → $key", (c) => {
    expect(cacheKey(c.semitones, c.tempo, c.bake_tempo)).toBe(c.key);
  });

  it("snaps to 0.01 and normalises -0", () => {
    expect(snap(0.8333)).toBe(0.83);
    expect(Object.is(snap(-0), 0)).toBe(true);
    expect(Object.is(snap(-0.001), 0)).toBe(true);
  });
});
