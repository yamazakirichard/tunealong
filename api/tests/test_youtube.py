import pytest

from tunealong.youtube import parse_id

ID = "E0ozmU9cJDg"

VALID = [
    (ID, ID),
    (f"  {ID}  ", ID),
    ("-AbCdEfGh_1", "-AbCdEfGh_1"),
    (f"https://www.youtube.com/watch?v={ID}", ID),
    (f"https://youtube.com/watch?v={ID}&t=42s", ID),
    (f"https://www.youtube.com/watch?v={ID}&list=PL1234567890&index=3", ID),
    (f"https://www.youtube.com/watch?feature=share&v={ID}", ID),
    (f"https://m.youtube.com/watch?v={ID}", ID),
    (f"https://music.youtube.com/watch?v={ID}&si=abcDEF123", ID),
    (f"https://youtu.be/{ID}", ID),
    (f"https://youtu.be/{ID}?si=XyZ123&t=10", ID),
    (f"youtu.be/{ID}", ID),
    (f"www.youtube.com/watch?v={ID}", ID),
    (f"https://www.youtube.com/shorts/{ID}", ID),
    (f"https://www.youtube.com/embed/{ID}?start=5", ID),
    (f"https://www.youtube-nocookie.com/embed/{ID}", ID),
    (f"https://www.youtube.com/live/{ID}?feature=shared", ID),
    (f"http://WWW.YOUTUBE.COM/watch?v={ID}", ID),
]

INVALID = [
    "",
    "E0ozmU9cJD",                                     # 10 chars
    "E0ozmU9cJDgX",                                   # 12 chars
    "E0ozmU9cJ!g",                                    # bad char
    f"https://www.youtube.com/watch?v={ID}X",
    "https://www.youtube.com/watch?list=PL1234567890",
    f"https://vimeo.com/{ID}",
    f"https://notyoutube.com/watch?v={ID}",
    "https://www.youtube.com/channel/UCabcdefghijk",
    "https://www.youtube.com/@someone",
    "https://youtu.be/",
    "not a url at all",
]


@pytest.mark.parametrize("url,expected", VALID)
def test_valid(url, expected):
    assert parse_id(url) == expected


@pytest.mark.parametrize("url", INVALID)
def test_invalid(url):
    with pytest.raises(ValueError):
        parse_id(url)
