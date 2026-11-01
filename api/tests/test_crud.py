import json
from pathlib import Path

import pytest

from songbook import ingest
from songbook.cache import cache_key

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def lib(client, conn, settings, originals):
    """The three fixture songs, ingested: A, B and C (all Unsorted)."""
    ingest.scan(conn, settings)
    return {r["youtube_id"]: r["id"] for r in conn.execute("SELECT id, youtube_id FROM songs")}


def groups(client, **params):
    r = client.get("/api/library", params=params)
    assert r.status_code == 200
    return r.json()["groups"]


def names(gs):
    return [g["name"] for g in gs]


def artist(client, name, **kw):
    r = client.post("/api/artists", json={"name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def preset(client, song_id, **kw):
    return client.post(f"/api/songs/{song_id}/presets", json={"name": "p", **kw})


# --- library ------------------------------------------------------------------

def test_library_groups_and_orders(client, lib):
    zz = artist(client, "ZZ Top", sort_order=0)
    acdc = artist(client, "AC/DC")
    beatles = artist(client, "beatles")
    client.patch(f"/api/songs/{lib['AAAAAAAAAAA']}", json={"artist_id": acdc})
    client.patch(f"/api/songs/{lib['BBBBBBBBBBB']}", json={"artist_id": zz})
    gs = groups(client)
    # sort_order first, then unordered by name (case-insensitive), Unsorted last.
    assert names(gs) == ["ZZ Top", "AC/DC", "beatles", "Unsorted"]
    by = {g["name"]: g for g in gs}
    assert [s["youtube_id"] for s in by["AC/DC"]["songs"]] == ["AAAAAAAAAAA"]
    assert [s["youtube_id"] for s in by["Unsorted"]["songs"]] == ["CCCCCCCCCCC"]
    assert by["Unsorted"]["id"] is None and by["beatles"]["songs"] == []
    s = by["AC/DC"]["songs"][0]
    assert s["media_url"] == f"media/originals/{lib['AAAAAAAAAAA']}" and s["default_preset"] is None


def test_library_includes_default_preset(client, lib):
    sid = lib["AAAAAAAAAAA"]
    preset(client, sid, name="drop D", semitones=-2, is_default=True)
    preset(client, sid, name="other", semitones=1)
    song = next(s for s in groups(client)[-1]["songs"] if s["id"] == sid)
    assert song["default_preset"]["name"] == "drop D"


def test_library_rejects_unknown_group_by(client, lib):
    assert client.get("/api/library", params={"group_by": "colour"}).status_code == 422


def test_library_with_no_songs(client):
    assert names(groups(client)) == ["Unsorted"]


# --- songs --------------------------------------------------------------------

def test_moving_song_to_new_artist_name_creates_it(client, conn, lib):
    sid = lib["AAAAAAAAAAA"]
    r = client.patch(f"/api/songs/{sid}", json={"artist_name": "Black Sabbath"})
    assert r.status_code == 200
    aid = conn.execute("SELECT id FROM artists WHERE name = 'Black Sabbath'").fetchone()[0]
    assert r.json()["artist_id"] == aid
    # Same name again, other case: no second artist.
    client.patch(f"/api/songs/{lib['BBBBBBBBBBB']}", json={"artist_name": "black sabbath"})
    assert conn.execute("SELECT count(*) FROM artists").fetchone()[0] == 1
    by = {g["name"]: g for g in groups(client)}
    assert len(by["Black Sabbath"]["songs"]) == 2


def test_patch_song_fields(client, lib):
    sid = lib["AAAAAAAAAAA"]
    r = client.patch(f"/api/songs/{sid}", json={"title": "  Iron Man  ", "notes": "capo 2"})
    assert (r.json()["title"], r.json()["notes"]) == ("Iron Man", "capo 2")
    client.patch(f"/api/songs/{sid}", json={"artist_name": "X"})
    assert client.patch(f"/api/songs/{sid}", json={"artist_id": None}).json()["artist_id"] is None


@pytest.mark.parametrize("body", [
    {"title": ""}, {"title": None}, {"artist_id": 999}, {"artist_id": 1, "artist_name": "x"}, {"bogus": 1},
])
def test_patch_song_invalid(client, lib, body):
    assert client.patch(f"/api/songs/{lib['AAAAAAAAAAA']}", json=body).status_code == 422


def test_get_missing_song_is_404(client):
    assert client.get("/api/songs/999").status_code == 404
    assert client.patch("/api/songs/999", json={"title": "x"}).status_code == 404
    assert client.delete("/api/songs/999").status_code == 404


def test_get_song_has_presets_and_categories(client, lib):
    sid = lib["AAAAAAAAAAA"]
    preset(client, sid, name="b")
    preset(client, sid, name="a")
    cat = client.post("/api/categories", json={"name": "Tabs"}).json()["id"]
    client.put(f"/api/songs/{sid}/categories", json=[cat])
    s = client.get(f"/api/songs/{sid}").json()
    assert [p["name"] for p in s["presets"]] == ["a", "b"] and s["categories"] == [cat]


# --- presets ------------------------------------------------------------------

def test_second_default_preset_unsets_first(client, conn, lib):
    sid = lib["AAAAAAAAAAA"]
    p1 = preset(client, sid, name="one", is_default=True).json()["id"]
    r = preset(client, sid, name="two", is_default=True)
    assert r.status_code == 201
    defaults = conn.execute("SELECT id FROM presets WHERE song_id = ? AND is_default = 1", (sid,)).fetchall()
    assert [d[0] for d in defaults] == [r.json()["id"]]
    # And back via PATCH.
    assert client.patch(f"/api/presets/{p1}", json={"is_default": True}).status_code == 200
    defaults = conn.execute("SELECT id FROM presets WHERE song_id = ? AND is_default = 1", (sid,)).fetchall()
    assert [d[0] for d in defaults] == [p1]


@pytest.mark.parametrize("body", [
    {"semitones": 13}, {"semitones": -12.5}, {"tempo": 3}, {"tempo": 0.1},
    {"loop_a": 4, "loop_b": 2}, {"loop_a": 3, "loop_b": 3}, {"loop_a": -1}, {"volume": 1.5}, {"volume": -0.1}, {"name": ""}, {"bogus": True},
])
def test_invalid_preset_is_422_and_db_unchanged(client, conn, lib, body):
    sid = lib["AAAAAAAAAAA"]
    good = preset(client, sid, name="ok", semitones=1).json()
    before = conn.execute("SELECT * FROM presets").fetchall()
    assert preset(client, sid, **{"name": "bad", **body}).status_code == 422
    assert client.patch(f"/api/presets/{good['id']}", json=body).status_code == 422
    assert [tuple(r) for r in conn.execute("SELECT * FROM presets")] == [tuple(r) for r in before]


def test_patch_preset_checks_merged_loop(client, lib):
    p = preset(client, lib["AAAAAAAAAAA"], loop_a=2, loop_b=4).json()
    assert client.patch(f"/api/presets/{p['id']}", json={"loop_a": 5}).status_code == 422
    assert client.patch(f"/api/presets/{p['id']}", json={"loop_b": None}).json()["loop_b"] is None


def test_preset_volume_is_stored_and_optional(client, lib):
    sid = lib["AAAAAAAAAAA"]
    assert preset(client, sid, name="plain").json()["volume"] is None
    p = preset(client, sid, name="quiet", volume=0.4).json()
    assert p["volume"] == 0.4
    assert client.patch(f"/api/presets/{p['id']}", json={"semitones": 1}).json()["volume"] == 0.4
    assert client.patch(f"/api/presets/{p['id']}", json={"volume": None}).json()["volume"] is None


def test_duplicate_preset_name_is_409(client, lib):
    sid = lib["AAAAAAAAAAA"]
    preset(client, sid, name="Same")
    assert preset(client, sid, name="Same").status_code == 409


def test_tempo_is_snapped_and_cache_key_written(client, lib):
    p = preset(client, lib["AAAAAAAAAAA"], semitones=2, tempo=0.8333, bake_tempo=True).json()
    assert p["tempo"] == 0.83
    assert p["cache_key"] == "p+2.00_t0.830_bt1_rb3-v1"
    p = client.patch(f"/api/presets/{p['id']}", json={"bake_tempo": False}).json()
    assert p["cache_key"] == "p+2.00_t1.000_bt0_rb3-v1"
    p = client.patch(f"/api/presets/{p['id']}", json={"semitones": 0}).json()
    assert p["cache_key"] is None


def test_cache_key_cases():
    table = json.loads((FIXTURES / "cache_keys.json").read_text())
    for c in table["cases"]:
        assert cache_key(c["semitones"], c["tempo"], c["bake_tempo"]) == c["key"], c


def test_delete_preset(client, lib):
    p = preset(client, lib["AAAAAAAAAAA"]).json()
    assert client.delete(f"/api/presets/{p['id']}").status_code == 204
    assert client.delete(f"/api/presets/{p['id']}").status_code == 404


# --- playback -----------------------------------------------------------------

def test_song_with_no_presets_plays_original_unshifted(client, lib):
    sid = lib["AAAAAAAAAAA"]
    r = client.get(f"/api/songs/{sid}/playback").json()
    assert (r["live_semitones"], r["live_tempo"], r["source"]) == (0.0, 1.0, "original")
    assert r["url"] == f"media/originals/{sid}" and r["preset_id"] is None


def test_non_default_preset_doesnt_shift_playback(client, lib):
    sid = lib["AAAAAAAAAAA"]
    preset(client, sid, semitones=3, tempo=0.7)
    r = client.get(f"/api/songs/{sid}/playback").json()
    assert (r["live_semitones"], r["live_tempo"]) == (0.0, 1.0)


def test_default_preset_drives_playback(client, lib):
    sid = lib["AAAAAAAAAAA"]
    p = preset(client, sid, semitones=-2, tempo=0.75, loop_a=1, loop_b=3, is_default=True).json()
    r = client.get(f"/api/songs/{sid}/playback").json()
    assert (r["preset_id"], r["live_semitones"], r["live_tempo"], r["loop_a"], r["loop_b"]) == (
        p["id"], -2.0, 0.75, 1.0, 3.0)


# --- media --------------------------------------------------------------------

def test_range_request_and_seek(client, lib, settings):
    sid = lib["AAAAAAAAAAA"]
    data = (settings.originals_dir / "AAAAAAAAAAA.webm").read_bytes()
    full = client.get(f"/media/originals/{sid}")
    assert full.status_code == 200 and full.content == data
    assert full.headers["accept-ranges"] == "bytes" and full.headers["content-type"] == "video/webm"
    mid = len(data) // 2
    r = client.get(f"/media/originals/{sid}", headers={"Range": f"bytes={mid}-{mid + 999}"})
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes {mid}-{mid + 999}/{len(data)}"
    assert r.content == data[mid:mid + 1000]
    r = client.get(f"/media/originals/{sid}", headers={"Range": f"bytes={mid}-"})
    assert r.status_code == 206 and r.content == data[mid:]
    r = client.get(f"/media/originals/{sid}", headers={"Range": f"bytes={len(data) + 10}-"})
    assert r.status_code == 416


def test_mp4_content_type(client, lib):
    r = client.get(f"/media/originals/{lib['CCCCCCCCCCC']}")
    assert r.headers["content-type"] == "video/mp4"


@pytest.mark.parametrize("path", [
    "/media/originals/..%2F..%2Fsongbook.sqlite",
    "/media/originals/%2e%2e%2fsongbook.sqlite",
    "/media/originals/..",
    "/media/originals/-1",
    "/media/originals/1.0",
    "/media/originals/AAAAAAAAAAA",
    "/media/originals/999",
    "/media/renders/..%2Fsongbook.sqlite",
    "/media/renders/1",
    "/media/originals/1/../../songbook.sqlite",
])
def test_media_traversal_is_404(client, lib, path):
    assert client.get(path).status_code == 404


def test_db_path_escaping_root_is_404(client, conn, lib):
    sid = lib["AAAAAAAAAAA"]
    conn.execute("UPDATE songs SET original_path = '../../etc/passwd' WHERE id = ?", (sid,))
    assert client.get(f"/media/originals/{sid}").status_code == 404
    conn.execute("UPDATE songs SET original_path = 'songbook.sqlite' WHERE id = ?", (sid,))
    assert client.get(f"/media/originals/{sid}").status_code == 404


def test_render_media_served_and_touched(client, conn, lib, settings):
    sid = lib["AAAAAAAAAAA"]
    d = settings.renders_dir / str(sid)
    d.mkdir()
    (d / "k.webm").write_bytes(b"x" * 100)
    rid = conn.execute("INSERT INTO renders (song_id, cache_key, path) VALUES (?, 'k', ?)",
                       (sid, f"renders/{sid}/k.webm")).lastrowid
    r = client.get(f"/media/renders/{rid}", headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == b"x" * 10
    assert conn.execute("SELECT last_used_at FROM renders WHERE id = ?", (rid,)).fetchone()[0]


# --- delete -------------------------------------------------------------------

def _with_render(conn, settings, sid):
    d = settings.renders_dir / str(sid)
    d.mkdir(exist_ok=True)
    (d / "k.webm").write_bytes(b"render")
    conn.execute("INSERT INTO renders (song_id, cache_key, path) VALUES (?, 'k', ?)", (sid, f"renders/{sid}/k.webm"))
    return d


def test_delete_song_keeps_file_by_default(client, conn, lib, settings):
    sid = lib["AAAAAAAAAAA"]
    rdir = _with_render(conn, settings, sid)
    preset(client, sid)
    assert client.delete(f"/api/songs/{sid}").status_code == 204
    assert (settings.originals_dir / "AAAAAAAAAAA.webm").is_file()
    assert not rdir.exists()
    assert conn.execute("SELECT count(*) FROM presets").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM renders").fetchone()[0] == 0
    # The kept file is not re-added by the next scan.
    ingest.scan(conn, settings)
    assert conn.execute("SELECT count(*) FROM songs WHERE youtube_id = 'AAAAAAAAAAA'").fetchone()[0] == 0


def test_delete_song_with_delete_file(client, conn, lib, settings):
    sid = lib["BBBBBBBBBBB"]
    rdir = _with_render(conn, settings, sid)
    assert client.delete(f"/api/songs/{sid}", params={"delete_file": "true"}).status_code == 204
    assert not (settings.originals_dir / "BBBBBBBBBBB.webm").exists()
    assert not rdir.exists()
    assert (settings.originals_dir / "AAAAAAAAAAA.webm").is_file()


def test_readding_deleted_song_unignores_its_file(client, conn, lib, settings):
    client.delete(f"/api/songs/{lib['AAAAAAAAAAA']}")
    r = client.post("/api/songs", json={"url": "https://youtu.be/AAAAAAAAAAA"})
    assert r.status_code == 201
    assert conn.execute("SELECT count(*) FROM ignored_paths").fetchone()[0] == 0
    ingest.scan(conn, settings)
    assert conn.execute("SELECT status FROM songs WHERE youtube_id = 'AAAAAAAAAAA'").fetchone()[0] == "ready"


def test_delete_cancels_pending_download(client, conn):
    sid = client.post("/api/songs", json={"url": "https://youtu.be/E0ozmU9cJDg"}).json()["song"]["id"]
    client.delete(f"/api/songs/{sid}")
    assert conn.execute("SELECT status FROM jobs").fetchone()[0] == "error"


# --- link ---------------------------------------------------------------------

def _local_song(conn, title="Local"):
    return conn.execute("INSERT INTO songs (title, status, original_path) VALUES (?, 'ready', 'originals/local/x.webm')",
                        (title,)).lastrowid


def test_link_local_song(client, conn, lib):
    sid = _local_song(conn)
    r = client.post(f"/api/songs/{sid}/link", json={"url": "https://youtu.be/E0ozmU9cJDg?t=5"})
    assert r.status_code == 200 and r.json()["youtube_id"] == "E0ozmU9cJDg"
    r = client.post("/api/songs", json={"url": "https://www.youtube.com/watch?v=E0ozmU9cJDg"})
    assert r.status_code == 200 and r.json()["duplicate"] is True and r.json()["song"]["id"] == sid
    assert conn.execute("SELECT count(*) FROM jobs WHERE kind = 'download'").fetchone()[0] == 0
    # Linking a second song to the same ID conflicts and names the owner.
    other = _local_song(conn, "Other")
    r = client.post(f"/api/songs/{other}/link", json={"url": "E0ozmU9cJDg"})
    assert r.status_code == 409 and r.json()["song"]["id"] == sid
    # Re-linking to the same ID is a no-op.
    assert client.post(f"/api/songs/{sid}/link", json={"url": "E0ozmU9cJDg"}).status_code == 200


def test_link_invalid(client, conn, lib):
    sid = _local_song(conn)
    assert client.post(f"/api/songs/{sid}/link", json={"url": "https://vimeo.com/1"}).status_code == 422
    yt = lib["AAAAAAAAAAA"]
    assert client.post(f"/api/songs/{yt}/link", json={"url": "E0ozmU9cJDg"}).status_code == 422


# --- categories ---------------------------------------------------------------

def test_categories_grouping_and_delete(client, conn, lib):
    tabs = client.post("/api/categories", json={"name": "Tabs", "colour": "#ff0000"}).json()["id"]
    covers = client.post("/api/categories", json={"name": "Covers"}).json()["id"]
    sid = lib["AAAAAAAAAAA"]
    assert client.put(f"/api/songs/{sid}/categories", json=[tabs, covers]).status_code == 200
    gs = {g["name"]: g for g in groups(client, group_by="category")}
    assert names(groups(client, group_by="category")) == ["Covers", "Tabs", "Uncategorised"]
    assert [s["id"] for s in gs["Tabs"]["songs"]] == [sid] == [s["id"] for s in gs["Covers"]["songs"]]
    assert {s["youtube_id"] for s in gs["Uncategorised"]["songs"]} == {"BBBBBBBBBBB", "CCCCCCCCCCC"}
    assert gs["Tabs"]["colour"] == "#ff0000"
    # Filter by category.
    only = groups(client, category=tabs)
    assert [s["id"] for g in only for s in g["songs"]] == [sid]

    assert client.delete(f"/api/categories/{tabs}").status_code == 204
    assert conn.execute("SELECT count(*) FROM songs").fetchone()[0] == 3
    assert client.get(f"/api/songs/{sid}").json()["categories"] == [covers]


def test_category_validation(client, lib):
    assert client.post("/api/categories", json={"name": "Tabs"}).status_code == 201
    assert client.post("/api/categories", json={"name": "tabs"}).status_code == 409
    assert client.post("/api/categories", json={"name": "X", "colour": "red"}).status_code == 422
    assert client.put(f"/api/songs/{lib['AAAAAAAAAAA']}/categories", json=[999]).status_code == 422
    assert client.put(f"/api/songs/{lib['AAAAAAAAAAA']}/categories", json=[]).status_code == 200


# --- artists ------------------------------------------------------------------

def test_artist_crud(client, conn, lib):
    aid = artist(client, "Metallica")
    assert client.post("/api/artists", json={"name": "METALLICA"}).status_code == 409
    r = client.patch(f"/api/artists/{aid}", json={"columns": 2, "style": "column", "sort_order": 3})
    assert (r.json()["columns"], r.json()["style"], r.json()["sort_order"]) == (2, "column", 3)
    for bad in ({"columns": 9}, {"columns": 0}, {"style": "grid"}, {"name": ""}, {"name": None}):
        assert client.patch(f"/api/artists/{aid}", json=bad).status_code == 422
    other = artist(client, "Other")
    assert client.patch(f"/api/artists/{other}", json={"name": "metallica"}).status_code == 409
    client.patch(f"/api/songs/{lib['AAAAAAAAAAA']}", json={"artist_id": aid})
    assert client.delete(f"/api/artists/{aid}").status_code == 204
    assert client.get(f"/api/songs/{lib['AAAAAAAAAAA']}").json()["artist_id"] is None
    assert [a["name"] for a in client.get("/api/artists").json()] == ["Other"]


# --- reorder ------------------------------------------------------------------

def test_reorder_songs_within_artist(client, lib):
    aid = artist(client, "A")
    ids = [lib["AAAAAAAAAAA"], lib["BBBBBBBBBBB"], lib["CCCCCCCCCCC"]]
    for i in ids:
        client.patch(f"/api/songs/{i}", json={"artist_id": aid})
    new = [ids[2], ids[0], ids[1]]
    assert client.post("/api/reorder", json={"scope": "songs", "group_id": aid, "ids": new}).status_code == 200
    assert [s["id"] for s in groups(client)[0]["songs"]] == new


def test_reorder_unsorted_and_artists(client, lib):
    ids = [lib["CCCCCCCCCCC"], lib["AAAAAAAAAAA"]]
    assert client.post("/api/reorder", json={"scope": "songs", "group_id": None, "ids": ids}).status_code == 200
    assert [s["id"] for s in groups(client)[-1]["songs"]][:2] == ids
    a, b = artist(client, "A"), artist(client, "B")
    client.post("/api/reorder", json={"scope": "artists", "ids": [b, a]})
    assert names(groups(client))[:2] == ["B", "A"]


def test_reorder_with_foreign_id_is_422_and_unchanged(client, conn, lib):
    a, b = artist(client, "A"), artist(client, "B")
    client.patch(f"/api/songs/{lib['AAAAAAAAAAA']}", json={"artist_id": a})
    client.patch(f"/api/songs/{lib['BBBBBBBBBBB']}", json={"artist_id": b})
    before = conn.execute("SELECT id, sort_order FROM songs ORDER BY id").fetchall()
    for body in (
        {"scope": "songs", "group_id": a, "ids": [lib["AAAAAAAAAAA"], lib["BBBBBBBBBBB"]]},
        {"scope": "songs", "group_id": a, "ids": [lib["AAAAAAAAAAA"], 999]},
        {"scope": "songs", "group_id": a, "ids": [lib["AAAAAAAAAAA"], lib["AAAAAAAAAAA"]]},
        {"scope": "artists", "ids": [a, 999]},
        {"scope": "artists", "group_id": a, "ids": [a]},
        {"scope": "nope", "ids": [a]},
        {"scope": "songs", "ids": []},
    ):
        assert client.post("/api/reorder", json=body).status_code == 422, body
    assert [tuple(r) for r in conn.execute("SELECT id, sort_order FROM songs ORDER BY id")] == [tuple(r) for r in before]


def test_moving_song_clears_its_position(client, conn, lib):
    a, b = artist(client, "A"), artist(client, "B")
    sid = lib["AAAAAAAAAAA"]
    client.patch(f"/api/songs/{sid}", json={"artist_id": a})
    client.post("/api/reorder", json={"scope": "songs", "group_id": a, "ids": [sid]})
    client.patch(f"/api/songs/{sid}", json={"artist_id": b})
    assert conn.execute("SELECT sort_order FROM songs WHERE id = ?", (sid,)).fetchone()[0] is None


# --- search -------------------------------------------------------------------

def test_search_matches_uploader_title_artist(client, conn, lib):
    sid = lib["AAAAAAAAAAA"]
    conn.execute("UPDATE songs SET title = 'My cover', yt_title = 'Iron Man (Live)', uploader = 'TabChannel'"
                 " WHERE id = ?", (sid,))
    client.patch(f"/api/songs/{lib['BBBBBBBBBBB']}", json={"artist_name": "Sabbath"})
    found = lambda q: sorted(s["id"] for g in groups(client, q=q) for s in g["songs"])
    assert found("tabchan") == [sid]
    assert found("iron man") == [sid]
    assert found("MY COV") == [sid]
    assert found("sabb") == [lib["BBBBBBBBBBB"]]
    assert found("nothing matches this") == []
    assert names(groups(client, q="tabchan")) == ["Unsorted"]  # empty groups are dropped when searching
    assert found("%") == [] and found("_") == []  # no LIKE wildcards


# --- jobs ---------------------------------------------------------------------

def test_jobs_list_and_filter(client, conn):
    client.post("/api/songs", json={"url": "https://youtu.be/E0ozmU9cJDg"})
    client.post("/api/library/rescan")
    all_jobs = client.get("/api/jobs").json()
    assert [j["kind"] for j in all_jobs] == ["scan", "download"]
    assert all_jobs[1]["payload"] == {"youtube_id": "E0ozmU9cJDg"}
    assert len(client.get("/api/jobs", params={"status": "pending"}).json()) == 2
    assert client.get("/api/jobs", params={"status": "done"}).json() == []
    assert client.get("/api/jobs", params={"status": "bogus"}).status_code == 422
