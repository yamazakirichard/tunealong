// <video> → MediaElementSource → SoundTouch worklet (pitch only) → gain (volume) → speakers.
//
// A MediaElementSource can be created only once per element, so the player
// mounts a fresh <video> on every open and calls teardown() on close.
// AudioWorklet needs a secure context (HTTPS or localhost); without it the
// video plays directly and only cached renders change the pitch.

import { SoundTouchNode } from "@soundtouchjs/audio-worklet";
import processorUrl from "@soundtouchjs/audio-worklet/processor?url";

export interface Graph {
  ctx: AudioContext | null;
  node: SoundTouchNode | null;
  kind: "worklet" | "direct";
  setPitch: (semitones: number) => void;
  pitch: () => number;
  /** Output gain, 0..2. Without a context it's the element's own volume, which stops at 1. */
  setVolume: (gain: number) => void;
  volume: () => number;
  /** Whether gain above 1 is possible (there's a GainNode). */
  boost: boolean;
  teardown: () => Promise<void>;
}

export const graphErrors: string[] = [];

export async function buildGraph(video: HTMLVideoElement): Promise<Graph> {
  let pitch = 0;
  const direct = (ctx: AudioContext | null = null, gain: GainNode | null = null): Graph => ({
    ctx,
    node: null,
    kind: "direct",
    setPitch: (s) => (pitch = s),
    pitch: () => pitch,
    setVolume: (g) => (gain ? gain.gain.setValueAtTime(g, ctx!.currentTime) : (video.volume = Math.min(g, 1))),
    volume: () => (gain ? gain.gain.value : video.volume),
    boost: gain !== null,
    teardown: async () => {
      await ctx?.close().catch(() => {});
    },
  });

  if (!window.isSecureContext || typeof AudioWorkletNode === "undefined") return direct();

  const ctx = new AudioContext({ latencyHint: "playback" });
  let source: MediaElementAudioSourceNode;
  try {
    source = ctx.createMediaElementSource(video);
  } catch (e) {
    graphErrors.push(`${(e as Error).name}: ${(e as Error).message}`);
    await ctx.close().catch(() => {});
    return direct();
  }
  const gain = ctx.createGain();
  gain.connect(ctx.destination);
  try {
    await SoundTouchNode.register(ctx, processorUrl);
    const node = new SoundTouchNode({ context: ctx });
    source.connect(node);
    node.connect(gain);
    if (ctx.state === "suspended") await ctx.resume().catch(() => {});
    return {
      ctx,
      node,
      kind: "worklet",
      setPitch: (s) => node.pitchSemitones.setValueAtTime(s, ctx.currentTime),
      pitch: () => node.pitchSemitones.value,
      setVolume: (g) => gain.gain.setValueAtTime(g, ctx.currentTime),
      volume: () => gain.gain.value,
      boost: true,
      teardown: async () => {
        source.disconnect();
        node.disconnect();
        gain.disconnect();
        await ctx.close().catch(() => {});
      },
    };
  } catch (e) {
    // The element is already captured by the context, so route it straight out.
    graphErrors.push(`${(e as Error).name}: ${(e as Error).message}`);
    source.connect(gain);
    return direct(ctx, gain);
  }
}
