"""Offline renders: ffmpeg extract → rubberband (R3) → ffmpeg remux.

Rubber Band does both pitch (-p) and tempo (-T). The video is never
re-encoded: for a tempo change its packets are copied and only their
timestamps rescaled (the `setts` bitstream filter), so every frame stays
bit-identical and a retimed render is as fast as a pitch-only one.

Every path handed to ffmpeg/rubberband is absolute: YouTube IDs can start
with `-`, which a relative path would turn into an option.

Output goes to renders/<song_id>/.<key>.tmp.<ext> and is renamed into place,
so a partial file is never visible under its final name.
"""

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# original extension → (output extension, ffmpeg muxer, audio encoder args)
_OPUS = ["-c:a", "libopus", "-b:a", "160k"]
_AAC = ["-c:a", "aac", "-b:a", "192k"]
FORMATS = {
    "webm": ("webm", "webm", _OPUS),
    "mp4": ("mp4", "mp4", _AAC),
    "mkv": ("mkv", "matroska", _OPUS),
    "mp3": ("m4a", "ipod", _AAC),
    "m4a": ("m4a", "ipod", _AAC),
}


class RenderError(Exception):
    pass


@dataclass(frozen=True)
class Job:
    original: Path      # absolute
    out_dir: Path       # absolute: renders/<song_id>/
    key: str
    semitones: float
    tempo: float
    bake_tempo: bool
    video: Path | None = None  # absolute: take the video from here (the H.264 playback copy), audio from original


def run(cmd: list[str], timeout: float | None = None) -> None:
    """Run a tool; raise RenderError with the tail of stderr on failure. Tests patch this."""
    try:
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise RenderError(f"{Path(cmd[0]).name} timed out after {timeout:g}s") from e
    if p.returncode != 0:
        tail = p.stderr.decode(errors="replace").strip().splitlines()[-5:]
        raise RenderError(f"{Path(cmd[0]).name} exited {p.returncode}: " + " | ".join(tail))


def video_codec(path: Path) -> str | None:
    """The codec of the real video stream, not an mp3's embedded cover art. None if there isn't one."""
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v",
         "-show_entries", "stream=codec_name:stream_disposition=attached_pic",
         "-of", "json", str(path)], capture_output=True, check=True)
    streams = json.loads(p.stdout or b"{}").get("streams", [])
    return next((s.get("codec_name") for s in streams if not s.get("disposition", {}).get("attached_pic")), None)


def has_video(path: Path) -> bool:
    return video_codec(path) is not None


def output_name(job: Job) -> str:
    ext = (job.video or job.original).suffix[1:].lower()
    return f"{job.key}.{FORMATS[ext][0]}"


def render(job: Job, timeout: float | None = None) -> Path:
    """Render and return the final absolute path."""
    src = job.original.resolve()
    video_src = job.video.resolve() if job.video else src
    ext = video_src.suffix[1:].lower()
    if ext not in FORMATS:
        raise RenderError(f"can't render {video_src.suffix} files")
    out_ext, muxer, audio_args = FORMATS[ext]
    job.out_dir.mkdir(parents=True, exist_ok=True)
    final = job.out_dir / f"{job.key}.{out_ext}"
    work = job.out_dir / f".{job.key}.work"
    tmp_out = job.out_dir / f".{job.key}.tmp.{out_ext}"
    cleanup(job.out_dir, job.key)
    work.mkdir()
    try:
        wav, shifted = work / "in.wav", work / "out.wav"
        ff = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
        run(ff + ["-i", str(src), "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", str(wav)], timeout)

        rb = ["rubberband", "-3", "-q"]
        if job.semitones:
            rb += ["-p", f"{job.semitones:g}"]
        if job.bake_tempo and job.tempo != 1:
            rb += ["-T", f"{job.tempo:g}"]
        run(rb + [str(wav), str(shifted)], timeout)

        video = has_video(video_src)
        cmd = ff + ["-i", str(video_src), "-i", str(shifted)]
        if video:
            cmd += ["-map", "0:v:0"]
        cmd += ["-map", "1:a:0"]
        if video:
            cmd += ["-c:v", "copy"]
        if video and job.bake_tempo and job.tempo != 1:
            # Same packets, timestamps divided by the tempo. avoid_negative_ts keeps
            # every frame of an H.264 stream with B-frames: without it the unscaled
            # MP4 edit list cut the first frames.
            t = f"{job.tempo:g}"
            cmd += ["-bsf:v", f"setts=ts=TS/{t}:duration=DURATION/{t}", "-avoid_negative_ts", "make_zero"]
        cmd += audio_args + ["-map_metadata", "-1", "-map_chapters", "-1"]
        if muxer in ("mp4", "ipod"):
            cmd += ["-movflags", "+faststart"]
        run(cmd + ["-f", muxer, str(tmp_out)], timeout)
        os.replace(tmp_out, final)
    finally:
        cleanup(job.out_dir, job.key)
    return final


def cleanup(out_dir: Path, key: str) -> None:
    """Remove this key's work dir and temp output (left behind by a crash)."""
    shutil.rmtree(out_dir / f".{key}.work", ignore_errors=True)
    for p in out_dir.glob(f".{key}.tmp.*"):
        p.unlink(missing_ok=True)
