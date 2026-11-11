import pytest

from tunealong.guess import clean, guess


@pytest.mark.parametrize("yt_title, uploader, known, artist, title", [
    ("Black Sabbath - Paranoid (Official Video)", "BlackSabbathVEVO", [], "Black Sabbath", "Paranoid"),
    ("BLACK SABBATH – Iron Man [HD Remastered]", None, [], "BLACK SABBATH", "Iron Man"),
    ('Black Sabbath "War Pigs" (Live in Paris 1970)', None, [], "Black Sabbath", "War Pigs (Live in Paris 1970)"),
    ("Paranoid - Black Sabbath | Guitar Lesson", None, ["Black Sabbath"], "Black Sabbath", "Paranoid"),
    ("Paranoid - Black Sabbath", None, [], "Paranoid", "Black Sabbath"),  # unknown artist: take it as written
    ("Black Sabbath - Paranoid Guitar Backing Track", None, [], "Black Sabbath", "Paranoid"),
    ("Paranoid (2009 Remaster)", "Black Sabbath - Topic", [], "Black Sabbath", "Paranoid"),
    ("Paranoid (Official Audio)", "BlackSabbathVEVO", ["Black Sabbath"], "Black Sabbath", "Paranoid"),
    ("Paranoid", "Some Channel", ["Black Sabbath"], None, "Paranoid"),
    ("Backing track in A minor", None, [], None, "Backing track in A minor"),
    # Real oEmbed answers (2026-10-26).
    ('BLACK SABBATH - "Paranoid" (Official Video)', "Black Sabbath", [], "Black Sabbath", "Paranoid"),
    ("Numb (Official Music Video) [4K UPGRADE] – Linkin Park", "Linkin Park", [], "Linkin Park", "Numb"),
    ("Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)", "Rick Astley", [],
     "Rick Astley", "Never Gonna Give You Up"),
    ("Metallica: Enter Sandman (Official Music Video)", "Metallica", [], "Metallica", "Enter Sandman"),
    ("Guns N' Roses - Sweet Child O' Mine (Official Music Video)", "GunsNRosesVEVO", [],
     "Guns N' Roses", "Sweet Child O' Mine"),
    ("Lesson 1: Power Chords", "Marty Music", [], None, "Lesson 1: Power Chords"),
    ("black sabbath - paranoid", None, ["Black Sabbath"], "Black Sabbath", "paranoid"),
])
def test_guess(yt_title, uploader, known, artist, title):
    assert guess(yt_title, uploader, known) == {"artist": artist, "title": title}


def test_guess_nothing():
    assert guess(None) == {"artist": None, "title": None}
    assert guess("  ") == {"artist": None, "title": None}


def test_clean_keeps_meaningful_brackets():
    assert clean("Song (Acoustic) [Official Music Video]") == "Song (Acoustic)"


def test_camelcase_channel_orients_but_does_not_respell():
    assert guess("PARANOID - BLACK SABBATH", "BlackSabbathVEVO") == {"artist": "BLACK SABBATH", "title": "PARANOID"}
    assert guess("Numb - METALLICA", "Metallica") == {"artist": "Metallica", "title": "Numb"}
