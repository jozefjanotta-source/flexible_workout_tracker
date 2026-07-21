"""Streamlit rendering smoke test for every V1 page."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class AppSmokeTests(unittest.TestCase):
    def test_every_page_renders_without_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            previous_path = os.environ.get("WORKOUT_DB_PATH")
            os.environ["WORKOUT_DB_PATH"] = str(Path(temp_dir) / "smoke.db")
            try:
                app_path = Path(__file__).resolve().parents[1] / "app.py"
                app = AppTest.from_file(str(app_path), default_timeout=20).run()
                self.assertFalse(app.exception)
                for page in ("Workout", "Compare", "History", "Manage"):
                    app.radio[0].set_value(page)
                    app.run()
                    self.assertFalse(app.exception, f"{page} failed to render")
            finally:
                if previous_path is None:
                    os.environ.pop("WORKOUT_DB_PATH", None)
                else:
                    os.environ["WORKOUT_DB_PATH"] = previous_path

    def test_cancel_workout_discards_draft_and_returns_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            previous_path = os.environ.get("WORKOUT_DB_PATH")
            os.environ["WORKOUT_DB_PATH"] = str(Path(temp_dir) / "cancel.db")
            try:
                app_path = Path(__file__).resolve().parents[1] / "app.py"
                app = AppTest.from_file(str(app_path), default_timeout=20).run()
                app.radio[0].set_value("Workout").run()
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
                self.assertEqual(app.radio[0].value, "Home")
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
            try:
                app_path = Path(__file__).resolve().parents[1] / "app.py"
                app = AppTest.from_file(str(app_path), default_timeout=20).run()
                app.radio[0].set_value("Workout").run()
                app.checkbox[0].set_value(True)
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
                self.assertEqual(app.radio[0].value, "History")
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
                saved_intensity_reps = next(
                    widget for widget in app.selectbox
                    if widget.label == "Intensity reps"
                )
                self.assertEqual(saved_intensity_reps.value, 2)
            finally:
                if previous_path is None:
                    os.environ.pop("WORKOUT_DB_PATH", None)
                else:
                    os.environ["WORKOUT_DB_PATH"] = previous_path


if __name__ == "__main__":
    unittest.main()
