"""Tab recordings: MediaRecorder WebM uploaded, remuxed to be seekable, stored as a local song."""

import shutil
import subprocess

import pytest

from tunealong import ingest

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


def streamed_webm(tmp_path, audio=True, seconds=2) -> bytes:
    """A WebM written to a pipe, so like MediaRecorder's it has no duration or cues."""
    args = ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=10:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "libopus"]
    args += ["-c:v", "libvpx", "-b:v", "200k", "-f", "webm", "pipe:1"]
    return subprocess.run(args, capture_output=True, check=True).stdout


def duration(path) -> str:
    return subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                          capture_output=True, text=True).stdout.strip()


def upload(client, content, name="recording.webm", **form):
    return client.post("/api/songs/recording", files={"file": (name, content, "video/webm")}, data=form)


def test_recording_becomes_a_seekable_local_song(client, conn, settings, tmp_path):
    raw = streamed_webm(tmp_path)
    (tmp_path / "raw.webm").write_bytes(raw)
    assert duration(tmp_path / "raw.webm") in ("", "N/A")  # what the browser would get without the remux

    r = upload(client, raw, artist="TuneAlong Fixtures", title="Take 1")
    assert r.status_code == 201, r.text
    song = r.json()["song"]
    assert (song["kind"], song["status"], song["title"], song["youtube_id"]) == ("media", "ready", "Take 1", None)
    stored = [p for p in settings.local_dir.iterdir()]
    assert len(stored) == 1 and stored[0].suffix == ".webm"  # no temp files left behind
    assert float(duration(stored[0])) == pytest.approx(2, abs=0.2)

    media = client.get(f"/{song['media_url']}", headers={"Range": "bytes=0-3"})
    assert media.status_code == 206 and media.content == b"\x1a\x45\xdf\xa3"  # EBML header
    assert ingest.scan(conn, settings).created == 0  # the scan sees it as the song it already is


def test_title_defaults(client, tmp_path):
    assert upload(client, streamed_webm(tmp_path)).json()["song"]["title"] == "Recording"


def test_the_same_recording_twice_is_a_conflict(client, tmp_path):
    raw = streamed_webm(tmp_path)
    first = upload(client, raw).json()["song"]
    r = upload(client, raw)
    assert r.status_code == 409 and r.json()["song"]["id"] == first["id"]


def test_a_recording_without_sound_is_refused(client, settings, tmp_path):
    r = upload(client, streamed_webm(tmp_path, audio=False))
    assert r.status_code == 422 and "tab audio" in r.json()["detail"]
    assert not list(settings.local_dir.iterdir())


def test_garbage_and_wrong_types_are_refused(client, settings):
    assert upload(client, b"not a video").status_code == 422
    assert upload(client, b"x", name="clip.mp4").status_code == 415
    assert not list(settings.local_dir.iterdir())


def test_recording_presets_render_like_any_video(client, conn, tmp_path):
    song = upload(client, streamed_webm(tmp_path)).json()["song"]
    r = client.post(f"/api/songs/{song['id']}/presets", json={"name": "down", "semitones": -2})
    assert r.status_code == 201
    assert conn.execute("SELECT count(*) FROM jobs WHERE kind = 'render'").fetchone()[0] == 1
