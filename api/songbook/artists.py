"""Artist lookups shared by the API and the importer."""

import sqlite3


def get_or_create(conn: sqlite3.Connection, name: str) -> int:
    """Case-insensitive match on the NOCASE `name` column, else insert."""
    row = conn.execute("SELECT id FROM artists WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    return conn.execute("INSERT INTO artists (name) VALUES (?)", (name,)).lastrowid
