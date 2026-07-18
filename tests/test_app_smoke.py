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
                for page in ("Log workout", "History", "Exercises", "Routines"):
                    app.radio[0].set_value(page)
                    app.run()
                    self.assertFalse(app.exception, f"{page} failed to render")
            finally:
                if previous_path is None:
                    os.environ.pop("WORKOUT_DB_PATH", None)
                else:
                    os.environ["WORKOUT_DB_PATH"] = previous_path


if __name__ == "__main__":
    unittest.main()

