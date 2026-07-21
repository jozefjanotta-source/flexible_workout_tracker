"""Read-only workout-history and exercise-progress calculations."""

from __future__ import annotations

from datetime import date
from math import isclose
from pathlib import Path
from typing import Iterable

import pandas as pd

from database import connection_scope


def days_since_previous_workout(
    *,
    profile_id: int | None = None,
    db_path: Path | str | None = None,
    today: date | None = None,
) -> int | None:
    reference = today or date.today()
    query = "SELECT MAX(workout_date) AS last_date FROM workout_sessions WHERE workout_date < ?"
    params: list[object] = [reference.isoformat()]
    if profile_id is not None:
        query += " AND profile_id = ?"
        params.append(profile_id)
    with connection_scope(db_path) as connection:
        row = connection.execute(query, params).fetchone()
    if not row or not row["last_date"]:
        return None
    return (reference - date.fromisoformat(row["last_date"])).days


def exercise_progress(
    exercise_id: int,
    *,
    profile_id: int | None = None,
    db_path: Path | str | None = None,
) -> pd.DataFrame:
    """Return the heaviest logged set per session for simple weight/reps tracking."""
    profile_filter = " AND ws.profile_id = ?" if profile_id is not None else ""
    query = f"""
        WITH ranked_sets AS (
            SELECT ws.workout_date AS date,
                   ws.completed_at,
                   ws.workout_name,
                   ls.weight,
                   ls.reps,
                   ROW_NUMBER() OVER (
                       PARTITION BY ws.id
                       ORDER BY ls.weight DESC, ls.reps DESC, ls.set_number
                   ) AS set_rank
            FROM session_exercises se
            JOIN workout_sessions ws ON ws.id = se.session_id
            JOIN logged_sets ls ON ls.session_exercise_id = se.id
            WHERE se.exercise_id = ?{profile_filter}
        )
        SELECT date, workout_name, weight, reps
        FROM ranked_sets
        WHERE set_rank = 1
        ORDER BY date, completed_at
    """
    params: tuple[object, ...] = (
        (exercise_id, profile_id) if profile_id is not None else (exercise_id,)
    )
    with connection_scope(db_path) as connection:
        cursor = connection.execute(query, params)
        columns = [description[0] for description in cursor.description]
        frame = pd.DataFrame.from_records(cursor.fetchall(), columns=columns)
    if not frame.empty:
        frame["date"] = pd.to_datetime(frame["date"])
        frame["weight"] = frame["weight"].round(2)
        evaluations = ["Baseline"]
        for index in range(1, len(frame)):
            current = frame.iloc[index]
            previous = frame.iloc[index - 1]
            evaluations.append(
                _evaluate_result(
                    weight=float(current["weight"]),
                    reps=int(current["reps"]),
                    previous_weight=float(previous["weight"]),
                    previous_reps=int(previous["reps"]),
                )
            )
        frame["evaluation"] = evaluations
    return frame


def _evaluate_result(
    *, weight: float, reps: int, previous_weight: float, previous_reps: int
) -> str:
    """Classify a result against the immediately preceding logged result."""
    weight_improved = weight > previous_weight and not isclose(weight, previous_weight)
    reps_improved = reps > previous_reps
    if weight_improved or reps_improved:
        return "Progress"
    if isclose(weight, previous_weight) and reps == previous_reps:
        return "No progress"
    return "Regression"


def latest_exercise_progress(
    *,
    profile_id: int | None = None,
    db_path: Path | str | None = None,
) -> pd.DataFrame:
    """Return the latest evaluated result for every exercise in one query."""
    profile_filter = " AND ws.profile_id = ?" if profile_id is not None else ""
    query = f"""
        WITH ranked_sets AS (
            SELECT se.exercise_id, se.exercise_name AS exercise,
                   ws.workout_date AS date, ws.completed_at,
                   ws.workout_name, ls.weight, ls.reps,
                   ROW_NUMBER() OVER (
                       PARTITION BY ws.id, se.exercise_id
                       ORDER BY ls.weight DESC, ls.reps DESC, ls.set_number
                   ) AS set_rank
            FROM session_exercises se
            JOIN workout_sessions ws ON ws.id = se.session_id
            JOIN logged_sets ls ON ls.session_exercise_id = se.id
            WHERE 1 = 1{profile_filter}
        )
        SELECT exercise_id, exercise, date, completed_at,
               workout_name, weight, reps
        FROM ranked_sets
        WHERE set_rank = 1
        ORDER BY exercise_id, date, completed_at
    """
    params: tuple[object, ...] = (profile_id,) if profile_id is not None else ()
    with connection_scope(db_path) as connection:
        cursor = connection.execute(query, params)
        columns = [description[0] for description in cursor.description]
        frame = pd.DataFrame.from_records(cursor.fetchall(), columns=columns)
    result_columns = [
        "exercise_id", "exercise", "date", "workout_name",
        "weight", "reps", "evaluation",
    ]
    if frame.empty:
        return pd.DataFrame(columns=result_columns)
    frame["date"] = pd.to_datetime(frame["date"])
    summaries: list[dict[str, object]] = []
    for _, group in frame.groupby("exercise_id", sort=False):
        ordered = group.reset_index(drop=True)
        current = ordered.iloc[-1]
        evaluation = "Baseline"
        if len(ordered) > 1:
            previous = ordered.iloc[-2]
            evaluation = _evaluate_result(
                weight=float(current["weight"]),
                reps=int(current["reps"]),
                previous_weight=float(previous["weight"]),
                previous_reps=int(previous["reps"]),
            )
        summaries.append(
            {
                "exercise_id": int(current["exercise_id"]),
                "exercise": current["exercise"],
                "date": current["date"],
                "workout_name": current["workout_name"],
                "weight": round(float(current["weight"]), 2),
                "reps": int(current["reps"]),
                "evaluation": evaluation,
            }
        )
    return pd.DataFrame.from_records(summaries, columns=result_columns)


def workout_comparison_dataframe(
    *,
    routine_id: int,
    workout_ids: Iterable[int] | None = None,
    profile_id: int | None = None,
    db_path: Path | str | None = None,
) -> pd.DataFrame:
    """Return the best set for each exercise in each selected workout session."""
    selected_workouts = tuple(dict.fromkeys(int(item) for item in (workout_ids or ())))
    query = """
        WITH ranked_sets AS (
            SELECT ws.id AS session_id, ws.workout_date AS date,
                   ws.completed_at, ws.workout_id, ws.workout_name AS workout,
                   se.exercise_id, se.exercise_name AS exercise,
                   ls.weight, ls.reps,
                   ROW_NUMBER() OVER (
                       PARTITION BY ws.id, se.exercise_id
                       ORDER BY ls.weight DESC, ls.reps DESC, ls.set_number
                   ) AS set_rank
            FROM workout_sessions ws
            JOIN session_exercises se ON se.session_id = ws.id
            JOIN logged_sets ls ON ls.session_exercise_id = se.id
            WHERE ws.routine_id = ?
    """
    params: list[object] = [routine_id]
    if profile_id is not None:
        query += " AND ws.profile_id = ?"
        params.append(profile_id)
    if selected_workouts:
        placeholders = ", ".join("?" for _ in selected_workouts)
        query += f" AND ws.workout_id IN ({placeholders})"
        params.extend(selected_workouts)
    query += """
        )
        SELECT session_id, date, completed_at, workout_id, workout,
               exercise_id, exercise, weight, reps
        FROM ranked_sets
        WHERE set_rank = 1
        ORDER BY exercise_id, date, completed_at
    """
    with connection_scope(db_path) as connection:
        cursor = connection.execute(query, params)
        columns = [description[0] for description in cursor.description]
        frame = pd.DataFrame.from_records(cursor.fetchall(), columns=columns)
    if frame.empty:
        frame["evaluation"] = pd.Series(dtype="object")
        return frame
    frame["date"] = pd.to_datetime(frame["date"])
    frame["weight"] = frame["weight"].astype(float).round(2)
    evaluations = pd.Series(index=frame.index, dtype="object")
    for _, group in frame.groupby("exercise_id", sort=False):
        previous: pd.Series | None = None
        for index, current in group.iterrows():
            if previous is None:
                evaluations.at[index] = "Baseline"
            else:
                evaluations.at[index] = _evaluate_result(
                    weight=float(current["weight"]),
                    reps=int(current["reps"]),
                    previous_weight=float(previous["weight"]),
                    previous_reps=int(previous["reps"]),
                )
            previous = current
    frame["evaluation"] = evaluations
    return frame


def history_dataframe(
    *,
    profile_id: int | None = None,
    routine_id: int | None = None,
    workout_id: int | None = None,
    exercise_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db_path: Path | str | None = None,
) -> pd.DataFrame:
    query = """
        SELECT ws.workout_date AS date, COALESCE(p.name, 'Unassigned') AS profile,
               ws.routine_name AS routine,
               ws.workout_name AS workout,
               se.exercise_name AS exercise, ls.set_number,
               ls.weight, ls.reps, ls.intensity_method,
               ls.intensity_reps, ls.notes
        FROM workout_sessions ws
        LEFT JOIN profiles p ON p.id = ws.profile_id
        JOIN session_exercises se ON se.session_id = ws.id
        JOIN logged_sets ls ON ls.session_exercise_id = se.id
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
        query += " AND se.exercise_id = ?"
        params.append(exercise_id)
    if date_from is not None:
        query += " AND ws.workout_date >= ?"
        params.append(date_from.isoformat())
    if date_to is not None:
        query += " AND ws.workout_date <= ?"
        params.append(date_to.isoformat())
    query += " ORDER BY ws.workout_date DESC, ws.completed_at DESC, se.position, ls.set_number"
    with connection_scope(db_path) as connection:
        cursor = connection.execute(query, params)
        columns = [description[0] for description in cursor.description]
        return pd.DataFrame.from_records(cursor.fetchall(), columns=columns)
