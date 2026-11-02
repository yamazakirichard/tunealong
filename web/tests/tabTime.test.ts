import { describe, expect, it } from "vitest";

import { songToSynth, synthToSong } from "../src/lib/tabTime";

describe("tab time", () => {
  it("is the identity at speed 1", () => {
    expect(synthToSong(4000, 1)).toBe(4);
    expect(songToSynth(4, 1)).toBe(4000);
  });

  it("maps a slowed-down synth back onto the song's own timeline", () => {
    // A 4 s song at 0.73 ends at 5479 ms of playback.
    expect(synthToSong(4000 / 0.73, 0.73)).toBeCloseTo(4, 9);
    expect(songToSynth(4, 0.73)).toBeCloseTo(4000 / 0.73, 9);
  });

  it("round-trips at any speed", () => {
    for (const speed of [0.25, 0.5, 0.73, 1, 1.5, 2]) {
      for (const t of [0, 0.1, 1.25, 3.999]) expect(synthToSong(songToSynth(t, speed), speed)).toBeCloseTo(t, 9);
    }
  });

  it("never seeks before the start", () => {
    expect(songToSynth(-1, 1)).toBe(0);
  });
});
