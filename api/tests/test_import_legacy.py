import os
import shutil
import subprocess

import pytest

from tunealong import import_legacy, importer
from tunealong.media import sha256_file

from .conftest import FIXTURES


@pytest.fixture(scope="session")
def audio_m4a(tmp_path_factory):
    """A 2 s audio-only AAC file, for the audio/video twin tests."""
    out = tmp_path_factory.mktemp("audio") / "tone.m4a"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
         "-c:a", "aac", "-b:a", "64k", str(out)],
        check=True,
    )
    return out


@pytest.fixture
def legacy(tmp_path, audio_m4a):
    """A legacy MeTube folder with real-world names, outside TUNEALONG_ROOT."""
    d = tmp_path / "legacy"
    d.mkdir()
    src = FIXTURES / "originals"
    shutil.copy2(src / "AAAAAAAAAAA.webm", d / "Metallica - Master of Puppets [E0ozmU9cJDg].webm")
    shutil.copy2(src / "CCCCCCCCCCC.mp4", d / "Metallica - One.mp4")
    shutil.copy2(src / "BBBBBBBBBBB.webm", d / "Some Song (Backing Track).webm")
    shutil.copy2(audio_m4a, d / "Some Song (Backing Track).m4a")
    (d / "notes.txt").write_text("not media")
    (d / "Half done.webm.part").write_bytes(b"partial")
    return d


def snapshot(d):
    return {p.name: (sha256_file(p), p.stat().st_mtime_ns) for p in sorted(d.iterdir())}


def run(d, *args):
    assert import_legacy.main([str(d), *args]) == 0


def songs(conn):
    return conn.execute(
        "SELECT s.*, a.name AS artist FROM songs s LEFT JOIN artists a ON a.id = s.artist_id ORDER BY s.id"
    ).fetchall()


def test_guess():
    assert importer.guess("Metallica - Master of Puppets [E0ozmU9cJDg]") == (
        "E0ozmU9cJDg", "Metallica", "Master of Puppets")
    assert importer.guess("A - B - C") == (None, "A", "B - C")
    assert importer.guess("Just a title") == (None, None, "Just a title")
    assert importer.guess("Title [-AbCdEfGh_1]") == ("-AbCdEfGh_1", None, "Title")
    assert importer.guess("Tag [not-an-id]") == (None, None, "Tag [not-an-id]")


def test_id_suffix_becomes_youtube_song(conn, settings, legacy, capsys):
    run(legacy)
    s = [r for r in songs(conn) if r["youtube_id"]]
    assert len(s) == 1
    assert (s[0]["youtube_id"], s[0]["artist"], s[0]["title"], s[0]["status"]) == (
        "E0ozmU9cJDg", "Metallica", "Master of Puppets", "ready")
    assert s[0]["original_path"] == "originals/E0ozmU9cJDg.webm"
    assert (settings.originals_dir / "E0ozmU9cJDg.webm").is_file()


def test_no_id_becomes_local_song(conn, settings, legacy):
    sha = sha256_file(legacy / "Metallica - One.mp4")
    run(legacy)
    r = conn.execute("SELECT s.*, a.name AS artist FROM songs s JOIN artists a ON a.id = s.artist_id"
                     " WHERE s.title = 'One'").fetchone()
    assert r["youtube_id"] is None and r["artist"] == "Metallica"
    assert r["original_path"] == f"originals/local/{sha[:16]}.mp4"
    assert r["original_sha256"] == sha
    assert (settings.root / r["original_path"]).is_file()
    # Both Metallica files share one artist row.
    assert conn.execute("SELECT count(*) FROM artists").fetchone()[0] == 1


def test_no_separator_lands_in_unsorted(conn, settings, legacy):
    run(legacy)
    r = conn.execute("SELECT * FROM songs WHERE title = 'Some Song (Backing Track)'").fetchone()
    assert r["artist_id"] is None


def test_audio_twin_is_skipped_for_video(conn, settings, legacy, capsys):
    run(legacy)
    rows = conn.execute("SELECT original_path FROM songs WHERE title = 'Some Song (Backing Track)'").fetchall()
    assert [r[0].rsplit(".", 1)[1] for r in rows] == ["webm"]
    assert "twin-skipped" in capsys.readouterr().out


def test_lone_audio_file_is_imported(conn, settings, tmp_path, audio_m4a):
    d = tmp_path / "audio_only"
    d.mkdir()
    shutil.copy2(audio_m4a, d / "Ozzy - Backing.m4a")
    run(d)
    r = conn.execute("SELECT * FROM songs").fetchone()
    assert r["title"] == "Backing" and r["original_path"].endswith(".m4a")


def test_importing_twice_creates_no_duplicates(conn, settings, legacy, capsys):
    run(legacy)
    n = conn.execute("SELECT count(*) FROM songs").fetchone()[0]
    assert n == 3
    capsys.readouterr()
    run(legacy)
    assert conn.execute("SELECT count(*) FROM songs").fetchone()[0] == n
    assert "duplicate: 3" in capsys.readouterr().out


def test_same_content_twice_in_one_folder(conn, settings, legacy):
    shutil.copy2(legacy / "Metallica - One.mp4", legacy / "Metallica - One (copy).mp4")
    run(legacy)
    assert conn.execute("SELECT count(*) FROM songs WHERE title LIKE 'One%'").fetchone()[0] == 1


def test_sources_untouched(conn, settings, legacy):
    before = snapshot(legacy)
    run(legacy)
    assert snapshot(legacy) == before


def test_dry_run_changes_nothing(conn, settings, legacy, capsys):
    disk_before = sorted(p.relative_to(settings.root) for p in settings.root.rglob("*"))
    src_before = snapshot(legacy)
    run(legacy, "--dry-run")
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "Master of Puppets" in out and "import-local" in out
    assert conn.execute("SELECT count(*) FROM songs").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM artists").fetchone()[0] == 0
    assert sorted(p.relative_to(settings.root) for p in settings.root.rglob("*")) == disk_before
    assert snapshot(legacy) == src_before


def test_dry_run_without_db_creates_no_db(settings, legacy, capsys):
    assert not settings.db_path.exists()
    run(legacy, "--dry-run")
    assert not settings.db_path.exists()


def test_unsupported_files_are_skipped_and_reported(conn, settings, legacy, capsys):
    run(legacy)
    out = capsys.readouterr().out
    assert "notes.txt" in out and "Half done.webm.part" in out
    assert "unsupported: 2" in out
    assert conn.execute("SELECT count(*) FROM songs WHERE title LIKE '%notes%' OR title LIKE '%Half%'"
                        ).fetchone()[0] == 0


def test_hardlinks_on_same_filesystem(conn, settings, legacy):
    run(legacy)
    src = legacy / "Metallica - Master of Puppets [E0ozmU9cJDg].webm"
    assert os.path.samefile(src, settings.originals_dir / "E0ozmU9cJDg.webm")


def test_copy_fallback_when_link_fails(conn, settings, legacy, monkeypatch):
    import errno

    def no_link(*a):
        raise OSError(errno.EXDEV, "cross-device")

    monkeypatch.setattr(os, "link", no_link)
    run(legacy)
    dest = settings.originals_dir / "E0ozmU9cJDg.webm"
    assert dest.is_file() and not os.path.samefile(legacy / "Metallica - Master of Puppets [E0ozmU9cJDg].webm", dest)
    assert not list(settings.originals_dir.rglob(".*.tmp"))
