"""Streamlit entrypoint and navigation for the workout tracker."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from streamlit_ui import render_shared_header


st.set_page_config(
    page_title="Workout Tracker",
    page_icon="🏋️",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.html(Path(__file__).resolve().parent / "assets" / "style.css")

home_page = st.Page(
    "ui_pages/home.py",
    title="Home",
    icon=":material/home:",
    default=True,
)
workout_page = st.Page(
    "ui_pages/workout.py",
    title="Log Workout",
    icon=":material/fitness_center:",
)
compare_page = st.Page(
    "ui_pages/compare.py",
    title="Compare",
    icon=":material/monitoring:",
)
history_page = st.Page(
    "ui_pages/history.py",
    title="History",
    icon=":material/history:",
)
routines_page = st.Page(
    "ui_pages/routines.py",
    title="Routines",
    icon=":material/list_alt:",
)
exercises_page = st.Page(
    "ui_pages/exercises.py",
    title="Exercises",
    icon=":material/exercise:",
)
profiles_page = st.Page(
    "ui_pages/profiles.py",
    title="Profiles",
    icon=":material/group:",
)

page_by_name = {
    "Home": home_page,
    "Workout": workout_page,
    "History": history_page,
}
selected_page = st.navigation(
    {
        "": [home_page, workout_page, compare_page, history_page],
        "Manage": [routines_page, exercises_page, profiles_page],
    },
    position="top",
)

pending_page = st.session_state.pop("navigate_after_rerun", None)
if pending_page in page_by_name:
    st.switch_page(page_by_name[pending_page])
render_shared_header()
selected_page.run()
