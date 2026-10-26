"""Render cache keys (and, from Phase 5, garbage collection).

Key: p{semitones:+.2f}_t{tempo:.3f}_bt{bake_tempo}_{engine}-{engine_version}.
When tempo isn't baked it is applied live in the browser, so the key uses
t1.000 and presets that differ only in live tempo share one render.
"""

ENGINE = "rb3"
ENGINE_VERSION = "v1"


def snap(value: float, step: float = 0.01) -> float:
    """Round to `step` so Python and JS format the stored value identically."""
    return round(round(value / step) * step, 2)


def is_identity(semitones: float, tempo: float, bake_tempo: bool) -> bool:
    return snap(semitones) == 0 and (not bake_tempo or snap(tempo) == 1)


def cache_key(semitones: float, tempo: float, bake_tempo: bool) -> str | None:
    """The render key for these settings, or None when no render is needed."""
    if is_identity(semitones, tempo, bake_tempo):
        return None
    s = snap(semitones) + 0.0  # -0.0 -> 0.0, so it formats as +0.00
    t = snap(tempo) if bake_tempo else 1.0
    return f"p{s:+.2f}_t{t:.3f}_bt{int(bool(bake_tempo))}_{ENGINE}-{ENGINE_VERSION}"
