"""Pydantic request/response models."""

from pydantic import BaseModel, Field


class SongAdd(BaseModel):
    url: str = Field(min_length=1)
    artist: str | None = None
    title: str | None = None


class Song(BaseModel):
    id: int
    youtube_id: str | None
    artist_id: int | None
    title: str
    yt_title: str | None
    uploader: str | None
    status: str
    error: str | None
    added_at: str


class SongAdded(BaseModel):
    song: Song
    duplicate: bool = False
