"""Pydantic request/response models."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

Name = Annotated[str, Field(min_length=1, max_length=200)]


class _Strict(BaseModel):
    model_config = {"extra": "forbid", "str_strip_whitespace": True}


class SongAdd(_Strict):
    url: str = Field(min_length=1)
    artist: str | None = None
    title: str | None = None


class SongPatch(_Strict):
    artist_id: int | None = None
    artist_name: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    notes: str | None = None
    tab_track: int | None = Field(default=None, ge=0, le=999)

    @model_validator(mode="after")
    def _one_artist_field(self):
        if {"artist_id", "artist_name"} <= self.model_fields_set:
            raise ValueError("give artist_id or artist_name, not both")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title can't be null")
        return self


class LinkIn(_Strict):
    url: str = Field(min_length=1)


class ArtistIn(_Strict):
    name: Name
    sort_order: int | None = None
    columns: int = Field(default=4, ge=1, le=8)
    style: Literal["row", "column"] = "row"


class ArtistPatch(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sort_order: int | None = None
    columns: int | None = Field(default=None, ge=1, le=8)
    style: Literal["row", "column"] | None = None


class CategoryIn(_Strict):
    name: Name
    colour: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    sort_order: int | None = None


class CategoryPatch(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    colour: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    sort_order: int | None = None


class PresetIn(_Strict):
    name: Name
    semitones: float = Field(default=0.0, ge=-12, le=12)
    tempo: float = Field(default=1.0, ge=0.25, le=2.0)
    # Rubber Band renders tempo too, unless a client asks for live tempo only.
    bake_tempo: bool = True
    loop_a: float | None = Field(default=None, ge=0)
    loop_b: float | None = Field(default=None, ge=0)
    is_default: bool = False
    volume: float | None = Field(default=None, ge=0, le=2)  # None = the browser's

    @model_validator(mode="after")
    def _loop_order(self):
        if self.loop_a is not None and self.loop_b is not None and self.loop_a >= self.loop_b:
            raise ValueError("loop_a must be before loop_b")
        return self


class PresetPatch(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    semitones: float | None = None
    tempo: float | None = None
    bake_tempo: bool | None = None
    loop_a: float | None = None
    loop_b: float | None = None
    is_default: bool | None = None
    volume: float | None = None


class Reorder(_Strict):
    scope: Literal["artists", "categories", "songs"]
    group_id: int | None = None  # songs: the artist id, or null for Unsorted
    ids: list[int] = Field(min_length=1)
