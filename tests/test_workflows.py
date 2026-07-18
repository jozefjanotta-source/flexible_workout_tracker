"""Service-level tests for the main V1 workflows."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from exercise_management import create_exercise, list_exercises, update_exercise
from init_db import initialize_database
from progress_calculations import days_since_previous_workout, exercise_progress
from routine_management import (
    add_exercise_to_workout,
    create_routine,
    create_workout,
    list_workout_exercises,
    move_workout_exercise,
    remove_exercise_from_workout,
    update_routine,
    update_workout_exercise,
)
from workout_logging import (
    ExerciseLog,
    SetEntry,
    get_previous_result,
    get_session_review,
    list_sessions,
    save_completed_session,
)


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        initialize_database(self.db_path, seed_sample_routine=False)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_exercise_create_edit_and_deactivate(self) -> None:
        exercise_id = create_exercise(
            "Custom Press", "Shoulders", "Dumbbells", db_path=self.db_path
        )
        update_exercise(
            exercise_id,
            name="Custom Overhead Press",
            primary_muscle_group="Shoulders",
            equipment="Dumbbells",
            notes="Controlled reps",
            active=False,
            db_path=self.db_path,
        )
        exercise = next(item for item in list_exercises(db_path=self.db_path) if item.id == exercise_id)
        self.assertEqual(exercise.name, "Custom Overhead Press")
        self.assertFalse(exercise.active)

    def test_routine_build_log_history_progress_and_snapshots(self) -> None:
        exercises = list_exercises(active_only=True, db_path=self.db_path)
        squat = next(item for item in exercises if item.name == "Barbell Back Squat")
        bench = next(item for item in exercises if item.name == "Bench Press")
        routine_id = create_routine("Strength", db_path=self.db_path)
        workout_id = create_workout(routine_id, "Day One", db_path=self.db_path)
        squat_config = add_exercise_to_workout(
            workout_id,
            squat.id,
            target_min_reps=5,
            target_max_reps=8,
            target_sets=3,
            db_path=self.db_path,
        )
        bench_config = add_exercise_to_workout(
            workout_id,
            bench.id,
            target_min_reps=6,
            target_max_reps=10,
            target_sets=3,
            db_path=self.db_path,
        )
        move_workout_exercise(bench_config, -1, self.db_path)
        configured = list_workout_exercises(workout_id, self.db_path)
        self.assertEqual([item.exercise_name for item in configured], ["Bench Press", "Barbell Back Squat"])

        session_day = date.today() - timedelta(days=3)
        session_id = save_completed_session(
            routine_id,
            workout_id,
            session_day,
            datetime.combine(session_day, datetime.min.time()).replace(hour=18),
            [
                ExerciseLog(bench_config, (SetEntry(60, 8), SetEntry(60, 7, "Rest-pause"))),
                ExerciseLog(squat_config, (SetEntry(80, 6),)),
            ],
            notes="Good session",
            db_path=self.db_path,
        )

        update_routine(
            routine_id,
            name="Renamed Strength",
            description="Edited later",
            active=True,
            db_path=self.db_path,
        )
        update_workout_exercise(
            bench_config,
            target_min_reps=10,
            target_max_reps=12,
            target_sets=4,
            instructions="New target",
            db_path=self.db_path,
        )
        remove_exercise_from_workout(squat_config, self.db_path)

        review = get_session_review(session_id, self.db_path)
        self.assertEqual(review["routine_name"], "Strength")
        self.assertEqual(review["exercises"][0]["target_min_reps"], 6)
        self.assertEqual(len(review["exercises"]), 2)
        self.assertEqual(len(list_sessions(exercise_id=bench.id, db_path=self.db_path)), 1)
        previous = get_previous_result(bench.id, db_path=self.db_path)
        self.assertIsNotNone(previous)
        self.assertEqual(len(previous["sets"]), 2)
        progress = exercise_progress(bench.id, db_path=self.db_path)
        self.assertEqual(progress.iloc[0]["volume"], 900.0)
        self.assertEqual(days_since_previous_workout(db_path=self.db_path), 3)

    def test_schema_has_expected_tables(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        expected = {
            "exercises",
            "routines",
            "workouts",
            "workout_exercises",
            "workout_sessions",
            "session_exercises",
            "logged_sets",
        }
        self.assertTrue(expected.issubset(tables))


if __name__ == "__main__":
    unittest.main()

