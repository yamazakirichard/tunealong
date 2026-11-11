"""SQLite access: connection setup and a tiny forward-only migration runner.

Migration 1 is schema.sql. Later migrations go in migrations/NNNN_name.sql and
are applied in filename order. Applied versions are recorded in schema_version.
"""

import sqlite3
from importlib import resources
from pathlib import Path

_PKG = resources.files("tunealong")


def migrations() -> list[str]:
    """All migration scripts, in order. Index + 1 is the version number."""
    scripts = [(_PKG / "schema.sql").read_text()]
    mig_dir = _PKG / "migrations"
    if mig_dir.is_dir():
        files = sorted(f for f in mig_dir.iterdir() if f.name.endswith(".sql"))
        scripts += [f.read_text() for f in files]
    return scripts


def connect(path: Path | str, busy_timeout_ms: int = 5000) -> sqlite3.Connection:
    """Open a connection with the pragmas every connection needs.

    Autocommit mode (isolation_level=None): callers use explicit
    BEGIN/COMMIT, or the `transaction()` helper.
    """
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


class transaction:
    """`with transaction(conn):` runs the block in BEGIN IMMEDIATE … COMMIT."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")


def schema_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        " version INTEGER PRIMARY KEY,"
        " applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    return conn.execute("SELECT coalesce(max(version), 0) FROM schema_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations. Returns the resulting schema version.

    Each migration runs in its own BEGIN IMMEDIATE transaction, and the version
    is re-read under that lock, so the api and worker can both start at once.
    """
    scripts = migrations()
    schema_version(conn)
    for version, sql in enumerate(scripts, start=1):
        conn.execute("BEGIN IMMEDIATE")
        try:
            if schema_version(conn) >= version:
                conn.execute("COMMIT")
                continue
            # executescript() would COMMIT first, so run statement by statement.
            for stmt in _split(sql):
                conn.execute(stmt)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return schema_version(conn)


def _split(sql: str) -> list[str]:
    """Split a script into complete statements (sqlite3.complete_statement aware)."""
    stmts, buf = [], ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                stmts.append(buf)
            buf = ""
    leftover = [l for l in buf.splitlines() if l.strip() and not l.strip().startswith("--")]
    if leftover:
        raise ValueError(f"incomplete SQL statement at end of migration: {leftover[0]!r}")
    return stmts


def open_db(path: Path | str, busy_timeout_ms: int = 5000) -> sqlite3.Connection:
    """Connect and bring the schema up to date."""
    conn = connect(path, busy_timeout_ms)
    migrate(conn)
    return conn
