// Player keyboard shortcuts as a pure reducer, so they can be tested.

export const TEMPO_MIN = 0.25;
export const TEMPO_MAX = 2.0;
export const TEMPO_STEP = 0.05;
export const PITCH_MIN = -12;
export const PITCH_MAX = 12;

export interface Controls {
  semitones: number;
  tempo: number;
  loopOn: boolean;
}

export type Effect = "toggle-play" | "set-a" | "set-b" | "fullscreen" | null;

const round2 = (x: number) => Math.round(x * 100) / 100;
export const clampTempo = (t: number) => round2(Math.min(TEMPO_MAX, Math.max(TEMPO_MIN, t)));
export const clampPitch = (s: number) => round2(Math.min(PITCH_MAX, Math.max(PITCH_MIN, s)));

/** Apply a key to the controls. Returns null for keys that aren't shortcuts. */
export function shortcut(state: Controls, key: string): { state: Controls; effect: Effect } | null {
  switch (key) {
    case " ":
      return { state, effect: "toggle-play" };
    case "[":
      return { state: { ...state, tempo: clampTempo(state.tempo - TEMPO_STEP) }, effect: null };
    case "]":
      return { state: { ...state, tempo: clampTempo(state.tempo + TEMPO_STEP) }, effect: null };
    case "-":
      return { state: { ...state, semitones: clampPitch(state.semitones - 1) }, effect: null };
    case "=":
      return { state: { ...state, semitones: clampPitch(state.semitones + 1) }, effect: null };
    case "a":
    case "A":
      return { state, effect: "set-a" };
    case "b":
    case "B":
      return { state, effect: "set-b" };
    case "l":
    case "L":
      return { state: { ...state, loopOn: !state.loopOn }, effect: null };
    case "f":
    case "F":
      return { state, effect: "fullscreen" };
    default:
      return null;
  }
}
