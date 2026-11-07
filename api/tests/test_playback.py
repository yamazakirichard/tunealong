"""H.264 playback copies: the real ffmpeg, so run with `make test-docker`."""

import shutil
import subprocess
from pathlib import Path

import pytest

from songbook import db, ingest, playback, render
from songbook.media import sha256_file
from songbook.worker import Worker

pytestmark = pytest.mark.skipif(shutil.which("rubberband") is None, reason="rubberband not installed")


def codec(path: Path) -> str:
    return render.video_codec(path)


def frames(path: Path) -> int:
    return int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                               "stream=nb_read_frames", "-of", "csv=p=0", str(path)],
                              capture_output=True, check=True, text=True).stdout)


def song_row(conn, yid):
    return conn.execute("SELECT * FROM songs WHERE youtube_id = ?", (yid,)).fetchone()


@pytest.fixture
def worker(settings, client):
    w = Worker(settings)
    yield w
    w.conn.close()


@pytest.fixture
def av1(settings, conn) -> dict:
    """A song whose original isn't H.264, as a new download would arrive."""
    path = settings.originals_dir / "VVVVVVVVVVV.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=322x180:r=30:d=3",
                    "-f", "lavfi", "-i", "sine=f=440:d=3", "-c:v", "libaom-av1", "-cpu-used", "8", "-crf", "40",
                    "-c:a", "aac", "-shortest", str(path)], check=True)
    ingest.scan(conn, settings)
    return {"path": path, "row": song_row(conn, "VVVVVVVVVVV")}


def test_copy_is_h264_with_every_frame_and_the_original_is_untouched(client, conn, settings, worker, av1):
    before = sha256_file(av1["path"])
    assert codec(av1["path"]) == "av1"
    assert worker.maybe_playback() is True
    row = song_row(conn, "VVVVVVVVVVV")
    copy = settings.root / row["playback_path"]
    assert row["playback_state"] == "done" and row["playback_path"] == f"playback/{row['id']}.mp4"
    assert codec(copy) == "h264"
    assert frames(copy) == frames(av1["path"])
    assert sha256_file(av1["path"]) == before
    assert not list(settings.playback_dir.glob(".*"))
    assert worker.maybe_playback() is False  # nothing left to do


def test_copy_keeps_resolution_up_to_an_even_size(client, conn, settings, worker, av1):
    odd = settings.originals_dir / "OOOOOOOOOOO.webm"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=321x181:r=10:d=1",
                    "-c:v", "libvpx-vp9", "-cpu-used", "8", str(odd)], check=True)
    ingest.scan(conn, settings)
    while worker.maybe_playback():
        pass
    copy = settings.root / song_row(conn, "OOOOOOOOOOO")["playback_path"]
    size = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                           "-of", "csv=p=0", str(copy)], capture_output=True, check=True, text=True).stdout.strip()
    assert size == "320,180"


def test_media_route_serves_the_copy_with_range(client, conn, settings, worker, av1):
    song_id = av1["row"]["id"]
    assert client.get(f"/media/originals/{song_id}").content == av1["path"].read_bytes()  # no copy yet: the original
    worker.maybe_playback()
    copy = settings.playback_dir / f"{song_id}.mp4"
    r = client.get(f"/media/originals/{song_id}", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and r.content == copy.read_bytes()[:100]
    copy.unlink()
    assert client.get(f"/media/originals/{song_id}").content == av1["path"].read_bytes()  # falls back


def test_h264_gets_no_copy(client, conn, settings, worker, av1):
    path = settings.originals_dir / "HHHHHHHHHHH.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=10:d=1",
                    "-c:v", "libx264", str(path)], check=True)
    ingest.scan(conn, settings)
    while worker.maybe_playback():
        pass
    row = song_row(conn, "HHHHHHHHHHH")
    assert row["playback_state"] == "done" and row["playback_path"] is None
    assert not (settings.playback_dir / f"{row['id']}.mp4").exists()


def test_render_waits_for_the_copy_and_uses_its_video(client, conn, settings, worker, av1):
    song_id = av1["row"]["id"]
    r = client.post(f"/api/songs/{song_id}/presets", json={"name": "p", "semitones": 2, "tempo": 0.5, "bake_tempo": True})
    assert r.status_code == 201, r.text
    worker.run_until_idle()
    row = conn.execute("SELECT path FROM renders WHERE song_id = ?", (song_id,)).fetchone()
    out = settings.root / row["path"]
    assert codec(out) == "h264"
    assert song_row(conn, "VVVVVVVVVVV")["playback_state"] == "done"
    assert frames(out) == frames(av1["path"])


def test_old_renders_go_when_the_copy_arrives(client, conn, settings, av1):
    song_id = av1["row"]["id"]
    old = settings.renders_dir / str(song_id) / "x.mp4"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"av1")
    conn.execute("INSERT INTO renders (song_id, cache_key, path, bytes) VALUES (?, 'x', ?, 3)",
                 (song_id, old.relative_to(settings.root).as_posix()))
    playback.ensure(conn, settings, song_id)
    assert not old.exists()
    assert conn.execute("SELECT count(*) FROM renders WHERE song_id = ?", (song_id,)).fetchone()[0] == 0


def test_failed_encode_is_recorded_and_not_retried(client, conn, settings, worker, av1, monkeypatch):
    def boom(*a, **kw):
        raise render.RenderError("nope")
    monkeypatch.setattr(render, "run", boom)
    assert worker.maybe_playback() is True
    assert song_row(conn, "VVVVVVVVVVV")["playback_state"] == "error"
    assert worker.maybe_playback() is False
    assert client.get(f"/media/originals/{av1['row']['id']}").status_code == 200


def test_delete_removes_the_copy(client, conn, settings, worker, av1):
    song_id = av1["row"]["id"]
    worker.maybe_playback()
    assert client.delete(f"/api/songs/{song_id}").status_code == 204
    assert not (settings.playback_dir / f"{song_id}.mp4").exists()


def test_new_path_for_the_original_means_a_new_copy(client, conn, settings, worker, av1):
    worker.maybe_playback()
    moved = av1["path"].with_suffix(".mkv")
    av1["path"].rename(moved)
    conn.execute("UPDATE songs SET status = 'queued' WHERE youtube_id = 'VVVVVVVVVVV'")
    ingest.scan(conn, settings)
    row = song_row(conn, "VVVVVVVVVVV")
    assert row["playback_state"] == "pending" and row["playback_path"] is None


def test_existing_songs_are_left_alone_until_queued(settings, tmp_path, monkeypatch, capsys):
    """The migration marks the songs already there as skip; the CLI brings one back."""
    conn = db.connect(settings.db_path)
    scripts = db.migrations()
    for version, sql in enumerate(scripts[:-1], start=1):
        conn.executescript(sql)
    conn.execute("INSERT INTO songs (youtube_id, title, original_path, status) VALUES ('EEEEEEEEEEE', 't', 'originals/x.mp4', 'ready')")
    conn.executescript(scripts[-1])
    assert conn.execute("SELECT playback_state FROM songs").fetchone()[0] == "skip"
    conn.execute("INSERT INTO songs (youtube_id, title, original_path, status) VALUES ('FFFFFFFFFFF', 't', 'originals/y.mp4', 'ready')")
    assert conn.execute("SELECT playback_state FROM songs WHERE youtube_id = 'FFFFFFFFFFF'").fetchone()[0] == "pending"
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))")
    conn.executemany("INSERT OR IGNORE INTO schema_version (version) VALUES (?)", [(i + 1,) for i in range(len(scripts))])
    sid = conn.execute("SELECT id FROM songs WHERE youtube_id = 'EEEEEEEEEEE'").fetchone()[0]
    conn.close()
    monkeypatch.setenv("SONGBOOK_ROOT", str(settings.root))
    assert playback.main(["queue", str(sid)]) == 0
    assert "1 song(s) queued" in capsys.readouterr().out
    check = db.connect(settings.db_path)
    assert check.execute("SELECT playback_state FROM songs WHERE id = ?", (sid,)).fetchone()[0] == "pending"
    check.close()
