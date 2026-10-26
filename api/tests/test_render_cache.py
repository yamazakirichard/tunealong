"""Render caching, enqueueing, playback and GC. The renderer is stubbed, so
these run without rubberband; test_render.py covers the real pipeline."""

import pytest

from songbook import cache, ingest, render
from songbook.worker import Worker


@pytest.fixture
def renders(monkeypatch):
    """Stub renderer: records each call and writes a small file."""
    calls = []

    def fake(job, timeout=None):
        calls.append(job)
        job.out_dir.mkdir(parents=True, exist_ok=True)
        final = job.out_dir / render.output_name(job)
        final.write_bytes(b"r" * 1000)
        return final

    monkeypatch.setattr(render, "render", fake)
    return calls


@pytest.fixture
def song(client, conn, settings, originals):
    ingest.scan(conn, settings)
    return conn.execute("SELECT id FROM songs WHERE youtube_id = 'AAAAAAAAAAA'").fetchone()[0]


@pytest.fixture
def worker(settings, client):
    w = Worker(settings)
    yield w
    w.conn.close()


def preset(client, song_id, **kw):
    r = client.post(f"/api/songs/{song_id}/presets", json={"name": "p", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def render_jobs(conn):
    return conn.execute("SELECT * FROM jobs WHERE kind = 'render' ORDER BY id").fetchall()


def files(settings, song_id):
    d = settings.renders_dir / str(song_id)
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


def playback(client, preset_id):
    r = client.get(f"/api/presets/{preset_id}/playback")
    assert r.status_code == 200, r.text
    return r.json()


def test_saving_same_preset_twice_renders_once(client, conn, settings, song, worker, renders):
    p = preset(client, song, semitones=2)
    client.patch(f"/api/presets/{p['id']}", json={"semitones": 2})  # before the worker runs
    assert len(render_jobs(conn)) == 1
    worker.run_until_idle()
    client.patch(f"/api/presets/{p['id']}", json={"semitones": 2, "name": "renamed"})  # after
    worker.run_until_idle()
    assert len(render_jobs(conn)) == 1 and len(renders) == 1
    assert files(settings, song) == ["p+2.00_t1.000_bt0_rb3-v1.webm"]


def test_identical_presets_share_one_render(client, conn, settings, song, worker, renders):
    preset(client, song, name="a", semitones=-3)
    preset(client, song, name="b", semitones=-3)
    worker.run_until_idle()
    assert len(renders) == 1
    assert conn.execute("SELECT count(*) FROM renders").fetchone()[0] == 1


def test_live_tempo_doesnt_split_the_cache(client, conn, settings, song, worker, renders):
    a = preset(client, song, name="a", semitones=2, tempo=0.8)
    b = preset(client, song, name="b", semitones=2, tempo=1.0)
    assert a["cache_key"] == b["cache_key"] == "p+2.00_t1.000_bt0_rb3-v1"
    worker.run_until_idle()
    assert len(renders) == 1
    pa, pb = playback(client, a["id"]), playback(client, b["id"])
    assert pa["url"] == pb["url"] and pa["source"] == "render"
    assert (pa["live_tempo"], pb["live_tempo"]) == (0.8, 1.0)


def test_minus_zero_semitones_key(client, song, renders):
    p = preset(client, song, semitones=-0.0, tempo=0.75, bake_tempo=True)
    assert p["cache_key"].startswith("p+0.00_") and p["semitones"] == 0.0


def test_deleted_render_file_is_re_enqueued_on_save(client, conn, settings, song, worker, renders):
    p = preset(client, song, semitones=2)
    worker.run_until_idle()
    for f in (settings.renders_dir / str(song)).iterdir():
        f.unlink()
    client.patch(f"/api/presets/{p['id']}", json={"semitones": 2})
    assert [j["status"] for j in render_jobs(conn)] == ["done", "pending"]
    worker.run_until_idle()
    assert len(renders) == 2 and playback(client, p["id"])["source"] == "render"


def test_deleted_render_file_is_re_enqueued_on_playback(client, conn, settings, song, worker, renders):
    p = preset(client, song, semitones=2)
    worker.run_until_idle()
    for f in (settings.renders_dir / str(song)).iterdir():
        f.unlink()
    assert playback(client, p["id"])["source"] == "pending"
    assert conn.execute("SELECT count(*) FROM renders").fetchone()[0] == 0
    worker.run_until_idle()
    assert playback(client, p["id"])["source"] == "render"


def test_engine_version_bump_gives_new_key_and_render(client, conn, settings, song, worker, renders, monkeypatch):
    p = preset(client, song, semitones=2)
    worker.run_until_idle()
    monkeypatch.setattr(cache, "ENGINE_VERSION", "v2")
    pb = playback(client, p["id"])
    assert pb["source"] == "pending"  # the v1 render is ignored
    assert client.get(f"/api/songs/{song}/presets").json()[0]["cache_key"] == "p+2.00_t1.000_bt0_rb3-v2"
    worker.run_until_idle()
    assert len(renders) == 2 and renders[1].key.endswith("-v2")
    assert playback(client, p["id"])["source"] == "render"


@pytest.mark.parametrize("kw", [{}, {"tempo": 0.7}, {"tempo": 1.0, "bake_tempo": True}])
def test_identity_preset_makes_no_job(client, conn, song, renders, kw):
    p = preset(client, song, **kw)
    assert p["cache_key"] is None and render_jobs(conn) == []
    pb = playback(client, p["id"])
    assert pb["source"] == "original" and pb["url"] == f"/media/originals/{song}"
    assert pb["live_semitones"] == 0 and pb["live_tempo"] == kw.get("tempo", 1.0)


def test_pending_then_render(client, conn, song, worker, renders):
    p = preset(client, song, semitones=2, tempo=0.9)
    pb = playback(client, p["id"])
    assert (pb["source"], pb["url"], pb["live_semitones"], pb["live_tempo"]) == (
        "pending", f"/media/originals/{song}", 2.0, 0.9)
    worker.run_until_idle()
    pb = playback(client, p["id"])
    rid = conn.execute("SELECT id FROM renders").fetchone()[0]
    assert (pb["source"], pb["url"], pb["live_semitones"], pb["live_tempo"], pb["time_scale"]) == (
        "render", f"/media/renders/{rid}", 0.0, 0.9, 1.0)
    assert client.get(pb["url"]).status_code == 200


def test_baked_half_tempo_playback(client, song, worker, renders):
    p = preset(client, song, semitones=1, tempo=0.5, bake_tempo=True)
    worker.run_until_idle()
    pb = playback(client, p["id"])
    assert (pb["source"], pb["live_semitones"], pb["live_tempo"], pb["time_scale"]) == ("render", 0.0, 1.0, 2.0)


def test_baked_pending_plays_live(client, song, renders):
    p = preset(client, song, tempo=0.5, bake_tempo=True)
    pb = playback(client, p["id"])
    assert (pb["source"], pb["live_tempo"], pb["time_scale"]) == ("pending", 0.5, 1.0)


def test_song_playback_follows_default_preset(client, song, worker, renders):
    preset(client, song, semitones=2, is_default=True)
    assert client.get(f"/api/songs/{song}/playback").json()["source"] == "pending"
    worker.run_until_idle()
    assert client.get(f"/api/songs/{song}/playback").json()["source"] == "render"


def test_no_render_for_a_song_without_its_file(client, conn, renders):
    sid = conn.execute("INSERT INTO songs (youtube_id, title, status) VALUES ('ZZZZZZZZZZZ', 't', 'queued')").lastrowid
    p = preset(client, sid, semitones=2)
    assert render_jobs(conn) == []
    assert client.get(f"/api/presets/{p['id']}/playback").status_code == 409


def test_failed_render_is_reported_not_retried_on_open(client, conn, song, worker, monkeypatch):
    def broken(job, timeout=None):
        raise render.RenderError("rubberband exited 1: boom")

    monkeypatch.setattr(render, "render", broken)
    p = preset(client, song, semitones=2)
    worker.run_until_idle()
    assert [j["attempts"] for j in render_jobs(conn)] == [3]
    pb = playback(client, p["id"])
    assert pb["source"] == "original" and "boom" in pb["render_error"]
    assert pb["live_semitones"] == 2.0  # still shifted, live
    assert len(render_jobs(conn)) == 1
    client.patch(f"/api/presets/{p['id']}", json={"semitones": 2})  # saving again retries
    assert len(render_jobs(conn)) == 2


def test_song_deleted_mid_render(client, conn, settings, song, worker, monkeypatch):
    def delete_then_render(job, timeout=None):
        conn.execute("DELETE FROM songs WHERE id = ?", (song,))
        job.out_dir.mkdir(parents=True, exist_ok=True)
        f = job.out_dir / render.output_name(job)
        f.write_bytes(b"x")
        return f

    monkeypatch.setattr(render, "render", delete_then_render)
    preset(client, song, semitones=2)
    worker.run_until_idle()
    assert conn.execute("SELECT count(*) FROM renders").fetchone()[0] == 0
    assert files(settings, song) == []


# --- gc -----------------------------------------------------------------------

def _render(conn, settings, song_id, key, size, used):
    d = settings.renders_dir / str(song_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{key}.webm").write_bytes(b"x" * size)
    conn.execute("INSERT INTO renders (song_id, cache_key, path, bytes, last_used_at) VALUES (?, ?, ?, ?, ?)",
                 (song_id, key, f"renders/{song_id}/{key}.webm", size, used))


def test_gc_evicts_unreferenced_first_and_never_originals(client, conn, settings, song, renders):
    p = preset(client, song, name="kept", semitones=2)
    conn.execute("DELETE FROM jobs")
    # Referenced but oldest; unreferenced ones are newer.
    _render(conn, settings, song, p["cache_key"], 1000, "2020-01-01 00:00:00")
    _render(conn, settings, song, "orphan-old", 1000, "2024-01-01 00:00:00")
    _render(conn, settings, song, "orphan-new", 1000, "2025-01-01 00:00:00")
    stray = settings.renders_dir / str(song) / "stray.webm"
    stray.write_bytes(b"x" * 10)
    originals_before = sorted(p.name for p in settings.originals_dir.rglob("*"))

    removed = cache.gc(conn, settings, max_bytes=1500)
    assert removed == [f"renders/{song}/stray.webm", f"renders/{song}/orphan-old.webm", f"renders/{song}/orphan-new.webm"]
    assert [r[0] for r in conn.execute("SELECT cache_key FROM renders")] == [p["cache_key"]]

    removed = cache.gc(conn, settings, max_bytes=0)  # then plain LRU, including referenced
    assert removed == [f"renders/{song}/{p['cache_key']}.webm"]
    assert sorted(p.name for p in settings.originals_dir.rglob("*")) == originals_before


def test_gc_skips_rows_pointing_outside_renders(client, conn, settings, song):
    conn.execute("INSERT INTO renders (song_id, cache_key, path) VALUES (?, 'evil', 'originals/AAAAAAAAAAA.webm')",
                 (song,))
    cache.gc(conn, settings, max_bytes=0)
    assert (settings.originals_dir / "AAAAAAAAAAA.webm").is_file()


def test_gc_under_budget_does_nothing(client, conn, settings, song):
    _render(conn, settings, song, "k", 100, None)
    assert cache.gc(conn, settings, max_bytes=10_000) == []


def test_gc_cli(client, conn, settings, song, capsys):
    _render(conn, settings, song, "k", 100, None)
    assert cache.main(["gc", "--max-gb", "0"]) == 0
    assert "1 file(s) removed" in capsys.readouterr().out
