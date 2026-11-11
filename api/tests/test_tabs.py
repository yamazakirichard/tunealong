"""Tab songs: Guitar Pro / MusicXML files played by alphaTab, never rendered."""

import dataclasses

from tunealong import db, ingest
from tunealong.deps import get_settings
from tunealong.media import sha256_file

from .conftest import FIXTURES

SCALE = FIXTURES / "scale.musicxml"


def upload(client, name="scale.musicxml", content=None, **form):
    content = SCALE.read_bytes() if content is None else content
    return client.post("/api/songs/tab", files={"file": (name, content, "application/octet-stream")},
                       data=form)


def test_upload_creates_a_ready_tab_song(client, settings):
    r = upload(client, artist="TuneAlong Fixtures", title="Scale")
    assert r.status_code == 201, r.text
    song = r.json()["song"]
    assert (song["kind"], song["status"], song["title"], song["tab_track"]) == ("tab", "ready", "Scale", None)
    assert song["youtube_id"] is None and song["artist_id"] is not None
    sha = sha256_file(SCALE)
    assert (settings.tabs_dir / f"{sha[:16]}.musicxml").read_bytes() == SCALE.read_bytes()
    assert not [p for p in settings.tabs_dir.iterdir() if p.name.startswith(".")]  # no temp files left

    media = client.get(f"/{song['media_url']}", headers={"Range": "bytes=0-4"})
    assert media.status_code == 206 and media.content == b"<?xml"


def test_title_defaults_to_the_file_name(client):
    assert upload(client, name="My Exercise.gp5", content=b"FICHIER GUITAR PRO v5.10").json()["song"]["title"] \
        == "My Exercise"


def test_same_bytes_twice_is_a_conflict(client):
    first = upload(client).json()["song"]
    r = upload(client, name="other-name.xml")
    assert r.status_code == 409 and r.json()["song"]["id"] == first["id"]


def test_rejects_other_files(client, settings):
    assert upload(client, name="song.mp3").status_code == 415
    assert upload(client, name="noext").status_code == 415
    assert upload(client, content=b"").status_code == 422
    assert not list(settings.tabs_dir.iterdir())


def test_rejects_oversize_files(client, settings):
    small = dataclasses.replace(settings, tab_max_mb=0.001)  # ~1 KB; the fixture is ~3.7 KB
    client.app.dependency_overrides[get_settings] = lambda: small
    try:
        assert upload(client).status_code == 413
    finally:
        client.app.dependency_overrides.clear()
    assert not list(settings.tabs_dir.iterdir())


def test_presets_never_render_and_playback_is_tab(client, conn):
    song = upload(client).json()["song"]
    r = client.post(f"/api/songs/{song['id']}/presets",
                    json={"name": "slow", "semitones": 2, "tempo": 0.73, "is_default": True, "volume": 1.5,
                          "loop_a": 1.0, "loop_b": 3.0})
    assert r.status_code == 201, r.text
    assert conn.execute("SELECT count(*) FROM jobs WHERE kind = 'render'").fetchone()[0] == 0
    pb = client.get(f"/api/songs/{song['id']}/playback").json()
    assert pb["source"] == "tab" and pb["url"] == f"media/originals/{song['id']}"
    assert (pb["live_semitones"], pb["live_tempo"], pb["loop_a"], pb["loop_b"]) == (2, 0.73, 1.0, 3.0)
    assert client.get(f"/api/presets/{r.json()['id']}/playback").json()["source"] == "tab"
    assert conn.execute("SELECT count(*) FROM jobs WHERE kind = 'render'").fetchone()[0] == 0


def test_tab_track_patch(client):
    song = upload(client).json()["song"]
    assert client.patch(f"/api/songs/{song['id']}", json={"tab_track": 2}).json()["tab_track"] == 2
    assert client.patch(f"/api/songs/{song['id']}", json={"tab_track": None}).json()["tab_track"] is None
    assert client.patch(f"/api/songs/{song['id']}", json={"tab_track": -1}).status_code == 422


def test_tab_track_is_refused_for_media_songs(client, conn):
    sid = conn.execute("INSERT INTO songs (title, status) VALUES ('v', 'queued')").lastrowid
    assert client.patch(f"/api/songs/{sid}", json={"tab_track": 0}).status_code == 422


def test_tab_song_cannot_be_linked_to_youtube(client):
    song = upload(client).json()["song"]
    r = client.post(f"/api/songs/{song['id']}/link", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    assert r.status_code == 422


def test_scan_picks_up_dropped_tab_files(conn, settings):
    (settings.tabs_dir / "0123456789abcdef.gp5").write_bytes(b"gp5 bytes")
    (settings.tabs_dir / "not-a-hash.gp5").write_bytes(b"ignored")
    res = ingest.scan(conn, settings)
    assert res.created == 1
    row = conn.execute("SELECT kind, title, status FROM songs").fetchone()
    assert tuple(row) == ("tab", "0123456789abcdef", "ready")
    assert ingest.scan(conn, settings).created == 0


def test_delete_keeps_the_file_ignored_and_reupload_restores_it(client, conn, settings):
    song = upload(client).json()["song"]
    assert client.delete(f"/api/songs/{song['id']}").status_code == 204
    assert ingest.scan(conn, settings).created == 0  # kept on disk but ignored
    again = upload(client)
    assert again.status_code == 201
    assert conn.execute("SELECT count(*) FROM ignored_paths").fetchone()[0] == 0


def test_kind_migration_keeps_existing_songs_as_media(monkeypatch, settings):
    conn = db.connect(settings.db_path)
    all_ = db.migrations()
    monkeypatch.setattr(db, "migrations", lambda: all_[:5])
    db.migrate(conn)
    conn.execute("INSERT INTO songs (title, status) VALUES ('old', 'ready')")
    monkeypatch.setattr(db, "migrations", lambda: all_)
    db.migrate(conn)
    assert tuple(conn.execute("SELECT kind, tab_track FROM songs").fetchone()) == ("media", None)
