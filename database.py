"""SQLite connection and transaction helpers for the workout tracker."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "workout_tracker.db"


def get_db_path() -> Path:
    """Return the configured database path, creating its parent directory."""
    configured = os.getenv("WORKOUT_DB_PATH")
    path = Path(configured).expanduser().resolve() if configured else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Create a SQLite connection configured for this application."""
    path = Path(db_path).expanduser().resolve() if db_path else get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def connection_scope(
    db_path: Path | str | None = None,
) -> Iterator[sqlite3.Connection]:
    """Provide a read-oriented connection and always close it afterward."""
    connection = get_connection(db_path)
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def transaction(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """Commit a unit of work, or roll it back when an error is raised."""
    connection = get_connection(db_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
