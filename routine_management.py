"""Routine, workout, and workout-exercise configuration operations."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from database import INTEGRITY_ERRORS, connection_scope, transaction


class RoutineError(ValueError):
    """Raised when routine configuration is invalid."""


@dataclass(frozen=True)
class Routine:
    id: int
    name: str
    description: str
    frequency_days: int
    active: bool


@dataclass(frozen=True)
class Workout:
    id: int
    routine_id: int
    name: str
    description: str
    position: int
    active: bool


@dataclass(frozen=True)
class WorkoutExercise:
    id: int
    workout_id: int
    exercise_id: int
    exercise_name: str
    primary_muscle_group: str
    equipment: str
    position: int
    target_min_reps: int
    target_max_reps: int
    target_sets: int
    instructions: str


@dataclass(frozen=True)
class NextWorkoutStatus:
    routine_id: int
    routine_name: str
    frequency_days: int
    workout_id: int
    workout_name: str
    last_workout_name: str | None
    last_completed_at: datetime | None
    days_since_last_workout: int | None
    due_date: date | None
    is_due: bool


def create_routine(
    name: str,
    description: str = "",
    *,
    active: bool = True,
    frequency_days: int = 6,
    db_path: Path | str | None = None,
) -> int:
    if not name.strip():
        raise RoutineError("Routine name is required.")
    if frequency_days < 1:
        raise RoutineError("Frequency must be at least 1 day.")
    try:
        with transaction(db_path) as connection:
            cursor = connection.execute(
                "INSERT INTO routines (name, description, frequency_days, active) VALUES (?, ?, ?, ?)",
                (name.strip(), description.strip(), frequency_days, int(active)),
            )
            routine_id = int(cursor.lastrowid)
            if active:
                connection.execute(
                    "UPDATE profiles SET active_routine_id = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE active_routine_id IS NULL",
                    (routine_id,),
                )
            return routine_id
    except INTEGRITY_ERRORS as exc:
        raise RoutineError(f"A routine named '{name.strip()}' already exists.") from exc


def duplicate_routine(
    routine_id: int,
    new_name: str,
    *,
    db_path: Path | str | None = None,
) -> int:
    """Copy an active routine structure without copying any training history."""
    if not new_name.strip():
        raise RoutineError("New routine name is required.")
    try:
        with transaction(db_path) as connection:
            source = connection.execute(
                "SELECT description, frequency_days FROM routines WHERE id = ?", (routine_id,)
            ).fetchone()
            if source is None:
                raise RoutineError("Source routine not found.")
            routine_cursor = connection.execute(
                "INSERT INTO routines (name, description, frequency_days, active) VALUES (?, ?, ?, 1)",
                (new_name.strip(), source["description"], source["frequency_days"]),
            )
            new_routine_id = int(routine_cursor.lastrowid)
            workouts = connection.execute(
                """
                SELECT id, name, description, position FROM workouts
                WHERE routine_id = ? AND active = 1 ORDER BY position, id
                """,
                (routine_id,),
            ).fetchall()
            for workout in workouts:
                workout_cursor = connection.execute(
                    """
                    INSERT INTO workouts
                        (routine_id, name, description, position, active)
                    VALUES (?, ?, ?, ?, 1)
                    """,
                    (
                        new_routine_id,
                        workout["name"],
                        workout["description"],
                        workout["position"],
                    ),
                )
                new_workout_id = int(workout_cursor.lastrowid)
                connection.execute(
                    """
                    INSERT INTO workout_exercises
                        (workout_id, exercise_id, position, target_min_reps,
                         target_max_reps, target_sets, instructions, active)
                    SELECT ?, exercise_id, position, target_min_reps,
                           target_max_reps, target_sets, instructions, 1
                    FROM workout_exercises
                    WHERE workout_id = ? AND active = 1
                    ORDER BY position, id
                    """,
                    (new_workout_id, workout["id"]),
                )
            return new_routine_id
    except INTEGRITY_ERRORS as exc:
        raise RoutineError(f"A routine named '{new_name.strip()}' already exists.") from exc


def update_routine(
    routine_id: int,
    *,
    name: str,
    description: str,
    active: bool,
    frequency_days: int = 6,
    db_path: Path | str | None = None,
) -> None:
    if not name.strip():
        raise RoutineError("Routine name is required.")
    if frequency_days < 1:
        raise RoutineError("Frequency must be at least 1 day.")
    try:
        with transaction(db_path) as connection:
            cursor = connection.execute(
                """
                UPDATE routines SET name = ?, description = ?, frequency_days = ?, active = ?,
                    updated_at = CURRENT_TIMESTAMP WHERE id = ?
                """,
                (name.strip(), description.strip(), frequency_days, int(active), routine_id),
            )
            if cursor.rowcount == 0:
                raise RoutineError("Routine not found.")
    except INTEGRITY_ERRORS as exc:
        raise RoutineError(f"A routine named '{name.strip()}' already exists.") from exc


def list_routines(
    *, active_only: bool = False, db_path: Path | str | None = None
) -> list[Routine]:
    query = "SELECT id, name, description, frequency_days, active FROM routines"
    params: tuple[object, ...] = ()
    if active_only:
        query += " WHERE active = 1"
    query += " ORDER BY name COLLATE NOCASE"
    with connection_scope(db_path) as connection:
        rows = connection.execute(query, params).fetchall()
    return [
        Routine(
            row["id"], row["name"], row["description"],
            row["frequency_days"], bool(row["active"])
        )
        for row in rows
    ]


def next_workout_status(
    profile_id: int,
    *,
    today: date | None = None,
    db_path: Path | str | None = None,
) -> NextWorkoutStatus | None:
    """Return the next active workout in the selected profile's routine rotation."""
    current_date = today or date.today()
    with connection_scope(db_path) as connection:
        routine = connection.execute(
            """
            SELECT r.id, r.name, r.frequency_days
            FROM profiles p JOIN routines r ON r.id = p.active_routine_id
            WHERE p.id = ? AND p.active = 1 AND r.active = 1
            """,
            (profile_id,),
        ).fetchone()
        if routine is None:
            return None
        workouts = connection.execute(
            """
            SELECT id, name FROM workouts
            WHERE routine_id = ? AND active = 1 ORDER BY position, id
            """,
            (routine["id"],),
        ).fetchall()
        if not workouts:
            return None
        last = connection.execute(
            """
            SELECT workout_id, workout_name, completed_at
            FROM workout_sessions
            WHERE profile_id = ? AND routine_id = ?
            ORDER BY completed_at DESC, id DESC LIMIT 1
            """,
            (profile_id, routine["id"]),
        ).fetchone()

    next_index = 0
    if last is not None:
        matching_index = next(
            (index for index, workout in enumerate(workouts) if workout["id"] == last["workout_id"]),
            None,
        )
        if matching_index is not None:
            next_index = (matching_index + 1) % len(workouts)
    next_workout = workouts[next_index]
    last_completed_at = (
        datetime.fromisoformat(last["completed_at"]) if last is not None else None
    )
    due_date = (
        last_completed_at.date() + timedelta(days=routine["frequency_days"])
        if last_completed_at is not None
        else None
    )
    return NextWorkoutStatus(
        routine_id=int(routine["id"]),
        routine_name=str(routine["name"]),
        frequency_days=int(routine["frequency_days"]),
        workout_id=int(next_workout["id"]),
        workout_name=str(next_workout["name"]),
        last_workout_name=str(last["workout_name"]) if last is not None else None,
        last_completed_at=last_completed_at,
        days_since_last_workout=(current_date - last_completed_at.date()).days if last_completed_at else None,
        due_date=due_date,
        is_due=due_date is None or current_date >= due_date,
    )


def create_workout(
    routine_id: int,
    name: str,
    description: str = "",
    *,
    db_path: Path | str | None = None,
) -> int:
    if not name.strip():
        raise RoutineError("Workout name is required.")
    try:
        with transaction(db_path) as connection:
            position = connection.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM workouts WHERE routine_id = ?",
                (routine_id,),
            ).fetchone()[0]
            cursor = connection.execute(
                """
                INSERT INTO workouts (routine_id, name, description, position)
                VALUES (?, ?, ?, ?)
                """,
                (routine_id, name.strip(), description.strip(), position),
            )
            return int(cursor.lastrowid)
    except INTEGRITY_ERRORS as exc:
        raise RoutineError("That workout name is already used in this routine.") from exc


def update_workout(
    workout_id: int,
    *,
    name: str,
    description: str,
    active: bool,
    db_path: Path | str | None = None,
) -> None:
    if not name.strip():
        raise RoutineError("Workout name is required.")
    try:
        with transaction(db_path) as connection:
            cursor = connection.execute(
                """
                UPDATE workouts SET name = ?, description = ?, active = ?,
                    updated_at = CURRENT_TIMESTAMP WHERE id = ?
                """,
                (name.strip(), description.strip(), int(active), workout_id),
            )
            if cursor.rowcount == 0:
                raise RoutineError("Workout not found.")
    except INTEGRITY_ERRORS as exc:
        raise RoutineError("That workout name is already used in this routine.") from exc


def list_workouts(
    routine_id: int,
    *,
    active_only: bool = False,
    db_path: Path | str | None = None,
) -> list[Workout]:
    query = """
        SELECT id, routine_id, name, description, position, active
        FROM workouts WHERE routine_id = ?
    """
    params: list[object] = [routine_id]
    if active_only:
        query += " AND active = 1"
    query += " ORDER BY position, id"
    with connection_scope(db_path) as connection:
        rows = connection.execute(query, params).fetchall()
    return [
        Workout(row["id"], row["routine_id"], row["name"], row["description"], row["position"], bool(row["active"]))
        for row in rows
    ]


def add_exercise_to_workout(
    workout_id: int,
    exercise_id: int,
    *,
    target_min_reps: int,
    target_max_reps: int,
    target_sets: int,
    instructions: str = "",
    db_path: Path | str | None = None,
) -> int:
    _validate_targets(target_min_reps, target_max_reps, target_sets)
    try:
        with transaction(db_path) as connection:
            position = connection.execute(
                """
                SELECT COALESCE(MAX(position), 0) + 1 FROM workout_exercises
                WHERE workout_id = ? AND active = 1
                """,
                (workout_id,),
            ).fetchone()[0]
            existing = connection.execute(
                "SELECT id FROM workout_exercises WHERE workout_id = ? AND exercise_id = ?",
                (workout_id, exercise_id),
            ).fetchone()
            if existing:
                connection.execute(
                    """
                    UPDATE workout_exercises SET position = ?, target_min_reps = ?,
                        target_max_reps = ?, target_sets = ?, instructions = ?, active = 1,
                        updated_at = CURRENT_TIMESTAMP WHERE id = ?
                    """,
                    (position, target_min_reps, target_max_reps, target_sets, instructions.strip(), existing["id"]),
                )
                return int(existing["id"])
            cursor = connection.execute(
                """
                INSERT INTO workout_exercises
                    (workout_id, exercise_id, position, target_min_reps,
                     target_max_reps, target_sets, instructions)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (workout_id, exercise_id, position, target_min_reps, target_max_reps, target_sets, instructions.strip()),
            )
            return int(cursor.lastrowid)
    except INTEGRITY_ERRORS as exc:
        raise RoutineError("Could not add that exercise to the workout.") from exc


def update_workout_exercise(
    workout_exercise_id: int,
    *,
    target_min_reps: int,
    target_max_reps: int,
    target_sets: int,
    instructions: str,
    db_path: Path | str | None = None,
) -> None:
    _validate_targets(target_min_reps, target_max_reps, target_sets)
    with transaction(db_path) as connection:
        cursor = connection.execute(
            """
            UPDATE workout_exercises SET target_min_reps = ?, target_max_reps = ?,
                target_sets = ?, instructions = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (target_min_reps, target_max_reps, target_sets, instructions.strip(), workout_exercise_id),
        )
        if cursor.rowcount == 0:
            raise RoutineError("Workout exercise not found.")


def remove_exercise_from_workout(
    workout_exercise_id: int, db_path: Path | str | None = None
) -> None:
    with transaction(db_path) as connection:
        row = connection.execute(
            "SELECT workout_id FROM workout_exercises WHERE id = ?", (workout_exercise_id,)
        ).fetchone()
        if row is None:
            raise RoutineError("Workout exercise not found.")
        connection.execute(
            "UPDATE workout_exercises SET active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (workout_exercise_id,),
        )
        _normalize_positions(connection, row["workout_id"])


def move_workout_exercise(
    workout_exercise_id: int, direction: int, db_path: Path | str | None = None
) -> None:
    if direction not in (-1, 1):
        raise RoutineError("Direction must be -1 or 1.")
    with transaction(db_path) as connection:
        current = connection.execute(
            "SELECT workout_id, position FROM workout_exercises WHERE id = ? AND active = 1",
            (workout_exercise_id,),
        ).fetchone()
        if current is None:
            raise RoutineError("Workout exercise not found.")
        other = connection.execute(
            """
            SELECT id, position FROM workout_exercises
            WHERE workout_id = ? AND active = 1 AND position = ?
            """,
            (current["workout_id"], current["position"] + direction),
        ).fetchone()
        if other is None:
            return
        connection.execute(
            "UPDATE workout_exercises SET position = ? WHERE id = ?",
            (current["position"], other["id"]),
        )
        connection.execute(
            "UPDATE workout_exercises SET position = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (other["position"], workout_exercise_id),
        )


def list_workout_exercises(
    workout_id: int, db_path: Path | str | None = None
) -> list[WorkoutExercise]:
    with connection_scope(db_path) as connection:
        rows = connection.execute(
            """
            SELECT we.id, we.workout_id, we.exercise_id, e.name AS exercise_name,
                   e.primary_muscle_group, e.equipment, we.position,
                   we.target_min_reps, we.target_max_reps, we.target_sets,
                   we.instructions
            FROM workout_exercises we
            JOIN exercises e ON e.id = we.exercise_id
            WHERE we.workout_id = ? AND we.active = 1
            ORDER BY we.position, we.id
            """,
            (workout_id,),
        ).fetchall()
    return [WorkoutExercise(**dict(row)) for row in rows]


def _validate_targets(minimum: int, maximum: int, sets: int) -> None:
    if minimum < 1 or maximum < minimum:
        raise RoutineError("Rep range must be positive and maximum must be at least minimum.")
    if sets < 1:
        raise RoutineError("Target working sets must be at least 1.")


def _normalize_positions(connection: sqlite3.Connection, workout_id: int) -> None:
    rows = connection.execute(
        """
        SELECT id FROM workout_exercises
        WHERE workout_id = ? AND active = 1 ORDER BY position, id
        """,
        (workout_id,),
    ).fetchall()
    for position, row in enumerate(rows, start=1):
        connection.execute(
            "UPDATE workout_exercises SET position = ? WHERE id = ?", (position, row["id"])
        )
