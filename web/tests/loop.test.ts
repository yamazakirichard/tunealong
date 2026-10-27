import { describe, expect, it } from "vitest";

import { loopSeek, mapPosition, toMedia, toOriginal } from "../src/lib/loop";

describe("loop", () => {
  it("seeks back to A when t passes B", () => {
    expect(loopSeek(4.01, 2, 4)).toBe(2);
    expect(loopSeek(3.99, 2, 4)).toBeNull();
    expect(loopSeek(4, 2, 4)).toBe(2);
  });

  it("jumps forward to A from before it", () => {
    expect(loopSeek(0, 2, 4)).toBe(2);
    expect(loopSeek(1.9, 2, 4)).toBe(2);
    expect(loopSeek(1.97, 2, 4)).toBeNull(); // within the slack
    expect(loopSeek(2, 2, 4)).toBeNull();
    expect(loopSeek(0, 2, 4, 2)).toBe(4);
  });

  it("scales loop points on a baked render", () => {
    expect(loopSeek(8.01, 2, 4, 2)).toBe(4);
    expect(loopSeek(7.99, 2, 4, 2)).toBeNull();
  });

  it("does nothing without both points", () => {
    expect(loopSeek(10, null, 4)).toBeNull();
    expect(loopSeek(10, 2, null)).toBeNull();
    expect(loopSeek(10, 4, 2)).toBeNull();
  });
});

describe("position mapping", () => {
  it("original t=3 → baked render at tempo 0.5 (time_scale 2) t=6", () => {
    expect(mapPosition(3, 1, 2)).toBe(6);
    expect(toMedia(3, 1 / 0.5)).toBe(6);
  });

  it("back from the render to the original", () => {
    expect(mapPosition(6, 2, 1)).toBe(3);
    expect(toOriginal(6, 2)).toBe(3);
  });
});
