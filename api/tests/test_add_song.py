import dataclasses

import pytest

from tunealong import jobs
from tunealong.worker import MAX_ATTEMPTS, Worker

from .conftest import FIXTURES
from .fake_metube import FakeMetube, Server

YID = "E0ozmU9cJDg"
URL = f"https://www.youtube.com/watch?v={YID}"


@pytest.fixture
def fake(settings):
    fm = FakeMetube(settings.originals_dir, FIXTURES / "originals" / "AAAAAAAAAAA.webm")
    with Server(fm.app) as srv:
        fm.url = srv.url
        yield fm


@pytest.fixture
def wsettings(settings, fake):
    return dataclasses.replace(settings, metube_url=fake.url, download_timeout_s=5, download_poll_s=0.02)


@pytest.fixture
def worker(wsettings, client):  # client first, so the app has created the DB
    w = Worker(wsettings)
    yield w
    w.conn.close()


def song(conn, yid=YID):
    return conn.execute("SELECT * FROM songs WHERE youtube_id = ?", (yid,)).fetchone()


def job_count(conn, kind="download"):
    return conn.execute("SELECT count(*) FROM jobs WHERE kind = ?", (kind,)).fetchone()[0]


def test_add_new_url_downloads_and_becomes_ready(client, conn, worker, fake):
    r = client.post("/api/songs", json={"url": URL})
    assert r.status_code == 201
    assert r.json()["song"]["status"] == "queued" and r.json()["duplicate"] is False
    worker.run_until_idle()
    assert fake.add_calls == 1
    assert fake.calls[0] == {"url": URL, "download_type": "video", "quality": "best",
                             "format": "any", "codec": "auto"}
    s = song(conn)
    assert s["status"] == "ready" and s["original_path"] == f"originals/{YID}.webm"
    assert conn.execute("SELECT status FROM jobs").fetchone()[0] == "done"


def test_same_song_in_another_url_form_is_a_duplicate(client, conn, worker, fake):
    client.post("/api/songs", json={"url": URL})
    worker.run_until_idle()
    r = client.post("/api/songs", json={"url": f"https://youtu.be/{YID}?si=abc&t=30"})
    assert r.status_code == 200
    assert r.json()["duplicate"] is True and r.json()["song"]["youtube_id"] == YID
    worker.run_until_idle()
    assert fake.add_calls == 1
    assert job_count(conn) == 1


def test_adding_twice_before_download_finishes(client, conn, worker, fake):
    assert client.post("/api/songs", json={"url": URL}).status_code == 201
    r = client.post("/api/songs", json={"url": f"https://music.youtube.com/watch?v={YID}"})
    assert r.status_code == 202 and r.json()["duplicate"] is False
    assert job_count(conn) == 1
    worker.run_until_idle()
    assert fake.add_calls == 1 and job_count(conn) == 1


def test_adding_while_downloading_creates_no_job(client, conn, worker, fake):
    client.post("/api/songs", json={"url": URL})
    jobs.claim(conn)  # as the worker would: the job is now running
    conn.execute("UPDATE songs SET status = 'downloading'")
    r = client.post("/api/songs", json={"url": URL})
    assert r.status_code == 202 and r.json()["song"]["status"] == "downloading"
    assert job_count(conn) == 1


def test_metube_500_retries_then_errors(client, conn, worker, fake):
    fake.fail_status = 500
    client.post("/api/songs", json={"url": URL})
    worker.run_until_idle()
    assert fake.add_calls == MAX_ATTEMPTS == 3
    s = song(conn)
    assert s["status"] == "error" and "500" in s["error"]
    j = conn.execute("SELECT * FROM jobs").fetchone()
    assert (j["status"], j["attempts"]) == ("error", 3) and j["finished_at"]


def test_failed_download_reported_by_metube_history(client, conn, worker, fake):
    fake.yt_error = "ERROR: [youtube] This video is unavailable"
    client.post("/api/songs", json={"url": URL})
    worker.run_until_idle()
    s = song(conn)
    assert s["status"] == "error" and "unavailable" in s["error"]
    assert fake.add_calls == 3


def test_download_timeout(client, conn, wsettings, fake):
    fake.delay = 60
    w = Worker(dataclasses.replace(wsettings, download_timeout_s=0.2))
    client.post("/api/songs", json={"url": URL})
    w.run_until_idle()
    assert "timed out" in song(conn)["error"]


def test_readding_errored_song_retries(client, conn, worker, fake):
    fake.fail_status = 500
    client.post("/api/songs", json={"url": URL})
    worker.run_until_idle()
    assert song(conn)["status"] == "error"

    fake.fail_status = None
    r = client.post("/api/songs", json={"url": URL})
    assert r.status_code == 202
    s = song(conn)
    assert (s["status"], s["error"]) == ("queued", None)
    worker.run_until_idle()
    assert fake.add_calls == 4
    assert song(conn)["status"] == "ready"


def test_retry_clears_stale_metube_failure(client, conn, worker, fake):
    fake.yt_error = "ERROR: unavailable"
    client.post("/api/songs", json={"url": URL})
    worker.run_until_idle()
    fake.yt_error = None
    client.post("/api/songs", json={"url": URL})
    worker.run_until_idle()
    assert song(conn)["status"] == "ready" and fake.done == []


def test_crashed_running_job_is_reclaimed(client, conn, wsettings, fake):
    client.post("/api/songs", json={"url": URL})
    jobs.claim(conn)  # a worker claimed it, then died
    conn.execute("UPDATE songs SET status = 'downloading'")
    w = Worker(wsettings)
    w.startup()
    assert conn.execute("SELECT status FROM jobs WHERE kind = 'download'").fetchone()[0] == "pending"
    w.run_until_idle()
    assert song(conn)["status"] == "ready" and fake.add_calls == 1


def test_file_already_present_skips_metube(client, conn, worker, fake, settings):
    client.post("/api/songs", json={"url": URL})
    (settings.originals_dir / f"{YID}.webm").write_bytes(fake.fixture.read_bytes())
    worker.run_until_idle()
    assert fake.add_calls == 0 and song(conn)["status"] == "ready"


def test_rescan_twice_creates_one_scan_job(client, conn, worker, originals):
    assert client.post("/api/library/rescan").json() == {"queued": True}
    assert client.post("/api/library/rescan").status_code == 202
    assert conn.execute("SELECT count(*) FROM jobs WHERE kind = 'scan' AND status = 'pending'").fetchone()[0] == 1
    worker.run_until_idle()
    assert conn.execute("SELECT count(*) FROM songs").fetchone()[0] == 3
    assert client.post("/api/library/rescan").json() == {"queued": True}


def test_worker_startup_enqueues_a_scan(client, conn, worker):
    worker.startup()
    worker.startup()
    assert job_count(conn, "scan") == 1


def test_artist_matches_case_insensitively(client, conn):
    conn.execute("INSERT INTO artists (name) VALUES ('Metallica')")
    r = client.post("/api/songs", json={"url": URL, "artist": "metallica", "title": "Master of Puppets"})
    assert r.status_code == 201
    assert conn.execute("SELECT count(*) FROM artists").fetchone()[0] == 1
    s = song(conn)
    assert s["artist_id"] == conn.execute("SELECT id FROM artists").fetchone()[0]
    assert s["title"] == "Master of Puppets"


def test_new_artist_is_created(client, conn):
    client.post("/api/songs", json={"url": URL, "artist": "Black Sabbath"})
    assert conn.execute("SELECT name FROM artists").fetchone()[0] == "Black Sabbath"


def test_no_artist_lands_in_unsorted(client, conn):
    client.post("/api/songs", json={"url": URL})
    assert song(conn)["artist_id"] is None


@pytest.mark.parametrize("url", ["", "https://vimeo.com/123", "not a url", "E0ozmU9cJD"])
def test_invalid_url_is_422(client, conn, url):
    assert client.post("/api/songs", json={"url": url}).status_code == 422
    assert conn.execute("SELECT count(*) FROM songs").fetchone()[0] == 0


def test_placeholder_title_takes_youtube_title(client, conn, worker, fake, settings):
    (settings.originals_dir / f"{YID}.info.json").write_text('{"title": "Real title", "uploader": "Chan"}')
    client.post("/api/songs", json={"url": URL})
    worker.run_until_idle()
    s = song(conn)
    assert (s["title"], s["yt_title"], s["uploader"]) == ("Real title", "Real title", "Chan")


def test_given_title_is_kept_over_youtube_title(client, conn, worker, fake, settings):
    (settings.originals_dir / f"{YID}.info.json").write_text('{"title": "Real title"}')
    client.post("/api/songs", json={"url": URL, "title": "Mine"})
    worker.run_until_idle()
    assert song(conn)["title"] == "Mine"
