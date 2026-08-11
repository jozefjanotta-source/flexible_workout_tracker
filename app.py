"""Streamlit entrypoint and navigation for the workout tracker."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from streamlit_ui import render_shared_header


st.set_page_config(
    page_title="Heavy Duty Journal",
    page_icon="🏋️",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.html(Path(__file__).resolve().parent / "assets" / "style.css")

color_theme = st.session_state.get("color_theme", "Dark")
if color_theme not in ("Dark", "Light"):
    color_theme = "Dark"
theme_tokens = (
    {
        "background": "#0b1017",
        "surface": "#151d28",
        "surface_strong": "#1d2938",
        "field": "#0f1722",
        "text": "#f8fafc",
        "muted": "#d5deea",
        "border": "#52647a",
        "shadow": "rgba(0, 0, 0, 0.38)",
    }
    if color_theme == "Dark"
    else {
        "background": "#f3f7fc",
        "surface": "#ffffff",
        "surface_strong": "#e8f0fa",
        "field": "#ffffff",
        "text": "#142033",
        "muted": "#46566c",
        "border": "#8798ae",
        "shadow": "rgba(30, 58, 95, 0.16)",
    }
)
st.html(
    "<style>:root {"
    + ";".join(
        f"--hd-{name.replace('_', '-')}:{value}"
        for name, value in theme_tokens.items()
    )
    + ";--text-color:var(--hd-text)"
    + ";--background-color:var(--hd-background)"
    + ";--secondary-background-color:var(--hd-surface)"
    + f";color-scheme:{color_theme.lower()}"
    + "}</style>"
)

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
