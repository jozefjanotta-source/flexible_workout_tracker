"""Streamlit rendering smoke test for every V1 page."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from init_db import initialize_database


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
                    widget for widget in app.selectbox
                    if widget.label == "Reps"
                )
                intensity = next(
                    widget for widget in app.selectbox
                    if widget.label == "Intensity method"
                )
                intensity_reps = next(
                    widget for widget in app.selectbox
                    if widget.label == "Intensity reps"
                )
                self.assertTrue(intensity_reps.disabled)
                self.assertEqual(
                    list(reps.options),
                    [str(value) for value in range(1, 101)],
                )
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
                next(
                    button for button in app.button
                    if button.label == "Cancel workout"
                ).click().run()
                next(
                    button for button in app.button
                    if button.label == "Discard workout"
                ).click().run()
                self.assertFalse(app.exception)
                self.assertIn("Workout tracker", [title.value for title in app.title])
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
                app.checkbox[0].set_value(True)
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
                    widget for widget in app.selectbox
                    if widget.label == "Reps"
                ).set_value(8)
                next(
                    widget for widget in app.selectbox
                    if widget.label == "Intensity method"
                ).set_value("Rest-pause")
                app.run()
                intensity_reps = next(
                    widget for widget in app.selectbox
                    if widget.label == "Intensity reps"
                )
                self.assertFalse(intensity_reps.disabled)
                intensity_reps.set_value(2)
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


if __name__ == "__main__":
    unittest.main()
