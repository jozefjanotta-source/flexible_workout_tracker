"""Database schema creation and optional sample-data seeding."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from database import get_db_path, transaction


SCHEMA = """
CREATE TABLE IF NOT EXISTS exercises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    primary_muscle_group TEXT NOT NULL,
    equipment TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS routines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    routine_id INTEGER NOT NULL REFERENCES routines(id),
    name TEXT NOT NULL COLLATE NOCASE,
    description TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 1 CHECK (position > 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (routine_id, name)
);

CREATE TABLE IF NOT EXISTS workout_exercises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id INTEGER NOT NULL REFERENCES workouts(id),
    exercise_id INTEGER NOT NULL REFERENCES exercises(id),
    position INTEGER NOT NULL CHECK (position > 0),
    target_min_reps INTEGER NOT NULL CHECK (target_min_reps > 0),
    target_max_reps INTEGER NOT NULL CHECK (target_max_reps >= target_min_reps),
    target_sets INTEGER NOT NULL CHECK (target_sets > 0),
    instructions TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (workout_id, exercise_id)
);

CREATE TABLE IF NOT EXISTS workout_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    routine_id INTEGER REFERENCES routines(id),
    workout_id INTEGER REFERENCES workouts(id),
    routine_name TEXT NOT NULL,
    workout_name TEXT NOT NULL,
    workout_date TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS session_exercises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES workout_sessions(id) ON DELETE CASCADE,
    exercise_id INTEGER REFERENCES exercises(id),
    workout_exercise_id INTEGER REFERENCES workout_exercises(id),
    exercise_name TEXT NOT NULL,
    position INTEGER NOT NULL,
    target_min_reps INTEGER NOT NULL,
    target_max_reps INTEGER NOT NULL,
    target_sets INTEGER NOT NULL,
    instructions TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS logged_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_exercise_id INTEGER NOT NULL REFERENCES session_exercises(id) ON DELETE CASCADE,
    set_number INTEGER NOT NULL CHECK (set_number > 0),
    weight REAL NOT NULL CHECK (weight >= 0),
    reps INTEGER NOT NULL CHECK (reps > 0),
    intensity_method TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    UNIQUE (session_exercise_id, set_number)
);

CREATE INDEX IF NOT EXISTS idx_workouts_routine ON workouts(routine_id, active, position);
CREATE INDEX IF NOT EXISTS idx_workout_exercises_workout ON workout_exercises(workout_id, active, position);
CREATE INDEX IF NOT EXISTS idx_sessions_date ON workout_sessions(workout_date DESC, completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_session_exercises_exercise ON session_exercises(exercise_id, session_id);
"""


SAMPLE_EXERCISES = (
    ("Barbell Back Squat", "Legs", "Barbell", "Keep the torso braced and use a comfortable depth."),
    ("Bench Press", "Chest", "Barbell", "Use a controlled touch and stable upper back."),
    ("Romanian Deadlift", "Hamstrings", "Barbell", "Hinge at the hips and keep the bar close."),
    ("Lat Pulldown", "Back", "Cable", "Drive elbows down without swinging."),
    ("Seated Dumbbell Press", "Shoulders", "Dumbbells", "Keep ribs stacked over the pelvis."),
    ("Cable Row", "Back", "Cable", "Pause briefly with shoulder blades retracted."),
    ("Dumbbell Curl", "Biceps", "Dumbbells", "Avoid moving the upper arm."),
    ("Triceps Pushdown", "Triceps", "Cable", "Keep elbows close to the torso."),
    ("Plank", "Core", "Bodyweight", "Maintain a straight line and breathe normally."),
)


def initialize_database(
    db_path: Path | str | None = None, *, seed_sample_routine: bool = True
) -> Path:
    """Create missing tables and idempotently seed starter data."""
    path = Path(db_path).expanduser().resolve() if db_path else get_db_path()
    with transaction(path) as connection:
        connection.executescript(SCHEMA)
        connection.executemany(
            """
            INSERT INTO exercises (name, primary_muscle_group, equipment, notes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO NOTHING
            """,
            SAMPLE_EXERCISES,
        )
        if seed_sample_routine:
            _seed_sample_routine(connection)
    return path


def _seed_sample_routine(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO routines (name, description)
        VALUES ('Sample Full Body', 'Optional starter routine; edit, deactivate, or replace it.')
        ON CONFLICT(name) DO NOTHING
        """
    )
    routine = connection.execute(
        "SELECT id FROM routines WHERE name = 'Sample Full Body'"
    ).fetchone()
    if routine is None:
        return
    connection.execute(
        """
        INSERT INTO workouts (routine_id, name, description, position)
        VALUES (?, 'Workout A', 'A simple full-body example.', 1)
        ON CONFLICT(routine_id, name) DO NOTHING
        """,
        (routine["id"],),
    )
    workout = connection.execute(
        "SELECT id FROM workouts WHERE routine_id = ? AND name = 'Workout A'",
        (routine["id"],),
    ).fetchone()
    if workout is None:
        return
    examples = (
        ("Barbell Back Squat", 1, 5, 8, 3),
        ("Bench Press", 2, 6, 10, 3),
        ("Lat Pulldown", 3, 8, 12, 3),
    )
    for name, position, minimum, maximum, sets in examples:
        exercise = connection.execute(
            "SELECT id FROM exercises WHERE name = ?", (name,)
        ).fetchone()
        if exercise:
            connection.execute(
                """
                INSERT INTO workout_exercises
                    (workout_id, exercise_id, position, target_min_reps,
                     target_max_reps, target_sets)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(workout_id, exercise_id) DO NOTHING
                """,
                (workout["id"], exercise["id"], position, minimum, maximum, sets),
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize the workout tracker database.")
    parser.add_argument("--db", type=Path, help="Optional database path")
    parser.add_argument(
        "--no-sample-routine", action="store_true", help="Only seed the exercise library"
    )
    args = parser.parse_args()
    path = initialize_database(args.db, seed_sample_routine=not args.no_sample_routine)
    print(f"Database initialized at {path}")


if __name__ == "__main__":
    main()

