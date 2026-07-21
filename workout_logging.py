"""Completed-workout persistence and session review operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import isclose
from pathlib import Path
from typing import Iterable

from database import connection_scope, transaction
from profile_management import default_profile_id
from routine_management import list_workout_exercises


class WorkoutLogError(ValueError):
    """Raised when a workout log cannot be validated or saved."""


@dataclass(frozen=True)
class SetEntry:
    weight: float
    reps: int
    intensity_method: str = ""
    intensity_reps: int = 0
    notes: str = ""


@dataclass(frozen=True)
class ExerciseLog:
    workout_exercise_id: int
    sets: tuple[SetEntry, ...]


def save_completed_session(
    routine_id: int,
    workout_id: int,
    workout_date: date,
    completed_at: datetime,
    exercise_logs: Iterable[ExerciseLog],
    *,
    profile_id: int | None = None,
    notes: str = "",
    db_path: Path | str | None = None,
) -> int:
    """Save one session and immutable configuration snapshots in one transaction."""
    logs = {log.workout_exercise_id: log for log in exercise_logs}
    configured = list_workout_exercises(workout_id, db_path)
    if not configured:
        raise WorkoutLogError("This workout has no configured exercises.")
    configured_ids = {item.id for item in configured}
    if not set(logs).issubset(configured_ids):
        raise WorkoutLogError("The log contains an exercise that is not in this workout.")
    if not any(log.sets for log in logs.values()):
        raise WorkoutLogError("Log at least one completed set before saving.")
    for log in logs.values():
        for entry in log.sets:
            _validate_set(entry)

    selected_profile_id = profile_id or default_profile_id(db_path=db_path)
    with transaction(db_path) as connection:
        profile = connection.execute(
            "SELECT id FROM profiles WHERE id = ? AND active = 1",
            (selected_profile_id,),
        ).fetchone()
        if profile is None:
            raise WorkoutLogError("Select an active profile before saving the workout.")
        names = connection.execute(
            """
            SELECT r.name AS routine_name, w.name AS workout_name
            FROM workouts w JOIN routines r ON r.id = w.routine_id
            WHERE w.id = ? AND r.id = ?
            """,
            (workout_id, routine_id),
        ).fetchone()
        if names is None:
            raise WorkoutLogError("Routine and workout selection is invalid.")
        cursor = connection.execute(
            """
            INSERT INTO workout_sessions
                (profile_id, routine_id, workout_id, routine_name, workout_name,
                 workout_date, completed_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                selected_profile_id,
                routine_id,
                workout_id,
                names["routine_name"],
                names["workout_name"],
                workout_date.isoformat(),
                completed_at.isoformat(timespec="seconds"),
                notes.strip(),
            ),
        )
        session_id = int(cursor.lastrowid)
        for item in configured:
            exercise_cursor = connection.execute(
                """
                INSERT INTO session_exercises
                    (session_id, exercise_id, workout_exercise_id, exercise_name,
                     position, target_min_reps, target_max_reps, target_sets, instructions)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    item.exercise_id,
                    item.id,
                    item.exercise_name,
                    item.position,
                    item.target_min_reps,
                    item.target_max_reps,
                    item.target_sets,
                    item.instructions,
                ),
            )
            session_exercise_id = int(exercise_cursor.lastrowid)
            for set_number, entry in enumerate(logs.get(item.id, ExerciseLog(item.id, ())).sets, start=1):
                connection.execute(
                    """
                    INSERT INTO logged_sets
                        (session_exercise_id, set_number, weight, reps,
                         intensity_method, intensity_reps, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_exercise_id,
                        set_number,
                        round(entry.weight, 2),
                        entry.reps,
                        entry.intensity_method.strip(),
                        entry.intensity_reps,
                        entry.notes.strip(),
                    ),
                )
        return session_id


def _validate_set(entry: SetEntry) -> None:
    if entry.weight < 0:
        raise WorkoutLogError("Weight cannot be negative.")
    if not isclose(entry.weight * 4, round(entry.weight * 4), abs_tol=1e-9):
        raise WorkoutLogError("Weight must use 0.25 kg increments.")
    if entry.reps < 1:
        raise WorkoutLogError("Reps must be at least 1.")
    if entry.intensity_reps < 0:
        raise WorkoutLogError("Intensity reps cannot be negative.")
    if entry.intensity_reps and not entry.intensity_method.strip():
        raise WorkoutLogError(
            "Select an intensity method before recording intensity reps."
        )


def update_logged_set(
    set_id: int,
    *,
    weight: float,
    reps: int,
    intensity_method: str = "",
    intensity_reps: int = 0,
    notes: str = "",
    db_path: Path | str | None = None,
) -> None:
    """Correct the values of one set in a completed session."""
    entry = SetEntry(
        weight=weight,
        reps=reps,
        intensity_method=intensity_method,
        intensity_reps=intensity_reps,
        notes=notes,
    )
    _validate_set(entry)
    with transaction(db_path) as connection:
        cursor = connection.execute(
            """
            UPDATE logged_sets
            SET weight = ?, reps = ?, intensity_method = ?, intensity_reps = ?,
                notes = ? WHERE id = ?
            """,
            (
                round(weight, 2),
                reps,
                intensity_method.strip(),
                intensity_reps,
                notes.strip(),
                set_id,
            ),
        )
        if cursor.rowcount == 0:
            raise WorkoutLogError("Logged set not found.")


def delete_logged_set(
    set_id: int, *, db_path: Path | str | None = None
) -> None:
    """Delete one incorrectly logged set and renumber the remaining sets."""
    with transaction(db_path) as connection:
        row = connection.execute(
            "SELECT session_exercise_id FROM logged_sets WHERE id = ?", (set_id,)
        ).fetchone()
        if row is None:
            raise WorkoutLogError("Logged set not found.")
        connection.execute("DELETE FROM logged_sets WHERE id = ?", (set_id,))
        remaining = connection.execute(
            """
            SELECT id FROM logged_sets WHERE session_exercise_id = ?
            ORDER BY set_number, id
            """,
            (row["session_exercise_id"],),
        ).fetchall()
        for set_number, item in enumerate(remaining, start=1):
            connection.execute(
                "UPDATE logged_sets SET set_number = ? WHERE id = ?",
                (set_number, item["id"]),
            )


def get_previous_result(
    exercise_id: int,
    *,
    profile_id: int | None = None,
    before: datetime | None = None,
    db_path: Path | str | None = None,
) -> dict[str, object] | None:
    """Return the most recent logged result for an exercise."""
    query = """
        SELECT ws.id AS session_id, ws.workout_date, ws.workout_name,
               ls.set_number, ls.weight, ls.reps, ls.intensity_method,
               ls.intensity_reps
        FROM session_exercises se
        JOIN workout_sessions ws ON ws.id = se.session_id
        JOIN logged_sets ls ON ls.session_exercise_id = se.id
        WHERE se.exercise_id = ?
    """
    params: list[object] = [exercise_id]
    if profile_id is not None:
        query += " AND ws.profile_id = ?"
        params.append(profile_id)
    if before is not None:
        query += " AND ws.completed_at < ?"
        params.append(before.isoformat(timespec="seconds"))
    query += " ORDER BY ws.completed_at DESC, ls.set_number LIMIT 1"
    with connection_scope(db_path) as connection:
        first = connection.execute(query, params).fetchone()
        if first is None:
            return None
        sets = connection.execute(
            """
            SELECT ls.set_number, ls.weight, ls.reps, ls.intensity_method,
                   ls.intensity_reps, ls.notes
            FROM session_exercises se
            JOIN logged_sets ls ON ls.session_exercise_id = se.id
            WHERE se.session_id = ? AND se.exercise_id = ?
            ORDER BY ls.set_number
            """,
            (first["session_id"], exercise_id),
        ).fetchall()
    return {
        "session_id": first["session_id"],
        "workout_date": first["workout_date"],
        "workout_name": first["workout_name"],
        "sets": [dict(row) for row in sets],
    }


def get_previous_results(
    exercise_ids: Iterable[int],
    *,
    profile_id: int | None = None,
    db_path: Path | str | None = None,
) -> dict[int, dict[str, object]]:
    """Return the latest session result for several exercises in one query."""
    selected_ids = tuple(dict.fromkeys(int(item) for item in exercise_ids))
    if not selected_ids:
        return {}
    placeholders = ", ".join("?" for _ in selected_ids)
    query = f"""
        SELECT se.exercise_id, ws.id AS session_id, ws.workout_date,
               ws.workout_name, ws.completed_at, ls.set_number,
               ls.weight, ls.reps, ls.intensity_method,
               ls.intensity_reps, ls.notes
        FROM session_exercises se
        JOIN workout_sessions ws ON ws.id = se.session_id
        JOIN logged_sets ls ON ls.session_exercise_id = se.id
        WHERE se.exercise_id IN ({placeholders})
    """
    params: list[object] = list(selected_ids)
    if profile_id is not None:
        query += " AND ws.profile_id = ?"
        params.append(profile_id)
    query += (
        " ORDER BY se.exercise_id, ws.completed_at DESC, ws.id DESC, "
        "ls.set_number"
    )
    with connection_scope(db_path) as connection:
        rows = connection.execute(query, params).fetchall()

    results: dict[int, dict[str, object]] = {}
    for row in rows:
        exercise_id = int(row["exercise_id"])
        current = results.get(exercise_id)
        if current is None:
            current = {
                "session_id": int(row["session_id"]),
                "workout_date": row["workout_date"],
                "workout_name": row["workout_name"],
                "sets": [],
            }
            results[exercise_id] = current
        if int(current["session_id"]) != int(row["session_id"]):
            continue
        current["sets"].append(
            {
                "set_number": row["set_number"],
                "weight": row["weight"],
                "reps": row["reps"],
                "intensity_method": row["intensity_method"],
                "intensity_reps": row["intensity_reps"],
                "notes": row["notes"],
            }
        )
    return results


def list_sessions(
    *,
    profile_id: int | None = None,
    routine_id: int | None = None,
    workout_id: int | None = None,
    exercise_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db_path: Path | str | None = None,
) -> list[dict[str, object]]:
    query = """
        SELECT DISTINCT ws.id, COALESCE(p.name, 'Unassigned') AS profile_name,
               ws.routine_name, ws.workout_name,
               ws.workout_date, ws.completed_at, ws.notes,
               COUNT(DISTINCT se.id) AS exercise_count,
               COUNT(ls.id) AS set_count
        FROM workout_sessions ws
        LEFT JOIN profiles p ON p.id = ws.profile_id
        LEFT JOIN session_exercises se ON se.session_id = ws.id
        LEFT JOIN logged_sets ls ON ls.session_exercise_id = se.id
        WHERE 1 = 1
    """
    params: list[object] = []
    if profile_id is not None:
        query += " AND ws.profile_id = ?"
        params.append(profile_id)
    if routine_id is not None:
        query += " AND ws.routine_id = ?"
        params.append(routine_id)
    if workout_id is not None:
        query += " AND ws.workout_id = ?"
        params.append(workout_id)
    if exercise_id is not None:
        query += " AND EXISTS (SELECT 1 FROM session_exercises x WHERE x.session_id = ws.id AND x.exercise_id = ?)"
        params.append(exercise_id)
    if date_from is not None:
        query += " AND ws.workout_date >= ?"
        params.append(date_from.isoformat())
    if date_to is not None:
        query += " AND ws.workout_date <= ?"
        params.append(date_to.isoformat())
    query += " GROUP BY ws.id ORDER BY ws.workout_date DESC, ws.completed_at DESC"
    with connection_scope(db_path) as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_session_review(
    session_id: int, db_path: Path | str | None = None
) -> dict[str, object]:
    with connection_scope(db_path) as connection:
        session = connection.execute(
            "SELECT * FROM workout_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if session is None:
            raise WorkoutLogError("Session not found.")
        exercises = connection.execute(
            """
            SELECT id, exercise_name, position, target_min_reps,
                   target_max_reps, target_sets, instructions
            FROM session_exercises WHERE session_id = ? ORDER BY position, id
            """,
            (session_id,),
        ).fetchall()
        result_exercises: list[dict[str, object]] = []
        for exercise in exercises:
            sets = connection.execute(
                "SELECT id, set_number, weight, reps, intensity_method, "
                "intensity_reps, notes FROM logged_sets "
                "WHERE session_exercise_id = ? ORDER BY set_number",
                (exercise["id"],),
            ).fetchall()
            exercise_data = dict(exercise)
            exercise_data["sets"] = [dict(row) for row in sets]
            result_exercises.append(exercise_data)
    result = dict(session)
    result["exercises"] = result_exercises
    return result
