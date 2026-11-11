"""Make a browser recording seekable: ffmpeg copies the streams into a new WebM.

MediaRecorder streams WebM as it records, so the file has no duration and no
cues (seek index). A copy through ffmpeg's muxer writes both. Nothing is
re-encoded, so it takes about a second even for a long song.
"""

import subprocess


class RemuxFailed(Exception):
    pass


def remux_webm(src: str, dest: str, timeout: float = 300.0) -> None:
    """Copy src's audio and video into dest (absolute paths). Needs an audio stream."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", src],
        capture_output=True, text=True, timeout=timeout,
    )
    kinds = set(probe.stdout.split())
    if probe.returncode != 0 or not kinds:
        raise RemuxFailed((probe.stderr.strip().splitlines() or ["ffprobe could not read it"])[-1])
    if "audio" not in kinds:
        raise RemuxFailed("it has no sound (was 'Also share tab audio' ticked?)")
    run = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
         "-map", "0:v:0?", "-map", "0:a:0", "-c", "copy",
         # bitexact: no random segment UID or encoder tag, so the same recording
         # always remuxes to the same bytes and is recognised as a duplicate.
         "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
         "-f", "webm", dest],
        capture_output=True, text=True, timeout=timeout,
    )
    if run.returncode != 0:
        raise RemuxFailed((run.stderr.strip().splitlines() or ["ffmpeg failed"])[-1])
