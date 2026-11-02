import { describe, expect, it } from "vitest";

import { pickMimeType } from "../src/lib/tabRecorder";

describe("pickMimeType", () => {
  it("prefers VP9, then VP8, then any WebM", () => {
    expect(pickMimeType(() => true)).toBe("video/webm;codecs=vp9,opus");
    expect(pickMimeType((t) => !t.includes("vp9"))).toBe("video/webm;codecs=vp8,opus");
    expect(pickMimeType((t) => t === "video/webm")).toBe("video/webm");
  });

  it("is null when WebM can't be recorded (Safari records MP4 only)", () => {
    expect(pickMimeType(() => false)).toBeNull();
  });
});
