"""Training-profile creation, editing, and selection helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from database import INTEGRITY_ERRORS, connection_scope, transaction


class ProfileError(ValueError):
    """Raised when a training profile cannot be created or updated."""


@dataclass(frozen=True)
class Profile:
    id: int
    name: str
    notes: str
    active: bool


def create_profile(
    name: str,
    notes: str = "",
    *,
    active: bool = True,
    db_path: Path | str | None = None,
) -> int:
    """Create a profile without affecting shared routines or exercises."""
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ProfileError("Profile name is required.")
    try:
        with transaction(db_path) as connection:
            cursor = connection.execute(
                "INSERT INTO profiles (name, notes, active) VALUES (?, ?, ?)",
                (cleaned_name, notes.strip(), int(active)),
            )
            return int(cursor.lastrowid)
    except INTEGRITY_ERRORS as exc:
        raise ProfileError(f"A profile named '{cleaned_name}' already exists.") from exc


def update_profile(
    profile_id: int,
    *,
    name: str,
    notes: str,
    active: bool,
    db_path: Path | str | None = None,
) -> None:
    """Edit or archive a profile while retaining all of its history."""
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ProfileError("Profile name is required.")
    try:
        with transaction(db_path) as connection:
            current = connection.execute(
                "SELECT active FROM profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            if current is None:
                raise ProfileError("Profile not found.")
            if bool(current["active"]) and not active:
                active_count = connection.execute(
                    "SELECT COUNT(*) FROM profiles WHERE active = 1"
                ).fetchone()[0]
                if active_count <= 1:
                    raise ProfileError("At least one profile must remain active.")
            connection.execute(
                """
                UPDATE profiles
                SET name = ?, notes = ?, active = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (cleaned_name, notes.strip(), int(active), profile_id),
            )
    except INTEGRITY_ERRORS as exc:
        raise ProfileError(f"A profile named '{cleaned_name}' already exists.") from exc


def list_profiles(
    *, active_only: bool = False, db_path: Path | str | None = None
) -> list[Profile]:
    """Return profiles alphabetically, optionally excluding archived profiles."""
    query = "SELECT id, name, notes, active FROM profiles"
    if active_only:
        query += " WHERE active = 1"
    query += " ORDER BY name COLLATE NOCASE"
    with connection_scope(db_path) as connection:
        rows = connection.execute(query).fetchall()
    return [
        Profile(row["id"], row["name"], row["notes"], bool(row["active"]))
        for row in rows
    ]


def default_profile_id(*, db_path: Path | str | None = None) -> int:
    """Return a stable active profile for backward-compatible service calls."""
    with connection_scope(db_path) as connection:
        row = connection.execute(
            "SELECT id FROM profiles WHERE active = 1 ORDER BY id LIMIT 1"
        ).fetchone()
    if row is None:
        raise ProfileError("Create or reactivate a profile before logging a workout.")
    return int(row["id"])
