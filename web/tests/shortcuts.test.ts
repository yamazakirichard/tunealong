import { describe, expect, it } from "vitest";

import { type Controls, shortcut } from "../src/lib/shortcuts";

const base: Controls = { semitones: 0, tempo: 1, loopOn: false };
const apply = (key: string, s: Controls = base) => shortcut(s, key)!;

describe("shortcut reducer", () => {
  it("] from 1.00 gives 1.05, [ gives 0.95", () => {
    expect(apply("]").state.tempo).toBe(1.05);
    expect(apply("[").state.tempo).toBe(0.95);
  });

  it("clamps tempo to 0.25–2.0", () => {
    expect(apply("]", { ...base, tempo: 2 }).state.tempo).toBe(2);
    expect(apply("]", { ...base, tempo: 1.98 }).state.tempo).toBe(2);
    expect(apply("[", { ...base, tempo: 0.25 }).state.tempo).toBe(0.25);
    expect(apply("[", { ...base, tempo: 0.27 }).state.tempo).toBe(0.25);
  });

  it("repeated steps don't drift", () => {
    let s = base;
    for (let i = 0; i < 5; i++) s = apply("[", s).state;
    expect(s.tempo).toBe(0.75);
  });

  it("- and = change pitch by 1, clamped to ±12", () => {
    expect(apply("=").state.semitones).toBe(1);
    expect(apply("-").state.semitones).toBe(-1);
    expect(apply("=", { ...base, semitones: 12 }).state.semitones).toBe(12);
    expect(apply("-", { ...base, semitones: -12 }).state.semitones).toBe(-12);
    expect(apply("=", { ...base, semitones: 0.5 }).state.semitones).toBe(1.5);
  });

  it("L toggles the loop", () => {
    expect(apply("l").state.loopOn).toBe(true);
    expect(apply("L", { ...base, loopOn: true }).state.loopOn).toBe(false);
  });

  it.each([
    [" ", "toggle-play"],
    ["a", "set-a"],
    ["A", "set-a"],
    ["b", "set-b"],
    ["B", "set-b"],
    ["f", "fullscreen"],
    ["F", "fullscreen"],
  ])("%j → %s, state unchanged", (key, effect) => {
    const r = apply(key);
    expect(r.effect).toBe(effect);
    expect(r.state).toEqual(base);
  });

  it.each([
    ["ArrowLeft", { seekBy: -5 }],
    ["ArrowRight", { seekBy: 5 }],
    ["Home", { seekTo: 0 }],
  ])("%s seeks: %j", (key, effect) => {
    const r = apply(key);
    expect(r.effect).toEqual(effect);
    expect(r.state).toEqual(base);
  });

  it("ignores other keys", () => {
    expect(shortcut(base, "x")).toBeNull();
    expect(shortcut(base, "Enter")).toBeNull();
  });
});
