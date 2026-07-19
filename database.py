"""Local SQLite and optional Turso Cloud database helpers."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
from typing import Any, Iterator, Sequence

import certifi


DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "workout_tracker.db"
DEFAULT_CLOUD_CACHE_PATH = Path("/tmp/flexible_workout_tracker_cloud.db")
_DATABASE_LOCK = RLock()

# Python installations on macOS do not always expose a complete system CA bundle.
# Turso's sync client respects SSL_CERT_FILE, so provide certifi's maintained
# bundle while still allowing an explicit deployment setting to take precedence.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

try:
    import turso

    INTEGRITY_ERRORS = (sqlite3.IntegrityError, turso.IntegrityError)
except ImportError:  # Local-only installations remain supported.
    INTEGRITY_ERRORS = (sqlite3.IntegrityError,)


class MappingRow(Sequence[object]):
    """A SQLite-row-compatible result for Turso's DB-API cursor."""

    def __init__(self, columns: list[str], values: Sequence[object]) -> None:
        self._columns = columns
        self._values = tuple(values)
        self._positions = {name: index for index, name in enumerate(columns)}

    def __getitem__(self, key: int | slice | str) -> object:
        if isinstance(key, str):
            return self._values[self._positions[key]]
        return self._values[key]

    def __len__(self) -> int:
        return len(self._values)

    def keys(self) -> list[str]:
        return self._columns.copy()


def get_db_path() -> Path:
    """Return the configured database path, creating its parent directory."""
    configured = os.getenv("WORKOUT_DB_PATH")
    if configured:
        path = Path(configured).expanduser().resolve()
    elif _uses_turso():
        cloud_cache = os.getenv("TURSO_LOCAL_DB_PATH")
        path = (
            Path(cloud_cache).expanduser().resolve()
            if cloud_cache
            else DEFAULT_CLOUD_CACHE_PATH
        )
    else:
        path = DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection(db_path: Path | str | None = None) -> Any:
    """Create a configured local SQLite or Turso-compatible connection."""
    path = Path(db_path).expanduser().resolve() if db_path else get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if _uses_turso():
        connection = _get_turso_connection(path)
        connection.row_factory = _turso_row_factory
    else:
        connection = sqlite3.connect(path, timeout=10)
        connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def _uses_turso() -> bool:
    return bool(os.getenv("TURSO_DATABASE_URL")) or os.getenv(
        "WORKOUT_DB_BACKEND", ""
    ).casefold() == "turso"


def _get_turso_connection(path: Path) -> Any:
    try:
        remote_url = os.getenv("TURSO_DATABASE_URL")
        if remote_url:
            import turso.sync

            auth_token = os.getenv("TURSO_AUTH_TOKEN")
            if not auth_token:
                raise RuntimeError(
                    "TURSO_AUTH_TOKEN is required when TURSO_DATABASE_URL is configured."
                )
            return turso.sync.connect(
                str(path),
                remote_url=remote_url,
                auth_token=auth_token,
            )
        import turso

        return turso.connect(str(path))
    except ImportError as exc:
        raise RuntimeError(
            "Turso is configured but pyturso is not installed. Install requirements.txt."
        ) from exc


def _turso_row_factory(cursor: Any, row: Sequence[object]) -> MappingRow:
    columns = [str(description[0]) for description in cursor.description]
    return MappingRow(columns, row)


def _pull_remote(connection: Any) -> None:
    pull = getattr(connection, "pull", None)
    if callable(pull):
        pull()


def _push_remote(connection: Any) -> None:
    push = getattr(connection, "push", None)
    if callable(push):
        push()


@contextmanager
def connection_scope(
    db_path: Path | str | None = None,
) -> Iterator[Any]:
    """Provide a read-oriented connection and always close it afterward."""
    with _DATABASE_LOCK:
        connection = get_connection(db_path)
        try:
            _pull_remote(connection)
            yield connection
        finally:
            connection.close()


@contextmanager
def transaction(db_path: Path | str | None = None) -> Iterator[Any]:
    """Commit a unit of work, or roll it back when an error is raised."""
    with _DATABASE_LOCK:
        connection = get_connection(db_path)
        try:
            _pull_remote(connection)
            yield connection
            connection.commit()
            _push_remote(connection)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def create_database_backup(db_path: Path | str | None = None) -> bytes:
    """Return a consistent SQLite backup suitable for downloading or archiving."""
    with TemporaryDirectory() as temp_dir:
        backup_path = Path(temp_dir) / "workout_tracker_backup.db"
        if _uses_turso():
            source_path = (
                Path(db_path).expanduser().resolve() if db_path else get_db_path()
            )
            with _DATABASE_LOCK:
                connection = get_connection(source_path)
                try:
                    _pull_remote(connection)
                    checkpoint = getattr(connection, "checkpoint", None)
                    if callable(checkpoint):
                        checkpoint()
                finally:
                    connection.close()
                source = sqlite3.connect(source_path)
                destination = sqlite3.connect(backup_path)
                try:
                    source.backup(destination)
                    destination.commit()
                finally:
                    source.close()
                    destination.close()
        else:
            with connection_scope(db_path) as source:
                destination = sqlite3.connect(backup_path)
                try:
                    source.backup(destination)
                    destination.commit()
                finally:
                    destination.close()
        return backup_path.read_bytes()
