"""Streamlit user interface for the flexible workout tracker."""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Callable

import altair as alt
import pandas as pd
import streamlit as st

from database import create_database_backup
from exercise_management import (
    ExerciseError,
    create_exercise,
    list_exercises,
    update_exercise,
)
from init_db import initialize_database
from export_management import build_history_workbook
from progress_calculations import (
    days_since_previous_workout,
    history_dataframe,
    latest_exercise_progress,
    workout_comparison_dataframe,
)
from profile_management import (
    ProfileError,
    create_profile,
    default_profile_id,
    list_profiles,
    update_profile,
)
from routine_management import (
    RoutineError,
    WorkoutExercise,
    add_exercise_to_workout,
    create_routine,
    create_workout,
    duplicate_routine,
    list_routines,
    list_workout_exercises,
    list_workouts,
    move_workout_exercise,
    remove_exercise_from_workout,
    update_routine,
    update_workout,
    update_workout_exercise,
)
from workout_logging import (
    delete_completed_session,
    delete_logged_set,
    ExerciseLog,
    SetEntry,
    WorkoutLogError,
    get_previous_results,
    get_session_review,
    list_sessions,
    save_completed_session,
    update_logged_set,
)


APP_SCHEMA_VERSION = "v6_intensity_reps"


@st.cache_resource(show_spinner=False)
def initialize_app_database(database_identity: str, schema_version: str) -> None:
    """Initialize and migrate the database once per schema and app process."""
    del database_identity, schema_version
    initialize_database()


initialize_app_database(
    os.getenv("TURSO_DATABASE_URL")
    or os.getenv("WORKOUT_DB_PATH")
    or "local-default",
    APP_SCHEMA_VERSION,
)

INTENSITY_METHODS = (
    "",
    "Forced",
    "Negative",
    "Static holds",
    "Forced negative",
    "Partials",
    "Rest-pause",
    "Omni-contraction",
)
REP_OPTIONS = tuple(range(1, 101))
INTENSITY_REP_OPTIONS = tuple(range(0, 101))


st.markdown(
    """
    <style>
    .block-container {max-width: 1120px; padding-top: 2rem;}
    [data-testid="stMetric"] {background: rgba(128, 128, 128, 0.10); border: 1px solid rgba(128, 128, 128, 0.22); border-radius: 0.7rem; padding: 0.8rem;}
    @media (max-width: 640px) {
        .block-container {
            padding-top: 4.75rem;
            padding-left: 1rem;
            padding-right: 1rem;
            padding-bottom: 7rem;
        }
        div[data-baseweb="select"] > div {min-height: 44px;}
        .st-key-save_workout_action {
            position: fixed;
            left: 1rem;
            right: 1rem;
            bottom: 0.75rem;
            z-index: 999;
            padding: 0.5rem;
            border: 1px solid var(--st-border-color);
            border-radius: 0.75rem;
            background: var(--st-background-color);
            box-shadow: 0 0.35rem 1rem rgba(0, 0, 0, 0.18);
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def show_error(action: Callable[[], object]) -> bool:
    """Run a UI action and show expected domain/database errors cleanly."""
    try:
        action()
        return True
    except (ExerciseError, ProfileError, RoutineError, WorkoutLogError, ValueError) as exc:
        st.error(str(exc))
        return False
    except Exception as exc:  # UI boundary: do not crash the whole app.
        st.error(f"Unexpected error: {exc}")
        return False


def format_weight(value: object) -> str:
    """Show only the decimal places required by a 0.25 kg increment."""
    weight = float(value)
    quarter_units = round(weight * 4)
    quarter_remainder = quarter_units % 4
    decimals = (
        0 if quarter_remainder == 0 else 1 if quarter_remainder == 2 else 2
    )
    return f"{weight:.{decimals}f}"


def format_sets(sets: list[dict[str, object]]) -> str:
    if not sets:
        return "No completed sets"
    formatted: list[str] = []
    for row in sets:
        result = f"{format_weight(row['weight'])} × {row['reps']}"
        method = str(row.get("intensity_method") or "")
        intensity_reps = int(row.get("intensity_reps") or 0)
        if method:
            result += f" · {method}"
            if intensity_reps:
                result += f": {intensity_reps} reps"
        formatted.append(result)
    return " · ".join(formatted)


def current_profile_id() -> int:
    """Return the profile chosen in the persistent top-level selector."""
    profile_id = st.session_state.get("active_profile_id")
    if not isinstance(profile_id, int):
        raise ProfileError("Select a training profile.")
    return profile_id


def format_date(value: object) -> str:
    """Format a stored date consistently for the interface."""
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        try:
            parsed = date.fromisoformat(str(value)[:10])
        except ValueError:
            return str(value)
    return parsed.strftime("%d/%m/%y")


def format_datetime(value: object) -> str:
    """Format a stored completion timestamp for the interface."""
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return str(value)
    return parsed.strftime("%d/%m/%y %H:%M")


def progress_chart(frame: pd.DataFrame) -> alt.LayerChart:
    """Plot weight bars and a reps line only on dates containing results."""
    chart_frame = frame.copy()
    chart_frame["date"] = pd.to_datetime(chart_frame["date"])
    chart_frame = chart_frame.sort_values("date", kind="stable").reset_index(drop=True)
    chart_frame["weight_display"] = chart_frame["weight"].map(format_weight)
    weekday_short = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    weekday_full = (
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
        "Sunday",
    )
    chart_frame["weekday_short"] = chart_frame["date"].dt.dayofweek.map(
        dict(enumerate(weekday_short))
    )
    chart_frame["weekday_full"] = chart_frame["date"].dt.dayofweek.map(
        dict(enumerate(weekday_full))
    )
    chart_frame["calendar_week"] = (
        chart_frame["date"].dt.isocalendar().week.astype(int)
    )
    chart_frame["calendar_week_label"] = chart_frame["calendar_week"].map(
        lambda value: f"W{value:02d}"
    )
    chart_frame["date_axis_base"] = (
        chart_frame["weekday_short"]
        + " "
        + chart_frame["date"].dt.strftime("%d/%m")
        + " · "
        + chart_frame["calendar_week_label"]
    )
    chart_frame["date_tooltip"] = chart_frame["date"].dt.strftime("%d/%m/%y")
    chart_frame["date_occurrence"] = (
        chart_frame.groupby("date_axis_base").cumcount() + 1
    )
    chart_frame["date_count"] = chart_frame.groupby("date_axis_base")[
        "date_axis_base"
    ].transform("count")
    chart_frame["date_label"] = chart_frame.apply(
        lambda row: row["date_axis_base"]
        if row["date_count"] == 1
        else f"{row['date_axis_base']} ({int(row['date_occurrence'])})",
        axis=1,
    )
    date_order = chart_frame["date_label"].tolist()
    chart_frame["chart_position"] = range(1, len(chart_frame) + 1)
    chart_positions = chart_frame["chart_position"].tolist()
    # Keep short histories centered and separated without squeezing the chart.
    # Five virtual slots give two sessions distinct positions on desktop and phone.
    padding_slots = max((5 - len(chart_positions)) / 2, 0)
    x_domain = [
        0.5 - padding_slots,
        len(chart_positions) + 0.5 + padding_slots,
    ]
    axis_label_expression = f"{date_order!r}[datum.value - 1]"
    tooltip = [
        alt.Tooltip("date_tooltip:N", title="Date"),
        alt.Tooltip("weekday_full:N", title="Day"),
        alt.Tooltip("calendar_week_label:N", title="Calendar week"),
        alt.Tooltip("workout_name:N", title="Workout"),
        alt.Tooltip("weight_display:N", title="Weight"),
        alt.Tooltip("reps:Q", title="Reps"),
        alt.Tooltip("evaluation:N", title="Evaluation"),
    ]
    x_axis = alt.X(
        "chart_position:Q",
        title="Date",
        scale=alt.Scale(
            domain=x_domain,
            nice=False,
            zero=False,
        ),
        axis=alt.Axis(
            values=chart_positions,
            labelExpr=axis_label_expression,
            labelAngle=-35,
            labelOverlap=False,
            labelFlush=False,
            tickMinStep=1,
        ),
    )
    evaluation_color = alt.Color(
        "evaluation:N",
        title="Evaluation",
        legend=alt.Legend(orient="top", direction="horizontal"),
        scale=alt.Scale(
            domain=["Baseline", "Progress", "No progress", "Regression"],
            range=["#64748B", "#16A34A", "#D97706", "#DC2626"],
        ),
    )
    base = alt.Chart(chart_frame).encode(x=x_axis)
    weight_y = alt.Y(
        "weight:Q",
        title="Weight",
        scale=alt.Scale(zero=True),
        axis=alt.Axis(
            titleColor="#2563EB", labelColor="#2563EB", format="~f"
        ),
    )
    reps_y = alt.Y(
        "reps:Q",
        title="Reps",
        scale=alt.Scale(zero=False),
        axis=alt.Axis(
            titleColor="#EA580C",
            labelColor="#EA580C",
            orient="right",
            tickMinStep=1,
            format="d",
        ),
    )
    weight_bars = base.mark_bar(
        color="#2563EB", opacity=0.58, size=22
    ).encode(y=weight_y, tooltip=tooltip)
    reps_line = base.mark_line(
        color="#EA580C", strokeWidth=3
    ).encode(y=reps_y)
    reps_points = base.mark_point(filled=True, size=95, shape="square").encode(
        y=reps_y, color=evaluation_color, tooltip=tooltip
    )
    return (
        alt.layer(weight_bars, reps_line, reps_points)
        .resolve_scale(y="independent")
        .properties(height=330)
    )


def dashboard_page() -> None:
    st.title("Workout tracker")
    st.caption("Your Heavy Duty training at a glance.")
    profile_id = current_profile_id()
    sessions = list_sessions(profile_id=profile_id)
    days = days_since_previous_workout(profile_id=profile_id)
    latest_frame = latest_exercise_progress(profile_id=profile_id)
    progress_count = (
        int((latest_frame["evaluation"] == "Progress").sum())
        if not latest_frame.empty
        else 0
    )
    last_workout = sessions[0]["workout_name"] if sessions else "None yet"

    if st.button(
        "Start workout",
        type="primary",
        icon=":material/fitness_center:",
        width="stretch",
    ):
        st.session_state["navigate_after_rerun"] = "Workout"
        st.rerun()

    columns = st.columns(3)
    columns[0].metric(
        "Days since last workout",
        days if days is not None else "—",
        border=True,
    )
    columns[1].metric("Last workout", last_workout, border=True)
    columns[2].metric("Exercises progressing", progress_count, border=True)

    st.subheader("Recent workouts")
    if not sessions:
        st.info("No sessions yet. Build or select a routine, then log your first workout.")
        return
    for session in sessions[:4]:
        with st.container(border=True):
            name_col, date_col = st.columns([3, 1])
            name_col.markdown(f"**{session['workout_name']}**")
            name_col.caption(session["routine_name"])
            date_col.markdown(f"**{format_date(session['workout_date'])}**")
            st.caption(
                f"{session['exercise_count']} exercises · "
                f"{session['set_count']} completed sets"
            )

    st.subheader("Latest exercise progress")
    if latest_frame.empty:
        st.info("Log another result for an exercise to start evaluating progress.")
        return

    latest_frame = latest_frame.rename(
        columns={
            "exercise": "Exercise",
            "date": "Date",
            "weight": "Weight",
            "reps": "Reps",
            "evaluation": "Evaluation",
        }
    ).sort_values(["Date", "Exercise"], ascending=[False, True])
    latest_frame["Date"] = latest_frame["Date"].dt.strftime("%d/%m/%y")
    latest_frame["Weight"] = latest_frame["Weight"].map(format_weight)
    evaluation_colors = {
        "Progress": "green",
        "No progress": "orange",
        "Regression": "red",
        "Baseline": "gray",
    }
    for _, row in latest_frame.head(8).iterrows():
        with st.container(border=True):
            name_col, status_col = st.columns([3, 1])
            name_col.markdown(f"**{row['Exercise']}**")
            status_col.badge(
                str(row["Evaluation"]),
                color=evaluation_colors.get(str(row["Evaluation"]), "gray"),
            )
            st.caption(
                f"{row['Weight']} kg × {int(row['Reps'])} reps · {row['Date']}"
            )


def profiles_page() -> None:
    st.title("Profiles")
    st.caption("Profiles keep each person's workout history and progress separate.")
    mode = st.segmented_control(
        "Profile action",
        ["Create profile", "Manage profiles"],
        default="Manage profiles",
        key="profile_action",
    )
    if mode == "Create profile":
        with st.form("create_profile", clear_on_submit=True):
            name = st.text_input("Profile name")
            notes = st.text_area("Notes", placeholder="Optional coaching or profile notes")
            submitted = st.form_submit_button("Create profile")
        if submitted and show_error(lambda: create_profile(name, notes)):
            st.success("Profile created.")
            st.rerun()

    if mode == "Manage profiles":
        profiles = list_profiles()
        for profile in profiles:
            status = "Active" if profile.active else "Archived"
            status_icon = "●" if profile.active else "○"
            with st.expander(f"{status_icon} {profile.name} · {status}"):
                with st.form(f"edit_profile_{profile.id}"):
                    edited_name = st.text_input("Profile name", value=profile.name)
                    edited_notes = st.text_area("Notes", value=profile.notes)
                    edited_active = st.checkbox("Active", value=profile.active)
                    saved = st.form_submit_button("Save profile")
                if saved and show_error(
                    lambda item=profile: update_profile(
                        item.id,
                        name=edited_name,
                        notes=edited_notes,
                        active=edited_active,
                    )
                ):
                    st.success("Profile updated.")
                    st.rerun()


def exercises_page() -> None:
    st.title("Exercise library")
    mode = st.segmented_control(
        "Exercise action",
        ["Create exercise", "Manage library"],
        default="Manage library",
        key="exercise_action",
    )
    if mode == "Create exercise":
        with st.form("create_exercise", clear_on_submit=True):
            name = st.text_input("Exercise name")
            col1, col2 = st.columns(2)
            muscle = col1.text_input("Primary muscle group")
            equipment = col2.text_input("Equipment")
            notes = st.text_area("Notes")
            submitted = st.form_submit_button("Create exercise", type="primary")
        if submitted and show_error(lambda: create_exercise(name, muscle, equipment, notes)):
            st.success("Exercise created.")
            st.rerun()

    if mode == "Manage library":
        exercises = list_exercises()
        if not exercises:
            st.info("The exercise library is empty.")
            return
        state_filter = st.segmented_control(
            "Show", ["Active", "Inactive", "All"], default="Active"
        )
        shown = [
            exercise
            for exercise in exercises
            if state_filter == "All"
            or (state_filter == "Active" and exercise.active)
            or (state_filter == "Inactive" and not exercise.active)
        ]
        for exercise in shown:
            status = "Active" if exercise.active else "Inactive"
            status_icon = "●" if exercise.active else "○"
            with st.expander(
                f"{status_icon} {exercise.name} · "
                f"{exercise.primary_muscle_group} · {status}"
            ):
                with st.form(f"edit_exercise_{exercise.id}"):
                    edit_name = st.text_input("Exercise name", exercise.name)
                    col1, col2 = st.columns(2)
                    edit_muscle = col1.text_input("Primary muscle group", exercise.primary_muscle_group)
                    edit_equipment = col2.text_input("Equipment", exercise.equipment)
                    edit_notes = st.text_area("Notes", exercise.notes)
                    edit_active = st.checkbox("Active", exercise.active)
                    save = st.form_submit_button("Save changes")
                if save and show_error(
                    lambda e=exercise: update_exercise(
                        e.id,
                        name=edit_name,
                        primary_muscle_group=edit_muscle,
                        equipment=edit_equipment,
                        notes=edit_notes,
                        active=edit_active,
                    )
                ):
                    st.success("Exercise updated.")
                    st.rerun()


def routines_page() -> None:
    st.title("Routine builder")
    routines = list_routines()
    mode = st.segmented_control(
        "Routine action",
        ["Create routine", "Edit routine"],
        default="Edit routine",
        key="routine_action",
    )
    if mode == "Create routine":
        with st.form("create_routine", clear_on_submit=True):
            name = st.text_input("Routine name")
            description = st.text_area("Description")
            create = st.form_submit_button("Create routine", type="primary")
        if create and show_error(lambda: create_routine(name, description)):
            st.success("Routine created. Add its first workout in the Edit routine tab.")
            st.rerun()

        if routines:
            st.divider()
            st.subheader("Duplicate routine")
            st.caption("Copies the active workout structure and targets, but not history.")
            duplicate_labels = {routine.id: routine.name for routine in routines}
            with st.form("duplicate_routine", clear_on_submit=True):
                source_routine_id = st.selectbox(
                    "Source routine",
                    list(duplicate_labels),
                    format_func=duplicate_labels.get,
                )
                duplicate_name = st.text_input("New routine name")
                duplicate = st.form_submit_button("Duplicate routine")
            if duplicate and show_error(
                lambda: duplicate_routine(source_routine_id, duplicate_name)
            ):
                st.success("Routine duplicated. Its history starts empty.")
                st.rerun()

    if mode == "Edit routine":
        if not routines:
            st.info("Create a routine first.")
            return
        routine_labels = {routine.id: routine.name for routine in routines}
        routine_id = st.selectbox(
            "Routine", list(routine_labels), format_func=routine_labels.get, key="builder_routine"
        )
        routine = next(item for item in routines if item.id == routine_id)
        with st.expander("Routine details"):
            with st.form(f"edit_routine_{routine.id}"):
                routine_name = st.text_input("Name", routine.name)
                routine_description = st.text_area("Description", routine.description)
                routine_active = st.checkbox("Active", routine.active)
                save_routine = st.form_submit_button("Save routine")
            if save_routine and show_error(
                lambda: update_routine(
                    routine.id,
                    name=routine_name,
                    description=routine_description,
                    active=routine_active,
                )
            ):
                st.success("Routine updated.")
                st.rerun()

        st.subheader("Workouts")
        with st.form(f"new_workout_{routine.id}", clear_on_submit=True):
            col1, col2 = st.columns([2, 3])
            workout_name = col1.text_input("New workout name")
            workout_description = col2.text_input("Description")
            add_workout = st.form_submit_button("Add workout")
        if add_workout and show_error(
            lambda: create_workout(routine.id, workout_name, workout_description)
        ):
            st.success("Workout added.")
            st.rerun()

        workouts = list_workouts(routine.id)
        if not workouts:
            st.info("This routine has no workouts yet.")
            return
        workout_labels = {
            workout.id: f"{workout.position}. {workout.name}{'' if workout.active else ' (inactive)'}"
            for workout in workouts
        }
        workout_id = st.selectbox(
            "Configure workout", list(workout_labels), format_func=workout_labels.get
        )
        workout = next(item for item in workouts if item.id == workout_id)
        with st.expander("Workout details"):
            with st.form(f"edit_workout_{workout.id}"):
                edit_name = st.text_input("Workout name", workout.name)
                edit_description = st.text_area("Description", workout.description)
                edit_active = st.checkbox("Active", workout.active)
                save_workout = st.form_submit_button("Save workout")
            if save_workout and show_error(
                lambda: update_workout(
                    workout.id,
                    name=edit_name,
                    description=edit_description,
                    active=edit_active,
                )
            ):
                st.success("Workout updated.")
                st.rerun()

        active_exercises = list_exercises(active_only=True)
        configured = list_workout_exercises(workout.id)
        configured_ids = {item.exercise_id for item in configured}
        available = [item for item in active_exercises if item.id not in configured_ids]
        st.markdown("#### Add exercise")
        if available:
            exercise_labels = {item.id: f"{item.name} · {item.equipment}" for item in available}
            with st.form(f"add_exercise_{workout.id}", clear_on_submit=True):
                exercise_id = st.selectbox(
                    "Exercise", list(exercise_labels), format_func=exercise_labels.get
                )
                col1, col2 = st.columns(2)
                minimum = col1.number_input("Minimum reps", 1, 100, 6)
                maximum = col2.number_input("Maximum reps", 1, 100, 10)
                st.caption("Heavy Duty target: 1 working set")
                instructions = st.text_input("Optional instructions")
                add = st.form_submit_button("Add to workout")
            if add and show_error(
                lambda: add_exercise_to_workout(
                    workout.id,
                    exercise_id,
                    target_min_reps=int(minimum),
                    target_max_reps=int(maximum),
                    target_sets=1,
                    instructions=instructions,
                )
            ):
                st.success("Exercise added.")
                st.rerun()
        else:
            st.caption("Every active library exercise is already in this workout.")

        st.markdown("#### Exercise order and targets")
        configured = list_workout_exercises(workout.id)
        if not configured:
            st.info("Add at least one exercise before logging this workout.")
        for index, item in enumerate(configured):
            with st.expander(
                f"{item.position}. {item.exercise_name} · "
                f"1 × {item.target_min_reps}–{item.target_max_reps}"
            ):
                left, middle, right = st.columns([1, 1, 5])
                if left.button("↑", key=f"up_{item.id}", disabled=index == 0):
                    if show_error(lambda current=item: move_workout_exercise(current.id, -1)):
                        st.rerun()
                if middle.button("↓", key=f"down_{item.id}", disabled=index == len(configured) - 1):
                    if show_error(lambda current=item: move_workout_exercise(current.id, 1)):
                        st.rerun()
                right.caption(f"{item.primary_muscle_group} · {item.equipment}")
                with st.form(f"targets_{item.id}"):
                    col1, col2 = st.columns(2)
                    new_min = col1.number_input("Minimum reps", 1, 100, item.target_min_reps)
                    new_max = col2.number_input("Maximum reps", 1, 100, item.target_max_reps)
                    st.caption("Heavy Duty target: 1 working set")
                    new_instructions = st.text_input("Instructions", item.instructions)
                    save_targets = st.form_submit_button("Save targets")
                if save_targets and show_error(
                    lambda current=item: update_workout_exercise(
                        current.id,
                        target_min_reps=int(new_min),
                        target_max_reps=int(new_max),
                        target_sets=1,
                        instructions=new_instructions,
                    )
                ):
                    st.success("Targets updated.")
                    st.rerun()
                if st.button("Remove from workout", key=f"remove_{item.id}"):
                    if show_error(lambda current=item: remove_exercise_from_workout(current.id)):
                        st.rerun()


def _workout_exercise_card(
    item: WorkoutExercise,
    *,
    workout_id: int,
    previous: dict[str, object] | None,
) -> dict[str, object]:
    """Render one compact, phone-friendly exercise entry card."""
    previous_sets = list(previous["sets"]) if previous else []
    previous_set = previous_sets[0] if previous_sets else {}
    default_weight = round(
        float(previous_set.get("weight", 0.0) or 0.0) * 4
    ) / 4
    default_reps = int(
        previous_set.get("reps", item.target_min_reps)
        or item.target_min_reps
    )
    default_reps = min(max(default_reps, REP_OPTIONS[0]), REP_OPTIONS[-1])
    key_prefix = f"{workout_id}_{item.id}_1"
    completed_key = f"log_done_{key_prefix}"
    completed_before_render = bool(st.session_state.get(completed_key, False))
    status = " ✓" if completed_before_render else ""
    with st.expander(
        f"{item.position}. {item.exercise_name}{status}",
        expanded=item.position == 1 and not completed_before_render,
    ):
        st.caption(
            f"Target: 1 working set of "
            f"{item.target_min_reps}-{item.target_max_reps} reps"
            + (f" | {item.instructions}" if item.instructions else "")
        )
        if previous:
            st.info(
                f"Previous | {format_date(previous['workout_date'])} | "
                f"{previous['workout_name']}: {format_sets(previous_sets)}"
            )
        else:
            st.caption("No previous result for this exercise.")

        completed = st.checkbox("Completed", key=completed_key)
        weight_col, reps_col = st.columns(2)
        weight = weight_col.number_input(
            "Weight",
            min_value=0.0,
            max_value=1000.0,
            value=default_weight,
            step=0.25,
            format="%g",
            key=f"log_weight_{key_prefix}",
            help="Use the minus and plus buttons; each step is 0.25 kg.",
        )
        weight_col.caption(f"{format_weight(weight)} kg")
        reps = reps_col.selectbox(
            "Reps",
            REP_OPTIONS,
            index=REP_OPTIONS.index(default_reps),
            key=f"log_reps_{key_prefix}",
        )
        intensity_col, intensity_reps_col = st.columns([2, 1])
        intensity = intensity_col.selectbox(
            "Intensity method",
            INTENSITY_METHODS,
            key=f"log_intensity_{key_prefix}",
            format_func=lambda value: value or "None",
        )
        intensity_reps = intensity_reps_col.selectbox(
            "Intensity reps",
            INTENSITY_REP_OPTIONS,
            key=f"log_intensity_reps_{key_prefix}",
            disabled=not bool(intensity),
            format_func=lambda value: "Not recorded" if value == 0 else str(value),
            help="Reps performed using the selected intensity method.",
        )
        set_notes = st.text_input(
            "Set notes",
            placeholder="Optional",
            key=f"log_set_notes_{key_prefix}",
        )
    return {
        "completed": completed,
        "weight": weight,
        "reps": reps,
        "intensity_method": intensity,
        "intensity_reps": intensity_reps if intensity else 0,
        "notes": set_notes,
    }


def log_workout_page() -> None:
    st.title("Workout")
    st.caption("Choose a workout, record completed sets, then save or cancel the draft.")
    profile_id = current_profile_id()
    routines = list_routines(active_only=True)
    if not routines:
        st.info("Create and activate a routine before logging a workout.")
        return
    routine_labels = {item.id: item.name for item in routines}
    with st.container(border=True, key="workout_selector"):
        selector_col1, selector_col2 = st.columns(2)
        routine_id = selector_col1.selectbox(
            "Routine",
            list(routine_labels),
            format_func=routine_labels.get,
            key="log_routine_id",
        )
        workouts = list_workouts(routine_id, active_only=True)
        if not workouts:
            st.info("This routine has no active workouts.")
            return
        workout_labels = {item.id: item.name for item in workouts}
        workout_id = selector_col2.selectbox(
            "Workout",
            list(workout_labels),
            format_func=workout_labels.get,
            key="log_workout_id",
        )
    configured = list_workout_exercises(workout_id)
    if not configured:
        st.warning("This workout has no exercises. Add some in Manage.")
        return

    date_key = f"log_date_{workout_id}"
    time_key = f"log_time_{workout_id}"
    notes_key = f"log_notes_{workout_id}"
    with st.expander("Workout details"):
        col1, col2 = st.columns(2)
        session_date = col1.date_input("Workout date", date.today(), key=date_key)
        completion_time = col2.time_input(
            "Completion time",
            datetime.now().time().replace(microsecond=0),
            key=time_key,
        )
        session_notes = st.text_area(
            "Session notes",
            placeholder="Optional notes about the workout",
            key=notes_key,
        )

    previous_results = get_previous_results(
        (item.exercise_id for item in configured), profile_id=profile_id
    )
    draft_sets: dict[int, list[dict[str, object]]] = {}

    def clear_draft_widgets() -> None:
        """Remove every widget value belonging to the current workout draft."""
        for configured_item in configured:
            key_prefix = f"{workout_id}_{configured_item.id}_1"
            for field in (
                "done", "weight", "reps", "intensity", "intensity_reps",
                "set_notes",
            ):
                st.session_state.pop(f"log_{field}_{key_prefix}", None)

    completed_count = sum(
        bool(st.session_state.get(f"log_done_{workout_id}_{item.id}_1", False))
        for item in configured
    )
    st.progress(
        completed_count / len(configured),
        text=f"{completed_count} of {len(configured)} exercises completed",
    )
    for item in configured:
        draft_sets[item.id] = [
            _workout_exercise_card(
                item,
                workout_id=workout_id,
                previous=previous_results.get(item.exercise_id),
            )
        ]

    cancel_state_key = f"cancel_workout_{workout_id}"
    with st.container(key="save_workout_action"):
        save_col, cancel_col = st.columns([2, 1])
        save_workout = save_col.button(
            "Complete and save", type="primary", width="stretch"
        )
        request_cancel = cancel_col.button(
            "Cancel workout", width="stretch"
        )
    if request_cancel:
        st.session_state[cancel_state_key] = True
        st.rerun()

    if st.session_state.get(cancel_state_key):
        st.warning("Cancel this workout and discard every unsaved value?")
        discard_col, keep_col = st.columns(2)
        discard = discard_col.button(
            "Discard workout", type="primary", width="stretch"
        )
        keep = keep_col.button("Keep logging", width="stretch")
        if keep:
            st.session_state.pop(cancel_state_key, None)
            st.rerun()
        if discard:
            clear_draft_widgets()
            for key in (date_key, time_key, notes_key, cancel_state_key):
                st.session_state.pop(key, None)
            st.session_state["workout_cancelled"] = True
            st.session_state["navigate_after_rerun"] = "Home"
            st.rerun()

    if save_workout:
        logs: list[ExerciseLog] = []
        for item in configured:
            entries = tuple(
                SetEntry(
                    weight=round(float(row["weight"]), 2),
                    reps=int(row["reps"]),
                    intensity_method=str(row["intensity_method"] or ""),
                    intensity_reps=int(row["intensity_reps"]),
                    notes=str(row["notes"] or ""),
                )
                for row in draft_sets[item.id]
                if bool(row["completed"])
            )
            logs.append(ExerciseLog(item.id, entries))
        completed_at = datetime.combine(session_date, completion_time)
        saved_id: list[int] = []
        if show_error(
            lambda: saved_id.append(
                save_completed_session(
                    routine_id,
                    workout_id,
                    session_date,
                    completed_at,
                    logs,
                    profile_id=profile_id,
                    notes=session_notes,
                )
            )
        ):
            st.session_state["last_saved_session"] = saved_id[0]
            clear_draft_widgets()
            for key in (date_key, time_key, notes_key, cancel_state_key):
                st.session_state.pop(key, None)
            st.session_state["workout_saved"] = True
            st.session_state["navigate_after_rerun"] = "History"
            st.rerun()


@st.dialog("Delete completed workout")
def _delete_completed_workout_dialog(
    session_id: int,
    *,
    profile_id: int,
    session_label: str,
) -> None:
    st.warning(
        "This permanently deletes the completed workout and all of its logged "
        "sets. The routine template will not be changed."
    )
    st.caption(session_label)
    confirm_col, keep_col = st.columns(2)
    confirm_delete = confirm_col.button(
        "Delete permanently",
        type="primary",
        width="stretch",
    )
    keep_workout = keep_col.button("Keep workout", width="stretch")
    if keep_workout:
        st.rerun()
    if confirm_delete and show_error(
        lambda: delete_completed_session(
            session_id,
            profile_id=profile_id,
        )
    ):
        st.session_state.pop("prepared_history_downloads", None)
        st.session_state["completed_workout_deleted"] = True
        st.rerun()


def history_page() -> None:
    st.title("History")
    st.caption("Find and review completed workout sessions.")
    if st.session_state.pop("completed_workout_deleted", False):
        st.success("Completed workout deleted.")
    profile_id = current_profile_id()
    routines = list_routines()
    exercises = list_exercises()
    routine_options = {0: "All routines", **{item.id: item.name for item in routines}}
    with st.popover("Filters", width="stretch"):
        routine_id = st.selectbox(
            "Routine", list(routine_options), format_func=routine_options.get
        )
        workouts = list_workouts(routine_id) if routine_id else []
        workout_options = {
            0: "All workouts",
            **{item.id: item.name for item in workouts},
        }
        workout_id = st.selectbox(
            "Workout", list(workout_options), format_func=workout_options.get
        )
        exercise_options = {
            0: "All exercises",
            **{item.id: item.name for item in exercises},
        }
        exercise_id = st.selectbox(
            "Exercise", list(exercise_options), format_func=exercise_options.get
        )
        date_col1, date_col2 = st.columns(2)
        date_from = date_col1.date_input("From", value=None)
        date_to = date_col2.date_input("To", value=None)
    active_filters = sum(
        bool(value)
        for value in (routine_id, workout_id, exercise_id, date_from, date_to)
    )
    st.caption(
        "Showing all completed workouts"
        if active_filters == 0
        else f"{active_filters} history filter(s) active"
    )
    sessions = list_sessions(
        profile_id=profile_id,
        routine_id=routine_id or None,
        workout_id=workout_id or None,
        exercise_id=exercise_id or None,
        date_from=date_from,
        date_to=date_to,
    )

    with st.expander("Export and archive"):
        st.caption("Downloads are prepared only when requested, keeping this page faster.")
        signature = (
            profile_id,
            routine_id,
            workout_id,
            exercise_id,
            str(date_from),
            str(date_to),
            len(sessions),
        )
        prepare = st.button(
            "Prepare downloads",
            disabled=not sessions,
            key="prepare_history_downloads",
        )
        if prepare:
            with st.spinner("Preparing files..."):
                filtered_history = history_dataframe(
                    profile_id=profile_id,
                    routine_id=routine_id or None,
                    workout_id=workout_id or None,
                    exercise_id=exercise_id or None,
                    date_from=date_from,
                    date_to=date_to,
                )
                csv_history = filtered_history.copy()
                if not csv_history.empty:
                    csv_history["date"] = pd.to_datetime(
                        csv_history["date"]
                    ).dt.strftime("%d/%m/%y")
                st.session_state["prepared_history_downloads"] = {
                    "signature": signature,
                    "excel": build_history_workbook(sessions, filtered_history),
                    "csv": csv_history.to_csv(index=False).encode("utf-8"),
                    "backup": create_database_backup(),
                }
        prepared = st.session_state.get("prepared_history_downloads")
        if prepared and prepared.get("signature") == signature:
            export_col1, export_col2, export_col3 = st.columns(3)
            export_col1.download_button(
                "Download Excel",
                data=prepared["excel"],
                file_name=f"workout_history_{date.today().isoformat()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )
            export_col2.download_button(
                "Download CSV",
                data=prepared["csv"],
                file_name=f"workout_history_{date.today().isoformat()}.csv",
                mime="text/csv",
                width="stretch",
            )
            export_col3.download_button(
                "Archive database",
                data=prepared["backup"],
                file_name=f"workout_tracker_backup_{date.today().isoformat()}.db",
                mime="application/vnd.sqlite3",
                width="stretch",
            )

    if not sessions:
        st.info("No sessions match these filters.")
        return

    session_labels = {
        int(row["id"]): (
            f"{format_date(row['workout_date'])} | "
            f"{row['routine_name']} / {row['workout_name']} | "
            f"{row['set_count']} sets"
        )
        for row in sessions
    }
    default_id = st.session_state.pop("last_saved_session", None)
    ids = list(session_labels)
    default_index = ids.index(default_id) if default_id in ids else 0
    selected_id = st.selectbox(
        "Review completed session",
        ids,
        index=default_index,
        format_func=session_labels.get,
        key="history_review_session",
    )
    review = get_session_review(selected_id)
    with st.container(border=True):
        title_col, status_col = st.columns([3, 1])
        title_col.markdown(f"### {review['workout_name']}")
        status_col.badge("Completed", color="green")
        st.caption(
            f"{review['routine_name']} · {format_date(review['workout_date'])} · "
            f"{format_datetime(review['completed_at'])}"
        )
        if review["notes"]:
            st.write(review["notes"])
        if st.button(
            "Delete complete workout",
            icon=":material/delete:",
            key=f"request_delete_session_{selected_id}",
        ):
            _delete_completed_workout_dialog(
                selected_id,
                profile_id=profile_id,
                session_label=session_labels[selected_id],
            )

    for item in review["exercises"]:
        with st.expander(
            f"{item['position']}. {item['exercise_name']} | "
            f"{len(item['sets'])} completed sets"
        ):
            st.caption(
                f"Historic target: {item['target_sets']} x "
                f"{item['target_min_reps']}-{item['target_max_reps']}"
            )
            if item["instructions"]:
                st.caption(item["instructions"])
            if not item["sets"]:
                st.caption("Skipped in this session.")
                continue
            st.caption("Correct a value or delete an incorrectly logged set.")
            for set_row in item["sets"]:
                with st.form(f"edit_logged_set_{set_row['id']}"):
                    col1, col2 = st.columns(2)
                    corrected_weight = col1.number_input(
                        "Weight",
                        min_value=0.0,
                        value=round(float(set_row["weight"]) * 4) / 4,
                        step=0.25,
                        format="%g",
                    )
                    col1.caption(f"{format_weight(corrected_weight)} kg")
                    current_reps = int(set_row["reps"])
                    corrected_rep_options = list(REP_OPTIONS)
                    if current_reps not in corrected_rep_options:
                        corrected_rep_options.append(current_reps)
                        corrected_rep_options.sort()
                    corrected_reps = col2.selectbox(
                        "Reps",
                        corrected_rep_options,
                        index=corrected_rep_options.index(current_reps),
                    )
                    current_method = str(set_row["intensity_method"] or "")
                    corrected_method_options = list(INTENSITY_METHODS)
                    if current_method not in corrected_method_options:
                        corrected_method_options.append(current_method)
                    intensity_col, intensity_reps_col = st.columns([2, 1])
                    corrected_method = intensity_col.selectbox(
                        "Intensity method",
                        corrected_method_options,
                        index=corrected_method_options.index(current_method),
                        format_func=lambda value: value or "None",
                    )
                    current_intensity_reps = int(set_row.get("intensity_reps") or 0)
                    corrected_intensity_reps = intensity_reps_col.selectbox(
                        "Intensity reps",
                        INTENSITY_REP_OPTIONS,
                        index=INTENSITY_REP_OPTIONS.index(current_intensity_reps),
                        disabled=not bool(corrected_method),
                        format_func=lambda value: (
                            "Not recorded" if value == 0 else str(value)
                        ),
                    )
                    corrected_notes = st.text_input(
                        "Set notes", value=set_row["notes"]
                    )
                    save_col, delete_col = st.columns(2)
                    save_set = save_col.form_submit_button("Save set")
                    delete_set = delete_col.form_submit_button("Delete set")
                if save_set and show_error(
                    lambda row=set_row: update_logged_set(
                        row["id"],
                        weight=round(float(corrected_weight), 2),
                        reps=int(corrected_reps),
                        intensity_method=corrected_method,
                        intensity_reps=(
                            int(corrected_intensity_reps) if corrected_method else 0
                        ),
                        notes=corrected_notes,
                    )
                ):
                    st.success("Set corrected.")
                    st.rerun()
                if delete_set and show_error(
                    lambda row=set_row: delete_logged_set(row["id"])
                ):
                    st.success("Set deleted.")
                    st.rerun()


def comparison_page() -> None:
    st.title("Compare")
    st.caption(
        "Compare completed workouts and exercises inside one routine. "
        "Weight and reps stay together."
    )
    profile_id = current_profile_id()
    routines = list_routines()
    if not routines:
        st.info("Create a routine first.")
        return
    routine_labels = {item.id: item.name for item in routines}
    routine_id = st.selectbox(
        "Routine",
        list(routine_labels),
        format_func=routine_labels.get,
        key="compare_routine",
    )
    workouts = list_workouts(routine_id)
    if not workouts:
        st.info("This routine has no workouts.")
        return
    workout_labels = {item.id: item.name for item in workouts}
    selected_workouts = st.pills(
        "Workouts",
        list(workout_labels),
        selection_mode="multi",
        default=list(workout_labels),
        format_func=workout_labels.get,
        key=f"compare_workouts_{routine_id}",
        help="Only workouts from the selected routine can be compared.",
    )
    if not selected_workouts:
        st.info("Select at least one workout.")
        return

    comparison = workout_comparison_dataframe(
        routine_id=routine_id,
        workout_ids=selected_workouts,
        profile_id=profile_id,
    )
    if comparison.empty:
        st.info("No completed sessions are available for this selection.")
        return

    comparison = comparison.sort_values(["date", "completed_at", "exercise"])
    session_index = comparison[
        ["session_id", "date", "completed_at", "workout"]
    ].drop_duplicates("session_id").copy()
    session_index["base_label"] = (
        session_index["date"].dt.strftime("%d/%m/%y")
        + " | " + session_index["workout"].astype(str)
    )
    session_index["occurrence"] = session_index.groupby("base_label").cumcount() + 1
    session_index["duplicates"] = session_index.groupby("base_label")[
        "session_id"
    ].transform("count")
    session_index["label"] = session_index.apply(
        lambda row: row["base_label"] if row["duplicates"] == 1
        else f"{row['base_label']} ({int(row['occurrence'])})",
        axis=1,
    )
    comparison["Session"] = comparison["session_id"].map(
        session_index.set_index("session_id")["label"]
    )
    metrics = st.columns(3)
    metrics[0].metric("Sessions", int(comparison["session_id"].nunique()))
    metrics[1].metric("Workouts", int(comparison["workout_id"].nunique()))
    metrics[2].metric("Exercises", int(comparison["exercise_id"].nunique()))

    st.subheader("Sessions side by side")
    comparison["Result"] = comparison.apply(
        lambda row: f"{format_weight(row['weight'])} x {int(row['reps'])}", axis=1
    )
    session_order = comparison["Session"].drop_duplicates().tolist()
    pivot = comparison.pivot_table(
        index="exercise",
        columns="Session",
        values="Result",
        aggfunc="first",
    ).reindex(columns=session_order)
    pivot.index.name = "Exercise"
    st.dataframe(pivot, width="stretch")

    st.subheader("Exercise trends")
    exercise_names = comparison["exercise"].drop_duplicates().tolist()
    selected_exercises = st.pills(
        "Exercises to chart",
        exercise_names,
        selection_mode="multi",
        default=exercise_names[: min(4, len(exercise_names))],
        key=f"compare_exercises_{routine_id}",
        width="stretch",
    )
    if not selected_exercises:
        st.caption("Select one or more exercises to display their trends.")
        return
    for exercise_name in selected_exercises:
        exercise_frame = comparison[
            comparison["exercise"] == exercise_name
        ].rename(columns={"workout": "workout_name"})
        latest = exercise_frame.iloc[-1]
        evaluation_colors = {
            "Progress": "green",
            "No progress": "orange",
            "Regression": "red",
            "Baseline": "gray",
        }
        with st.container(border=True):
            title_col, status_col = st.columns([3, 1])
            title_col.markdown(f"#### {exercise_name}")
            status_col.badge(
                str(latest["evaluation"]),
                color=evaluation_colors.get(str(latest["evaluation"]), "gray"),
            )
            st.caption(
                f"Latest: {format_weight(latest['weight'])} × "
                f"{int(latest['reps'])} reps · {format_date(latest['date'])}"
            )
            st.altair_chart(
                progress_chart(
                    exercise_frame[
                        ["date", "workout_name", "weight", "reps", "evaluation"]
                    ]
                ),
                width="stretch",
            )


def render_shared_header() -> None:
    """Render profile context and cross-page notifications."""
    active_profiles = list_profiles(active_only=True)
    if not active_profiles:
        st.error(
            "No active profiles are available. "
            "Reactivate or create a profile to continue."
        )
        profiles_page()
        st.stop()
    profile_options = {profile.id: profile.name for profile in active_profiles}
    if st.session_state.get("active_profile_id") not in profile_options:
        st.session_state["active_profile_id"] = default_profile_id()
    with st.container(border=True, key="profile_bar"):
        profile_col, context_col = st.columns(
            [3, 1],
            vertical_alignment="bottom",
        )
        profile_col.caption("Training profile")
        profile_col.selectbox(
            "Training profile",
            list(profile_options),
            format_func=profile_options.get,
            key="active_profile_id",
            label_visibility="collapsed",
        )
        context_col.badge(
            "Cloud synced",
            icon=":material/cloud_done:",
            color="green",
        )
    if st.session_state.pop("workout_cancelled", False):
        st.info("Workout cancelled. Nothing was saved.")
    if st.session_state.pop("workout_saved", False):
        st.success("Workout saved. The completed session is shown below.")
