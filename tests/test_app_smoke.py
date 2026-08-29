"""Streamlit rendering smoke test for every V1 page."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

from exercise_management import list_exercises
from init_db import initialize_database
from profile_management import create_profile, default_profile_id
from routine_management import list_routines, list_workout_exercises, list_workouts
from workout_logging import ExerciseLog, SetEntry, save_completed_session


class AppSmokeTests(unittest.TestCase):
    def test_every_page_renders_without_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            previous_path = os.environ.get("WORKOUT_DB_PATH")
            os.environ["WORKOUT_DB_PATH"] = str(Path(temp_dir) / "smoke.db")
            initialize_database(os.environ["WORKOUT_DB_PATH"])
            try:
                app_path = Path(__file__).resolve().parents[1] / "app.py"
                app = AppTest.from_file(str(app_path), default_timeout=20).run()
                self.assertFalse(app.exception)
                self.assertTrue(
                    any(button.label == "Start workout" for button in app.button)
                )
                for page_path in (
                    "ui_pages/workout.py",
                    "ui_pages/compare.py",
                    "ui_pages/history.py",
                    "ui_pages/routines.py",
                    "ui_pages/exercises.py",
                    "ui_pages/profiles.py",
                    "ui_pages/settings.py",
                ):
                    app.switch_page(page_path).run()
                    self.assertFalse(
                        app.exception,
                        f"{page_path} failed to render",
                    )
            finally:
                if previous_path is None:
                    os.environ.pop("WORKOUT_DB_PATH", None)
                else:
                    os.environ["WORKOUT_DB_PATH"] = previous_path

    def test_cancel_workout_discards_draft_and_returns_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            previous_path = os.environ.get("WORKOUT_DB_PATH")
            os.environ["WORKOUT_DB_PATH"] = str(Path(temp_dir) / "cancel.db")
            initialize_database(os.environ["WORKOUT_DB_PATH"])
            try:
                app_path = Path(__file__).resolve().parents[1] / "app.py"
                app = AppTest.from_file(str(app_path), default_timeout=20).run()
                app.switch_page("ui_pages/workout.py").run()
                self.assertFalse(
                    any(
                        widget.label == "Sets to log"
                        for widget in app.selectbox
                    )
                )
                reps = next(
                    widget for widget in app.number_input
                    if widget.label == "Reps"
                )
                intensity = next(
                    widget for widget in app.selectbox
                    if widget.label == "Intensity method"
                )
                intensity_reps = next(
                    widget for widget in app.number_input
                    if widget.label == "Intensity reps"
                )
                self.assertFalse(intensity_reps.disabled)
                self.assertEqual(intensity_reps.min, 0)
                self.assertEqual(intensity_reps.max, 20)
                self.assertEqual(intensity_reps.step, 1)
                self.assertEqual(reps.min, 1)
                self.assertEqual(reps.max, 100)
                self.assertEqual(reps.step, 1)
                self.assertEqual(
                    list(intensity.options),
                    [
                        "None",
                        "Forced",
                        "Negative",
                        "Static holds",
                        "Forced negative",
                        "Partials",
                        "Rest-pause",
                        "Omni-contraction",
                    ],
                )
                self.assertTrue(
                    any(widget.label == "Weight" for widget in app.number_input)
                )
                self.assertTrue(
                    any(widget.label == "Log this set" for widget in app.checkbox)
                )
                next(
                    button for button in app.button
                    if button.label == "Cancel workout"
                ).click().run()
                next(
                    button for button in app.button
                    if button.label == "Discard workout"
                ).click().run()
                self.assertFalse(app.exception)
                self.assertIn("Dashboard", [title.value for title in app.title])
                self.assertIn(
                    "Workout cancelled. Nothing was saved.",
                    [message.value for message in app.info],
                )
            finally:
                if previous_path is None:
                    os.environ.pop("WORKOUT_DB_PATH", None)
                else:
                    os.environ["WORKOUT_DB_PATH"] = previous_path


    def test_new_controls_save_and_open_completed_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            previous_path = os.environ.get("WORKOUT_DB_PATH")
            db_path = Path(temp_dir) / "save.db"
            os.environ["WORKOUT_DB_PATH"] = str(db_path)
            initialize_database(db_path)
            try:
                app_path = Path(__file__).resolve().parents[1] / "app.py"
                app = AppTest.from_file(str(app_path), default_timeout=20).run()
                app.switch_page("ui_pages/workout.py").run()
                self.assertIsNone(
                    next(
                        widget for widget in app.number_input
                        if widget.label == "Weight"
                    ).value
                )
                self.assertIsNone(
                    next(
                        widget for widget in app.number_input
                        if widget.label == "Reps"
                    ).value
                )
                weight_input = next(
                    widget for widget in app.number_input
                    if widget.label == "Weight"
                )
                weight_input.set_value(50.0)
                app.run()
                self.assertIn(
                    "50 kg",
                    [caption.value for caption in app.caption],
                )
                next(
                    widget for widget in app.number_input
                    if widget.label == "Weight"
                ).set_value(50.5)
                app.run()
                self.assertIn(
                    "50.5 kg",
                    [caption.value for caption in app.caption],
                )
                next(
                    widget for widget in app.number_input
                    if widget.label == "Weight"
                ).set_value(50.25)
                app.run()
                self.assertIn(
                    "50.25 kg",
                    [caption.value for caption in app.caption],
                )
                next(
                    widget for widget in app.number_input
                    if widget.label == "Reps"
                ).set_value(8)
                next(
                    widget for widget in app.selectbox
                    if widget.label == "Intensity method"
                ).set_value("Rest-pause")
                app.run()
                intensity_reps = next(
                    widget for widget in app.number_input
                    if widget.label == "Intensity reps"
                )
                self.assertFalse(intensity_reps.disabled)
                intensity_reps.set_value(2)
                next(
                    widget for widget in app.checkbox
                    if widget.label == "Log this set"
                ).check().run()
                self.assertTrue(
                    any(button.label == "Edit" for button in app.button)
                )
                self.assertTrue(
                    any("50.25 kg × 8 reps" in caption.value for caption in app.caption)
                )
                next(
                    button for button in app.button
                    if button.label == "Complete and save"
                ).click().run()

                self.assertFalse(app.exception)
                self.assertIn("History", [title.value for title in app.title])
                self.assertIn(
                    "Workout saved. The completed session is shown below.",
                    [message.value for message in app.success],
                )
                self.assertTrue(
                    any(
                        widget.label == "Review completed session"
                        for widget in app.selectbox
                    )
                )
                # Start a fresh browser simulation after save cleared draft widget keys.
                app = AppTest.from_file(str(app_path), default_timeout=20).run()
                app.switch_page("ui_pages/workout.py").run()
                self.assertTrue(
                    any(message.value.startswith("Previous |") for message in app.info)
                )
                self.assertEqual(
                    next(
                        widget for widget in app.number_input
                        if widget.label == "Weight"
                    ).value,
                    50.25,
                )
                self.assertEqual(
                    next(
                        widget for widget in app.number_input
                        if widget.label == "Reps"
                    ).value,
                    8,
                )
                self.assertFalse(
                    any("✓" in expander.label for expander in app.expander)
                )
                next(
                    button for button in app.button
                    if button.label == "Complete and save"
                ).click().run()
                self.assertIn(
                    "Log at least one completed set before saving.",
                    [message.value for message in app.error],
                )
                with sqlite3.connect(db_path) as connection:
                    session_count = connection.execute(
                        "SELECT COUNT(*) FROM workout_sessions"
                    ).fetchone()[0]
                self.assertEqual(session_count, 1)

                next(
                    widget for widget in app.number_input
                    if widget.label == "Reps"
                ).set_value(9)
                next(
                    widget for widget in app.checkbox
                    if widget.label == "Log this set"
                ).check()
                app.switch_page("ui_pages/history.py").run()
                saved_intensity_reps = next(
                    widget for widget in app.selectbox
                    if widget.label == "Intensity reps"
                )
                self.assertEqual(saved_intensity_reps.value, 2)
                next(
                    button for button in app.button
                    if button.label == "Delete complete workout"
                ).click().run()
                self.assertIn(
                    "This permanently deletes the completed workout and all of its "
                    "logged sets. The routine template will not be changed.",
                    [message.value for message in app.warning],
                )
                self.assertTrue(
                    any(
                        button.label == "Delete permanently"
                        for button in app.button
                    )
                )
            finally:
                if previous_path is None:
                    os.environ.pop("WORKOUT_DB_PATH", None)
                else:
                    os.environ["WORKOUT_DB_PATH"] = previous_path

    def test_workout_drafts_follow_profile_and_plan_can_be_adjusted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            previous_path = os.environ.get("WORKOUT_DB_PATH")
            db_path = Path(temp_dir) / "profiles.db"
            os.environ["WORKOUT_DB_PATH"] = str(db_path)
            initialize_database(db_path)
            try:
                primary_profile_id = default_profile_id(db_path=db_path)
                other_profile_id = create_profile("Training partner", db_path=db_path)
                routine = list_routines(active_only=True, db_path=db_path)[0]
                workout = list_workouts(
                    routine.id, active_only=True, db_path=db_path
                )[0]
                configured = list_workout_exercises(workout.id, db_path=db_path)
                first_exercise = configured[0]
                for profile_id, weight, reps in (
                    (primary_profile_id, 40.0, 8),
                    (other_profile_id, 75.0, 5),
                ):
                    save_completed_session(
                        routine.id,
                        workout.id,
                        date(2026, 8, 20),
                        datetime(2026, 8, 20, 18, 0),
                        [
                            ExerciseLog(
                                first_exercise.id,
                                (SetEntry(weight, reps),),
                            )
                        ],
                        profile_id=profile_id,
                        db_path=db_path,
                    )

                app_path = Path(__file__).resolve().parents[1] / "app.py"
                app = AppTest.from_file(str(app_path), default_timeout=20).run()
                app.switch_page("ui_pages/workout.py").run()
                self.assertEqual(
                    next(
                        widget for widget in app.number_input
                        if widget.label == "Weight"
                    ).value,
                    40.0,
                )
                next(
                    widget for widget in app.selectbox
                    if widget.key == "active_profile_selector"
                ).set_value(other_profile_id).run()
                self.assertEqual(
                    next(
                        widget for widget in app.number_input
                        if widget.label == "Weight"
                    ).value,
                    75.0,
                )
                workout_selector = next(
                    widget for widget in app.selectbox
                    if widget.key == "log_workout_id"
                )
                if len(workout_selector.options) > 1:
                    alternate_workout_id = next(
                        option
                        for option in workout_selector.options
                        if option != workout.id
                    )
                    workout_selector.set_value(alternate_workout_id).run()
                    self.assertEqual(
                        next(
                            widget for widget in app.selectbox
                            if widget.key == "active_profile_selector"
                        ).value,
                        other_profile_id,
                    )
                    next(
                        widget for widget in app.selectbox
                        if widget.key == "log_workout_id"
                    ).set_value(workout.id).run()
                    self.assertEqual(
                        app.session_state["active_profile_id"],
                        other_profile_id,
                    )

                configured_ids = {item.exercise_id for item in configured}
                extra = next(
                    item
                    for item in list_exercises(active_only=True, db_path=db_path)
                    if item.id not in configured_ids
                )
                next(
                    widget for widget in app.selectbox
                    if widget.label == "Add an unplanned exercise"
                ).set_value(extra.id)
                next(
                    button for button in app.button
                    if button.key == f"log_add_exercise_button_{workout.id}"
                ).click().run()
                adjusted = list_workout_exercises(workout.id, db_path=db_path)
                added = next(item for item in adjusted if item.exercise_id == extra.id)
                self.assertEqual(added.position, len(adjusted))

                next(
                    button for button in app.button
                    if button.key == f"log_move_up_{added.id}"
                ).click().run()
                reordered = list_workout_exercises(workout.id, db_path=db_path)
                moved = next(item for item in reordered if item.id == added.id)
                self.assertEqual(moved.position, len(reordered) - 1)
            finally:
                if previous_path is None:
                    os.environ.pop("WORKOUT_DB_PATH", None)
                else:
                    os.environ["WORKOUT_DB_PATH"] = previous_path


if __name__ == "__main__":
    unittest.main()
