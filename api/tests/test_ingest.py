import json
import shutil

from tunealong import ingest
from tunealong.media import sha256_file


def songs(conn):
    return {r["youtube_id"]: r for r in conn.execute("SELECT * FROM songs")}


def test_scan_fixtures_creates_ready_songs_with_sha(conn, settings, originals):
    res = ingest.scan(conn, settings)
    assert res.created == 3
    rows = songs(conn)
    assert set(rows) == {"AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"}
    for yid, r in rows.items():
        path = settings.root / r["original_path"]
        assert r["status"] == "ready"
        assert path.parent == originals and path.name.startswith(yid)
        assert r["original_sha256"] == sha256_file(path)


def test_scan_twice_is_idempotent(conn, settings, originals):
    ingest.scan(conn, settings)
    before = {k: r["added_at"] for k, r in songs(conn).items()}
    res = ingest.scan(conn, settings)
    assert (res.created, res.updated, res.unchanged) == (0, 0, 3)
    assert {k: r["added_at"] for k, r in songs(conn).items()} == before


def test_partial_and_intermediate_files_are_ignored(conn, settings, originals):
    src = originals / "AAAAAAAAAAA.webm"
    for name in ("DDDDDDDDDDD.webm.part", "EEEEEEEEEEE.webm.temp", "FFFFFFFFFFF.webm.ytdl",
                 "GGGGGGGGGGG.f137.mp4", "HHHHHHHHHHH.part", "short.webm"):
        shutil.copy(src, originals / name)
    ingest.scan(conn, settings)
    assert set(songs(conn)) == {"AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"}


def test_unknown_local_file_creates_local_song(conn, settings, originals):
    src = originals / "BBBBBBBBBBB.webm"
    name = sha256_file(src)[:16]
    shutil.move(src, settings.local_dir / f"{name}.webm")
    ingest.scan(conn, settings)
    local = conn.execute("SELECT * FROM songs WHERE youtube_id IS NULL").fetchall()
    assert len(local) == 1
    assert local[0]["original_path"] == f"originals/local/{name}.webm"
    assert local[0]["status"] == "ready"
    assert ingest.scan(conn, settings).created == 0


def test_info_json_sets_reference_fields_only(conn, settings, originals):
    (originals / "AAAAAAAAAAA.info.json").write_text(
        json.dumps({"title": "Master of Puppets (cover)", "uploader": "Some Channel"}))
    (originals / "ZZZZZZZZZZZ.info.json").write_text(json.dumps({"title": "orphan"}))
    ingest.scan(conn, settings)
    rows = songs(conn)
    assert "ZZZZZZZZZZZ" not in rows and len(rows) == 3
    a = rows["AAAAAAAAAAA"]
    assert (a["yt_title"], a["uploader"], a["title"]) == (
        "Master of Puppets (cover)", "Some Channel", "Master of Puppets (cover)")
    assert rows["BBBBBBBBBBB"]["title"] == "BBBBBBBBBBB"


def test_rescan_keeps_user_title(conn, settings, originals):
    (originals / "AAAAAAAAAAA.info.json").write_text(json.dumps({"title": "YT title"}))
    ingest.scan(conn, settings)
    conn.execute("UPDATE songs SET title = 'My title' WHERE youtube_id = 'AAAAAAAAAAA'")
    (originals / "AAAAAAAAAAA.info.json").write_text(json.dumps({"title": "YT title v2"}))
    ingest.scan(conn, settings)
    a = songs(conn)["AAAAAAAAAAA"]
    assert a["title"] == "My title"
    assert a["yt_title"] == "YT title v2"


def test_new_songs_have_no_artist_or_categories(conn, settings, originals):
    conn.execute("INSERT INTO artists (name) VALUES ('Metallica')")
    conn.execute("INSERT INTO categories (name) VALUES ('Tabs')")
    ingest.scan(conn, settings)
    assert conn.execute("SELECT count(*) FROM songs WHERE artist_id IS NOT NULL").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM song_categories").fetchone()[0] == 0


def test_queued_row_flips_to_ready_when_file_appears(conn, settings, originals):
    target = originals / "AAAAAAAAAAA.webm"
    stash = settings.root / "stash.webm"
    shutil.move(target, stash)
    conn.execute("INSERT INTO songs (youtube_id, title, status) VALUES ('AAAAAAAAAAA', 'Mine', 'queued')")
    ingest.scan(conn, settings)
    assert songs(conn)["AAAAAAAAAAA"]["status"] == "queued"

    shutil.move(stash, target)
    res = ingest.scan(conn, settings, youtube_id="AAAAAAAAAAA")
    assert (res.created, res.updated) == (0, 1)
    a = songs(conn)["AAAAAAAAAAA"]
    assert (a["status"], a["title"], a["original_path"]) == ("ready", "Mine", "originals/AAAAAAAAAAA.webm")
    assert a["original_sha256"] == sha256_file(target)


def test_error_row_flips_to_ready_and_clears_error(conn, settings, originals):
    conn.execute("INSERT INTO songs (youtube_id, title, status, error)"
                 " VALUES ('BBBBBBBBBBB', 't', 'error', 'boom')")
    ingest.scan(conn, settings)
    b = songs(conn)["BBBBBBBBBBB"]
    assert (b["status"], b["error"]) == ("ready", None)


def test_scan_by_id_touches_only_that_id(conn, settings, originals):
    res = ingest.scan(conn, settings, youtube_id="CCCCCCCCCCC")
    assert res.created == 1 and set(songs(conn)) == {"CCCCCCCCCCC"}
