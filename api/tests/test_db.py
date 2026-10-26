import sqlite3

import pytest

from songbook import db


def add_song(conn, youtube_id="AAAAAAAAAAA", **kw):
    cols = {"youtube_id": youtube_id, "title": "t", "status": "ready", **kw}
    names = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    return conn.execute(f"INSERT INTO songs ({names}) VALUES ({marks})", tuple(cols.values())).lastrowid


def add_preset(conn, song_id, name="p", **kw):
    cols = {"song_id": song_id, "name": name, **kw}
    names = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    return conn.execute(f"INSERT INTO presets ({names}) VALUES ({marks})", tuple(cols.values())).lastrowid


def tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")}


# --- schema / migrations ----------------------------------------------------

def test_schema_applies_to_empty_db_and_twice_is_noop(settings):
    conn = db.connect(settings.db_path)
    assert db.migrate(conn) == len(db.migrations())
    before = tables(conn)
    assert {"artists", "songs", "presets", "categories", "song_categories",
            "renders", "jobs", "schema_version", "one_default_preset", "one_active_job"} <= before

    assert db.migrate(conn) == len(db.migrations())
    assert tables(conn) == before
    assert conn.execute("SELECT count(*) FROM schema_version").fetchone()[0] == len(db.migrations())
    conn.close()

    # and again from a fresh connection, as on a restart
    conn = db.open_db(settings.db_path)
    assert tables(conn) == before
    conn.close()


def test_failed_migration_rolls_back(settings, monkeypatch):
    conn = db.open_db(settings.db_path)
    v = db.schema_version(conn)
    bad = db.migrations() + ["CREATE TABLE half_done (x INTEGER);\nTHIS IS NOT SQL;\n"]
    monkeypatch.setattr(db, "migrations", lambda: bad)
    with pytest.raises(sqlite3.OperationalError):
        db.migrate(conn)
    assert db.schema_version(conn) == v
    assert "half_done" not in tables(conn)


def test_pragmas_on_every_connection(settings, conn):
    for c in (conn, db.connect(settings.db_path, busy_timeout_ms=1234)):
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == settings.busy_timeout_ms
    assert c.execute("PRAGMA busy_timeout").fetchone()[0] == 1234


def test_schema_sql_has_no_pragmas():
    from importlib import resources
    sql = (resources.files("songbook") / "schema.sql").read_text()
    stmts = [l for l in sql.splitlines() if not l.strip().startswith("--")]
    assert not any("PRAGMA" in l.upper() for l in stmts)


# --- songs ------------------------------------------------------------------

def test_song_youtube_id_must_be_11_chars(conn):
    with pytest.raises(sqlite3.IntegrityError):
        add_song(conn, youtube_id="A" * 10)


def test_duplicate_youtube_id_fails(conn):
    add_song(conn, "AAAAAAAAAAA")
    with pytest.raises(sqlite3.IntegrityError):
        add_song(conn, "AAAAAAAAAAA")


def test_local_songs_with_null_youtube_id_are_allowed(conn):
    add_song(conn, None, original_sha256="a" * 64)
    add_song(conn, None, original_sha256="b" * 64)
    assert conn.execute("SELECT count(*) FROM songs WHERE youtube_id IS NULL").fetchone()[0] == 2


# --- presets ----------------------------------------------------------------

def test_second_default_preset_fails(conn):
    s = add_song(conn)
    add_preset(conn, s, "one", is_default=1)
    add_preset(conn, s, "two", is_default=0)
    with pytest.raises(sqlite3.IntegrityError):
        add_preset(conn, s, "three", is_default=1)
    # another song can have its own default
    add_preset(conn, add_song(conn, "BBBBBBBBBBB"), "one", is_default=1)


@pytest.mark.parametrize("kw", [
    {"semitones": 13},
    {"semitones": -12.5},
    {"tempo": 3},
    {"tempo": 0.2},
    {"loop_a": 4, "loop_b": 4},
    {"loop_a": 5, "loop_b": 4},
    {"bake_tempo": 2},
])
def test_preset_out_of_range_fails(conn, kw):
    s = add_song(conn)
    with pytest.raises(sqlite3.IntegrityError):
        add_preset(conn, s, **kw)


def test_preset_edges_are_allowed(conn):
    s = add_song(conn)
    add_preset(conn, s, "lo", semitones=-12, tempo=0.25, loop_a=0, loop_b=0.1)
    add_preset(conn, s, "hi", semitones=12, tempo=2.0, bake_tempo=1)


# --- cascades ---------------------------------------------------------------

def test_delete_song_cascades_to_presets_and_renders(conn):
    s = add_song(conn)
    add_preset(conn, s)
    conn.execute("INSERT INTO renders (song_id, cache_key, path) VALUES (?, 'k', 'renders/1/k.webm')", (s,))
    conn.execute("DELETE FROM songs WHERE id = ?", (s,))
    assert conn.execute("SELECT count(*) FROM presets").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM renders").fetchone()[0] == 0


def test_delete_artist_unsorts_songs(conn):
    a = conn.execute("INSERT INTO artists (name) VALUES ('Metallica')").lastrowid
    s = add_song(conn, artist_id=a)
    conn.execute("DELETE FROM artists WHERE id = ?", (a,))
    assert conn.execute("SELECT artist_id FROM songs WHERE id = ?", (s,)).fetchone()[0] is None


# --- jobs -------------------------------------------------------------------

def add_job(conn, kind="download", key="dl:AAAAAAAAAAA", status="pending"):
    return conn.execute(
        "INSERT INTO jobs (kind, dedupe_key, payload, status) VALUES (?, ?, '{}', ?)",
        (kind, key, status),
    ).lastrowid


def test_active_job_dedupe(conn):
    j = add_job(conn)
    with pytest.raises(sqlite3.IntegrityError):
        add_job(conn)
    conn.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (j,))
    with pytest.raises(sqlite3.IntegrityError):
        add_job(conn)
    conn.execute("UPDATE jobs SET status = 'done' WHERE id = ?", (j,))
    add_job(conn)


def test_scan_job_kind_allowed_unknown_kind_fails(conn):
    add_job(conn, kind="scan", key="scan")
    with pytest.raises(sqlite3.IntegrityError):
        add_job(conn, kind="explode", key="x")


# --- API --------------------------------------------------------------------

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_fixture_copies(originals):
    names = sorted(p.name for p in originals.iterdir() if p.is_file())
    assert names == ["AAAAAAAAAAA.webm", "BBBBBBBBBBB.webm", "CCCCCCCCCCC.mp4"]
