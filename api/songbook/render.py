"""Offline renders: ffmpeg extract → rubberband (R3) → ffmpeg remux.

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

# original extension → (output extension, ffmpeg muxer, audio encoder args, baked-video encoder args)
_VP9 = ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "32", "-deadline", "good", "-cpu-used", "4", "-row-mt", "1"]
_H264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
_OPUS = ["-c:a", "libopus", "-b:a", "160k"]
_AAC = ["-c:a", "aac", "-b:a", "192k"]
FORMATS = {
    "webm": ("webm", "webm", _OPUS, _VP9),
    "mp4": ("mp4", "mp4", _AAC, _H264),
    "mkv": ("mkv", "matroska", _OPUS, _H264),
    "mp3": ("m4a", "ipod", _AAC, None),
    "m4a": ("m4a", "ipod", _AAC, None),
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


def run(cmd: list[str], timeout: float | None = None) -> None:
    """Run a tool; raise RenderError with the tail of stderr on failure. Tests patch this."""
    try:
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise RenderError(f"{Path(cmd[0]).name} timed out after {timeout:g}s") from e
    if p.returncode != 0:
        tail = p.stderr.decode(errors="replace").strip().splitlines()[-5:]
        raise RenderError(f"{Path(cmd[0]).name} exited {p.returncode}: " + " | ".join(tail))


def has_video(path: Path) -> bool:
    """A real video stream, not an mp3's embedded cover art."""
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=index:stream_disposition=attached_pic",
         "-of", "json", str(path)], capture_output=True, check=True)
    streams = json.loads(p.stdout or b"{}").get("streams", [])
    return any(not s.get("disposition", {}).get("attached_pic") for s in streams)


def output_name(job: Job) -> str:
    ext = job.original.suffix[1:].lower()
    return f"{job.key}.{FORMATS[ext][0]}"


def render(job: Job, timeout: float | None = None) -> Path:
    """Render and return the final absolute path."""
    src = job.original.resolve()
    ext = src.suffix[1:].lower()
    if ext not in FORMATS:
        raise RenderError(f"can't render {src.suffix} files")
    out_ext, muxer, audio_args, video_args = FORMATS[ext]
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

        video = has_video(src)
        cmd = ff + ["-i", str(src), "-i", str(shifted)]
        if video:
            cmd += ["-map", "0:v:0"]
        cmd += ["-map", "1:a:0"]
        if video and job.bake_tempo and job.tempo != 1:
            cmd += ["-filter:v", f"setpts=PTS/{job.tempo:g}"] + (video_args or _H264)
        elif video:
            cmd += ["-c:v", "copy"]
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
