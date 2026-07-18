"""Read-only workout-history and exercise-progress calculations."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from database import connection_scope


def days_since_previous_workout(
    *, db_path: Path | str | None = None, today: date | None = None
) -> int | None:
    reference = today or date.today()
    with connection_scope(db_path) as connection:
        row = connection.execute(
            "SELECT MAX(workout_date) AS last_date FROM workout_sessions WHERE workout_date < ?",
            (reference.isoformat(),),
        ).fetchone()
    if not row or not row["last_date"]:
        return None
    return (reference - date.fromisoformat(row["last_date"])).days


def exercise_progress(
    exercise_id: int, *, db_path: Path | str | None = None
) -> pd.DataFrame:
    """Return one row per session with volume and best-set indicators."""
    query = """
        SELECT ws.workout_date AS date, ws.id AS session_id, ws.workout_name,
               MAX(ls.weight) AS max_weight,
               MAX(ls.weight * (1.0 + ls.reps / 30.0)) AS estimated_1rm,
               SUM(ls.weight * ls.reps) AS volume,
               SUM(ls.reps) AS total_reps,
               COUNT(ls.id) AS sets
        FROM session_exercises se
        JOIN workout_sessions ws ON ws.id = se.session_id
        JOIN logged_sets ls ON ls.session_exercise_id = se.id
        WHERE se.exercise_id = ?
        GROUP BY ws.id
        ORDER BY ws.workout_date, ws.completed_at
    """
    with connection_scope(db_path) as connection:
        frame = pd.read_sql_query(query, connection, params=(exercise_id,))
    if not frame.empty:
        frame["date"] = pd.to_datetime(frame["date"])
        for column in ("max_weight", "estimated_1rm", "volume"):
            frame[column] = frame[column].round(2)
    return frame


def history_dataframe(
    *, db_path: Path | str | None = None
) -> pd.DataFrame:
    query = """
        SELECT ws.id AS session_id, ws.workout_date AS date,
               ws.routine_name AS routine, ws.workout_name AS workout,
               se.exercise_name AS exercise, ls.set_number,
               ls.weight, ls.reps, ls.intensity_method, ls.notes
        FROM workout_sessions ws
        JOIN session_exercises se ON se.session_id = ws.id
        JOIN logged_sets ls ON ls.session_exercise_id = se.id
        ORDER BY ws.workout_date DESC, ws.completed_at DESC,
                 se.position, ls.set_number
    """
    with connection_scope(db_path) as connection:
        return pd.read_sql_query(query, connection)
