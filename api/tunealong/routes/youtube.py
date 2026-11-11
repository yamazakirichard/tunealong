"""Look a video up before adding it, so the form can be pre-filled."""

import logging
import sqlite3

import httpx
from fastapi import APIRouter, Depends, HTTPException

from .. import config
from ..deps import get_conn, get_settings
from ..guess import guess
from ..youtube import oembed, parse_id

router = APIRouter(prefix="/api")
log = logging.getLogger(__name__)


@router.get("/youtube")
def youtube_info(url: str, conn: sqlite3.Connection = Depends(get_conn),
                 settings: config.Settings = Depends(get_settings)) -> dict:
    """The video's YouTube title and channel, plus a guessed artist and title.

    Unknown fields are null when YouTube can't be asked or won't say; adding
    the song still works, it just isn't pre-filled.
    """
    try:
        yid = parse_id(url)
    except ValueError as e:
        raise HTTPException(422, str(e))
    yt_title = uploader = None
    if settings.oembed_url:
        try:
            yt_title, uploader = oembed(settings.oembed_url, yid)
        except (httpx.HTTPError, ValueError) as e:
            log.info("oEmbed lookup for %s failed: %s", yid, e)
    known = [r["name"] for r in conn.execute("SELECT name FROM artists")]
    song = conn.execute("SELECT id FROM songs WHERE youtube_id = ?", (yid,)).fetchone()
    return {"youtube_id": yid, "yt_title": yt_title, "uploader": uploader,
            "in_library": song is not None, **guess(yt_title, uploader, known)}
