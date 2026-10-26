"""The real ffmpeg + rubberband pipeline. Needs `rubberband` on PATH; run the
whole suite in Docker with `make test-docker` to be sure nothing is skipped."""

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from songbook import render
from songbook.cache import cache_key

pytestmark = pytest.mark.skipif(shutil.which("rubberband") is None, reason="rubberband not installed")

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "originals"
SR = 48000


def decode(path: Path) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32)


def dominant_hz(samples: np.ndarray) -> float:
    # Middle 60%, Hann window, parabolic interpolation around the peak bin.
    n = len(samples)
    seg = samples[int(n * 0.2):int(n * 0.8)]
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    k = int(np.argmax(spec[1:])) + 1
    a, b, c = np.log(spec[k - 1:k + 2] + 1e-12)
    k += 0.5 * (a - c) / (a - 2 * b + c)
    return k * SR / len(seg)


def duration(path: Path) -> float:
    return len(decode(path)) / SR


def video_md5(path: Path) -> str:
    return subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:v", "-c", "copy",
                           "-f", "md5", "-"], capture_output=True, check=True, text=True).stdout.strip()


def make_job(src: Path, out_dir: Path, semitones=0.0, tempo=1.0, bake=False) -> render.Job:
    return render.Job(original=src, out_dir=out_dir, key=cache_key(semitones, tempo, bake),
                      semitones=semitones, tempo=tempo, bake_tempo=bake)


@pytest.fixture
def tone(tmp_path) -> Path:
    # A name starting with '-' proves every path reaches the tools as absolute.
    dst = tmp_path / "-tone440AAAA.webm"
    shutil.copy(FIXTURES / "AAAAAAAAAAA.webm", dst)
    return dst


@pytest.fixture
def out(tmp_path) -> Path:
    return tmp_path / "renders" / "1"


def test_tone_fixture_is_440(tone):
    assert dominant_hz(decode(tone)) == pytest.approx(440, abs=1)


def test_plus_two_semitones(tone, out):
    f = render.render(make_job(tone, out, semitones=2))
    assert f.name == "p+2.00_t1.000_bt0_rb3-v1.webm"
    assert dominant_hz(decode(f)) == pytest.approx(493.9, abs=3)


def test_minus_twelve_semitones(tone, out):
    f = render.render(make_job(tone, out, semitones=-12))
    assert dominant_hz(decode(f)) == pytest.approx(220, abs=2)


@pytest.mark.parametrize("name", ["AAAAAAAAAAA.webm", "CCCCCCCCCCC.mp4"])
def test_pitch_only_keeps_duration_and_video(tmp_path, out, name):
    src = tmp_path / name
    shutil.copy(FIXTURES / name, src)
    f = render.render(make_job(src, out, semitones=3))
    assert f.suffix == src.suffix
    assert abs(duration(f) - duration(src)) <= 0.050
    assert video_md5(f) == video_md5(src)
    assert dominant_hz(decode(f)) == pytest.approx(440 * 2 ** (3 / 12), abs=3)


def test_mkv_keeps_container_and_video(tmp_path, out):
    src = tmp_path / "DDDDDDDDDDD.mkv"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(FIXTURES / "AAAAAAAAAAA.webm"), "-c", "copy",
                    str(src)], check=True)
    f = render.render(make_job(src, out, semitones=-1))
    assert f.suffix == ".mkv" and video_md5(f) == video_md5(src)


def test_audio_only_original(tmp_path, out):
    src = tmp_path / "EEEEEEEEEEE.mp3"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
                    "-ar", "48000", "-c:a", "libmp3lame", str(src)], check=True)
    f = render.render(make_job(src, out, semitones=2))
    assert f.suffix == ".m4a"
    assert not render.has_video(f)
    assert dominant_hz(decode(f)) == pytest.approx(493.9, abs=3)
    assert abs(duration(f) - duration(src)) <= 0.050


def test_baked_half_tempo(tone, out):
    f = render.render(make_job(tone, out, tempo=0.5, bake=True))
    assert f.name == "p+0.00_t0.500_bt1_rb3-v1.webm"
    assert duration(f) == pytest.approx(2 * duration(tone), abs=0.15)
    assert dominant_hz(decode(f)) == pytest.approx(440, abs=3)
    v = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(f)], capture_output=True, text=True, check=True).stdout
    assert float(v) == pytest.approx(20, abs=0.3)


def test_killed_subprocess_leaves_no_visible_file_and_retry_works(tone, out, monkeypatch):
    real_run = render.run

    def killed_on_mux(cmd, timeout=None):
        if "-f" in cmd:  # the final remux: start it, then kill it mid-flight
            p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            p.kill()
            p.wait()
            raise render.RenderError(f"killed: {p.returncode}")
        return real_run(cmd, timeout)

    job = make_job(tone, out, semitones=2)
    monkeypatch.setattr(render, "run", killed_on_mux)
    with pytest.raises(render.RenderError):
        render.render(job)
    assert list(out.iterdir()) == []

    monkeypatch.setattr(render, "run", real_run)
    f = render.render(job)
    assert [p.name for p in out.iterdir()] == [f.name]


def test_leftovers_from_a_hard_crash_are_cleaned(tone, out):
    job = make_job(tone, out, semitones=1)
    out.mkdir(parents=True)
    (out / f".{job.key}.tmp.webm").write_bytes(b"partial")
    (out / f".{job.key}.work").mkdir()
    (out / f".{job.key}.work" / "in.wav").write_bytes(b"partial")
    f = render.render(job)
    assert [p.name for p in out.iterdir()] == [f.name]


def test_tool_failure_is_reported(tmp_path, out):
    bad = tmp_path / "FFFFFFFFFFF.webm"
    bad.write_bytes(b"not media")
    with pytest.raises(render.RenderError, match="ffmpeg exited"):
        render.render(make_job(bad, out, semitones=2))
    assert list(out.iterdir()) == []
