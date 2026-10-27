import { describe, expect, it } from "vitest";

import { completion, suggest, titleCandidates } from "../src/lib/suggest";

const artists = ["Black Sabbath", "Blur", "The Black Keys", "Beyoncé", "AC/DC", "blur"];

describe("suggest", () => {
  it("puts prefix matches before word matches", () => {
    expect(suggest("bla", artists)).toEqual(["Black Sabbath", "The Black Keys"]);
    expect(suggest("sabb", artists)).toEqual(["Black Sabbath"]);
  });

  it("ignores case and accents", () => {
    expect(suggest("BEYO", artists)).toEqual(["Beyoncé"]);
    expect(suggest("beyonce", artists)).toEqual([]); // exact match
  });

  it("splits words on punctuation", () => {
    expect(suggest("dc", artists)).toEqual(["AC/DC"]);
  });

  it("drops duplicates, exact matches and empty queries", () => {
    expect(suggest("b", artists)).toEqual(["Black Sabbath", "Blur", "Beyoncé", "The Black Keys"]);
    expect(suggest("blur", artists)).toEqual([]);
    expect(suggest("  ", artists)).toEqual([]);
  });

  it("caps the list", () => {
    expect(suggest("b", artists, 2)).toEqual(["Black Sabbath", "Blur"]);
  });
});

describe("completion", () => {
  it("returns the untyped rest of a prefix match", () => {
    expect(completion("black s", "Black Sabbath")).toBe("abbath");
    expect(completion("Blac", "Black Sabbath")).toBe("k Sabbath");
  });

  it("is empty for word matches and complete text", () => {
    expect(completion("sabb", "Black Sabbath")).toBe("");
    expect(completion("Blur", "Blur")).toBe("");
    expect(completion("", "Blur")).toBe("");
    expect(completion("x", undefined)).toBe("");
  });
});

describe("titleCandidates", () => {
  const songs = [
    { title: "War Pigs", artist_id: 2 },
    { title: "Paranoid", artist_id: 1 },
    { title: "Loose", artist_id: null },
  ];

  it("lists the artist's songs first", () => {
    expect(titleCandidates(songs, 1)).toEqual(["Paranoid", "War Pigs", "Loose"]);
  });

  it("keeps library order with no artist", () => {
    expect(titleCandidates(songs, undefined)).toEqual(["War Pigs", "Paranoid", "Loose"]);
  });
});
