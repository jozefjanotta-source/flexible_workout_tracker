"""Exercise-library operations."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from database import connection_scope, transaction


class ExerciseError(ValueError):
    """Raised when exercise input is invalid or conflicts with existing data."""


@dataclass(frozen=True)
class Exercise:
    id: int
    name: str
    primary_muscle_group: str
    equipment: str
    notes: str
    active: bool


def _validate(name: str, muscle_group: str, equipment: str) -> None:
    if not name.strip():
        raise ExerciseError("Exercise name is required.")
    if not muscle_group.strip():
        raise ExerciseError("Primary muscle group is required.")
    if not equipment.strip():
        raise ExerciseError("Equipment is required.")


def create_exercise(
    name: str,
    primary_muscle_group: str,
    equipment: str,
    notes: str = "",
    *,
    active: bool = True,
    db_path: Path | str | None = None,
) -> int:
    _validate(name, primary_muscle_group, equipment)
    try:
        with transaction(db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO exercises
                    (name, primary_muscle_group, equipment, notes, active)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    name.strip(),
                    primary_muscle_group.strip(),
                    equipment.strip(),
                    notes.strip(),
                    int(active),
                ),
            )
            return int(cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise ExerciseError(f"An exercise named '{name.strip()}' already exists.") from exc


def update_exercise(
    exercise_id: int,
    *,
    name: str,
    primary_muscle_group: str,
    equipment: str,
    notes: str,
    active: bool,
    db_path: Path | str | None = None,
) -> None:
    _validate(name, primary_muscle_group, equipment)
    try:
        with transaction(db_path) as connection:
            cursor = connection.execute(
                """
                UPDATE exercises
                SET name = ?, primary_muscle_group = ?, equipment = ?, notes = ?,
                    active = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    name.strip(),
                    primary_muscle_group.strip(),
                    equipment.strip(),
                    notes.strip(),
                    int(active),
                    exercise_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ExerciseError("Exercise not found.")
    except sqlite3.IntegrityError as exc:
        raise ExerciseError(f"An exercise named '{name.strip()}' already exists.") from exc


def set_exercise_active(
    exercise_id: int, active: bool, db_path: Path | str | None = None
) -> None:
    with transaction(db_path) as connection:
        cursor = connection.execute(
            "UPDATE exercises SET active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (int(active), exercise_id),
        )
        if cursor.rowcount == 0:
            raise ExerciseError("Exercise not found.")


def list_exercises(
    *, active_only: bool = False, db_path: Path | str | None = None
) -> list[Exercise]:
    query = "SELECT id, name, primary_muscle_group, equipment, notes, active FROM exercises"
    parameters: tuple[object, ...] = ()
    if active_only:
        query += " WHERE active = ?"
        parameters = (1,)
    query += " ORDER BY name COLLATE NOCASE"
    with connection_scope(db_path) as connection:
        rows = connection.execute(query, parameters).fetchall()
    return [
        Exercise(
            id=row["id"],
            name=row["name"],
            primary_muscle_group=row["primary_muscle_group"],
            equipment=row["equipment"],
            notes=row["notes"],
            active=bool(row["active"]),
        )
        for row in rows
    ]


def get_exercise(exercise_id: int, db_path: Path | str | None = None) -> Exercise:
    with connection_scope(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, name, primary_muscle_group, equipment, notes, active
            FROM exercises WHERE id = ?
            """,
            (exercise_id,),
        ).fetchone()
    if row is None:
        raise ExerciseError("Exercise not found.")
    return Exercise(
        id=row["id"],
        name=row["name"],
        primary_muscle_group=row["primary_muscle_group"],
        equipment=row["equipment"],
        notes=row["notes"],
        active=bool(row["active"]),
    )
