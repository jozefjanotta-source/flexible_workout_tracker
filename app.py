"""Streamlit user interface for the flexible workout tracker."""

from __future__ import annotations

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
    exercise_progress,
    history_dataframe,
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
    delete_logged_set,
    ExerciseLog,
    SetEntry,
    WorkoutLogError,
    get_previous_result,
    get_session_review,
    list_sessions,
    save_completed_session,
    update_logged_set,
)


st.set_page_config(page_title="Workout Tracker", page_icon="🏋️", layout="wide", initial_sidebar_state="collapsed")
initialize_database()

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


def format_sets(sets: list[dict[str, object]]) -> str:
    if not sets:
        return "No completed sets"
    return " · ".join(f"{row['weight']:g} × {row['reps']}" for row in sets)


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
    """Plot weight and reps together with independent, readable scales."""
    tooltip = [
        alt.Tooltip("date:T", title="Date", format="%d/%m/%y"),
        alt.Tooltip("workout_name:N", title="Workout"),
        alt.Tooltip("weight:Q", title="Weight"),
        alt.Tooltip("reps:Q", title="Reps"),
        alt.Tooltip("evaluation:N", title="Evaluation"),
    ]
    x_axis = alt.X("date:T", title="Date", axis=alt.Axis(format="%d/%m/%y"))
    evaluation_color = alt.Color(
        "evaluation:N",
        title="Evaluation",
        scale=alt.Scale(
            domain=["Baseline", "Progress", "No progress", "Regression"],
            range=["#64748B", "#16A34A", "#D97706", "#DC2626"],
        ),
    )
    base = alt.Chart(frame).encode(x=x_axis)
    weight_y = alt.Y(
        "weight:Q",
        title="Weight",
        scale=alt.Scale(zero=False),
        axis=alt.Axis(titleColor="#2563EB", labelColor="#2563EB"),
    )
    reps_y = alt.Y(
        "reps:Q",
        title="Reps",
        scale=alt.Scale(zero=False),
        axis=alt.Axis(titleColor="#EA580C", labelColor="#EA580C", orient="right"),
    )
    weight_line = base.mark_line(color="#2563EB", strokeWidth=3).encode(y=weight_y)
    weight_points = base.mark_point(filled=True, size=95).encode(
        y=weight_y, color=evaluation_color, tooltip=tooltip
    )
    reps_line = base.mark_line(color="#EA580C", strokeWidth=3, strokeDash=[6, 3]).encode(y=reps_y)
    reps_points = base.mark_point(filled=True, size=95, shape="square").encode(
        y=reps_y, color=evaluation_color, tooltip=tooltip
    )
    return (
        alt.layer(weight_line, weight_points, reps_line, reps_points)
        .resolve_scale(y="independent")
        .properties(height=360)
    )


def dashboard_page() -> None:
    st.title("Workout tracker")
    st.caption("Flexible routines, straightforward logging, and useful history.")
    routines = list_routines(active_only=True)
    exercises = list_exercises(active_only=True)
    profile_id = current_profile_id()
    sessions = list_sessions(profile_id=profile_id)
    days = days_since_previous_workout(profile_id=profile_id)
    columns = st.columns(4)
    columns[0].metric("Active routines", len(routines))
    columns[1].metric("Active exercises", len(exercises))
    columns[2].metric("Completed sessions", len(sessions))
    columns[3].metric("Days since previous workout", days if days is not None else "—")
    st.subheader("Recent sessions")
    if not sessions:
        st.info("No sessions yet. Build or select a routine, then log your first workout.")
        return
    frame = pd.DataFrame(sessions[:5]).rename(
        columns={
            "workout_date": "Date",
            "routine_name": "Routine",
            "workout_name": "Workout",
            "exercise_count": "Exercises",
            "set_count": "Sets",
        }
    )
    frame["Date"] = frame["Date"].map(format_date)
    st.dataframe(frame[["Date", "Routine", "Workout", "Exercises", "Sets"]], hide_index=True, width="stretch")

    st.subheader("Latest exercise progress")
    latest_rows: list[dict[str, object]] = []
    for exercise in exercises:
        progress = exercise_progress(exercise.id, profile_id=profile_id)
        if progress.empty:
            continue
        latest = progress.iloc[-1]
        latest_rows.append(
            {
                "Exercise": exercise.name,
                "Date": latest["date"],
                "Weight": latest["weight"],
                "Reps": latest["reps"],
                "Evaluation": latest["evaluation"],
            }
        )
    if not latest_rows:
        st.info("Log another result for an exercise to start evaluating progress.")
        return

    latest_frame = pd.DataFrame(latest_rows).sort_values(
        ["Date", "Exercise"], ascending=[False, True]
    )
    evaluations = latest_frame["Evaluation"].value_counts()
    summary_columns = st.columns(4)
    summary_columns[0].metric("Progress", int(evaluations.get("Progress", 0)))
    summary_columns[1].metric("No progress", int(evaluations.get("No progress", 0)))
    summary_columns[2].metric("Regression", int(evaluations.get("Regression", 0)))
    summary_columns[3].metric("Baseline", int(evaluations.get("Baseline", 0)))
    latest_frame["Date"] = latest_frame["Date"].dt.strftime("%d/%m/%y")
    latest_frame["Evaluation"] = latest_frame["Evaluation"].map(
        {
            "Progress": "🟢 Progress",
            "No progress": "🟠 No progress",
            "Regression": "🔴 Regression",
            "Baseline": "⚪ Baseline",
        }
    )
    st.dataframe(latest_frame, hide_index=True, width="stretch")


def profiles_page() -> None:
    st.title("Profiles")
    st.caption("Profiles keep each person's workout history and progress separate.")
    create_tab, manage_tab = st.tabs(["Create profile", "Manage profiles"])
    with create_tab:
        with st.form("create_profile", clear_on_submit=True):
            name = st.text_input("Profile name")
            notes = st.text_area("Notes", placeholder="Optional coaching or profile notes")
            submitted = st.form_submit_button("Create profile")
        if submitted and show_error(lambda: create_profile(name, notes)):
            st.success("Profile created.")
            st.rerun()

    with manage_tab:
        profiles = list_profiles()
        for profile in profiles:
            status = "Active" if profile.active else "Archived"
            with st.expander(f"{profile.name} · {status}"):
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
    create_tab, manage_tab = st.tabs(["Create exercise", "Manage library"])
    with create_tab:
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

    with manage_tab:
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
            with st.expander(f"{exercise.name} · {exercise.primary_muscle_group} · {status}"):
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
    create_tab, edit_tab = st.tabs(["Create routine", "Edit routine"])
    with create_tab:
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

    with edit_tab:
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
                col1, col2, col3 = st.columns(3)
                minimum = col1.number_input("Minimum reps", 1, 100, 6)
                maximum = col2.number_input("Maximum reps", 1, 100, 10)
                target_sets = col3.number_input("Working sets", 1, 20, 1)
                instructions = st.text_input("Optional instructions")
                add = st.form_submit_button("Add to workout")
            if add and show_error(
                lambda: add_exercise_to_workout(
                    workout.id,
                    exercise_id,
                    target_min_reps=int(minimum),
                    target_max_reps=int(maximum),
                    target_sets=int(target_sets),
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
            with st.expander(f"{item.position}. {item.exercise_name} · {item.target_sets} × {item.target_min_reps}–{item.target_max_reps}"):
                left, middle, right = st.columns([1, 1, 5])
                if left.button("↑", key=f"up_{item.id}", disabled=index == 0):
                    if show_error(lambda current=item: move_workout_exercise(current.id, -1)):
                        st.rerun()
                if middle.button("↓", key=f"down_{item.id}", disabled=index == len(configured) - 1):
                    if show_error(lambda current=item: move_workout_exercise(current.id, 1)):
                        st.rerun()
                right.caption(f"{item.primary_muscle_group} · {item.equipment}")
                with st.form(f"targets_{item.id}"):
                    col1, col2, col3 = st.columns(3)
                    new_min = col1.number_input("Minimum reps", 1, 100, item.target_min_reps)
                    new_max = col2.number_input("Maximum reps", 1, 100, item.target_max_reps)
                    new_sets = col3.number_input("Working sets", 1, 20, item.target_sets)
                    new_instructions = st.text_input("Instructions", item.instructions)
                    save_targets = st.form_submit_button("Save targets")
                if save_targets and show_error(
                    lambda current=item: update_workout_exercise(
                        current.id,
                        target_min_reps=int(new_min),
                        target_max_reps=int(new_max),
                        target_sets=int(new_sets),
                        instructions=new_instructions,
                    )
                ):
                    st.success("Targets updated.")
                    st.rerun()
                if st.button("Remove from workout", key=f"remove_{item.id}"):
                    if show_error(lambda current=item: remove_exercise_from_workout(current.id)):
                        st.rerun()


def log_workout_page() -> None:
    st.title("Log workout")
    profile_id = current_profile_id()
    routines = list_routines(active_only=True)
    if not routines:
        st.info("Create and activate a routine before logging a workout.")
        return
    routine_labels = {item.id: item.name for item in routines}
    routine_id = st.selectbox("Routine", list(routine_labels), format_func=routine_labels.get)
    workouts = list_workouts(routine_id, active_only=True)
    if not workouts:
        st.info("This routine has no active workouts.")
        return
    workout_labels = {item.id: item.name for item in workouts}
    workout_id = st.selectbox("Workout", list(workout_labels), format_func=workout_labels.get)
    configured = list_workout_exercises(workout_id)
    if not configured:
        st.warning("This workout has no exercises. Add some in the routine builder.")
        return

    col1, col2 = st.columns(2)
    session_date = col1.date_input("Workout date", date.today())
    completion_time = col2.time_input("Completion time", datetime.now().time().replace(microsecond=0))
    session_notes = st.text_area("Session notes", placeholder="Optional notes about the workout")

    edited_frames: dict[int, pd.DataFrame] = {}
    for item in configured:
        st.subheader(f"{item.position}. {item.exercise_name}")
        set_label = "set" if item.target_sets == 1 else "sets"
        st.caption(
            f"Target: {item.target_sets} {set_label} of {item.target_min_reps}–{item.target_max_reps} reps"
            + (f" · {item.instructions}" if item.instructions else "")
        )
        previous = get_previous_result(item.exercise_id, profile_id=profile_id)
        if previous:
            st.info(
                f"Previous · {format_date(previous['workout_date'])} · {previous['workout_name']}: "
                f"{format_sets(previous['sets'])}"
            )
        else:
            st.caption("No previous result for this exercise.")
        initial = pd.DataFrame(
            [
                {"Done": False, "Weight": 0.0, "Reps": item.target_min_reps, "Intensity method": "", "Notes": ""}
                for _ in range(1)
            ]
        )
        edited_frames[item.id] = st.data_editor(
            initial,
            key=f"log_sets_{workout_id}_{item.id}",
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            column_config={
                "Done": st.column_config.CheckboxColumn(required=True),
                "Weight": st.column_config.NumberColumn(min_value=0.0, step=0.5, required=True),
                "Reps": st.column_config.NumberColumn(min_value=1, step=1, required=True),
                "Intensity method": st.column_config.TextColumn(help="Optional: drop set, rest-pause, tempo, etc."),
            },
        )

    with st.container(key="save_workout_action"):
        save_workout = st.button(
            "Complete and save workout", type="primary", width="stretch"
        )
    if save_workout:
        logs: list[ExerciseLog] = []
        for item in configured:
            entries: list[SetEntry] = []
            frame = edited_frames[item.id]
            for row in frame.to_dict("records"):
                if bool(row.get("Done")):
                    entries.append(
                        SetEntry(
                            weight=float(row["Weight"]),
                            reps=int(row["Reps"]),
                            intensity_method=str(row.get("Intensity method") or ""),
                            notes=str(row.get("Notes") or ""),
                        )
                    )
            logs.append(ExerciseLog(item.id, tuple(entries)))
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
            for item in configured:
                st.session_state.pop(f"log_sets_{workout_id}_{item.id}", None)
            st.success(f"Workout saved. Session #{saved_id[0]} is available in History.")


def history_page() -> None:
    st.title("History")
    profile_id = current_profile_id()
    routines = list_routines()
    exercises = list_exercises()
    routine_options = {0: "All routines", **{item.id: item.name for item in routines}}
    col1, col2 = st.columns(2)
    routine_id = col1.selectbox("Routine", list(routine_options), format_func=routine_options.get)
    workouts = list_workouts(routine_id) if routine_id else []
    workout_options = {0: "All workouts", **{item.id: item.name for item in workouts}}
    workout_id = col2.selectbox("Workout", list(workout_options), format_func=workout_options.get)
    exercise_options = {0: "All exercises", **{item.id: item.name for item in exercises}}
    col3, col4, col5 = st.columns(3)
    exercise_id = col3.selectbox("Exercise", list(exercise_options), format_func=exercise_options.get)
    date_from = col4.date_input("From", value=None)
    date_to = col5.date_input("To", value=None)
    sessions = list_sessions(
        profile_id=profile_id,
        routine_id=routine_id or None,
        workout_id=workout_id or None,
        exercise_id=exercise_id or None,
        date_from=date_from,
        date_to=date_to,
    )
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
        csv_history["date"] = pd.to_datetime(csv_history["date"]).dt.strftime("%d/%m/%y")
    st.subheader("Export and archive")
    excel_bytes = build_history_workbook(sessions, filtered_history)
    export_col1, export_col2, export_col3 = st.columns(3)
    export_col1.download_button(
        "Download Excel",
        data=excel_bytes,
        file_name=f"workout_history_{date.today().isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        disabled=not sessions,
        width="stretch",
    )
    export_col2.download_button(
        "Download CSV",
        data=csv_history.to_csv(index=False).encode("utf-8"),
        file_name=f"workout_history_{date.today().isoformat()}.csv",
        mime="text/csv",
        disabled=filtered_history.empty,
        width="stretch",
    )
    export_col3.download_button(
        "Archive full database",
        data=create_database_backup(),
        file_name=f"workout_tracker_backup_{date.today().isoformat()}.db",
        mime="application/vnd.sqlite3",
        width="stretch",
        help="Complete local backup including exercises, routines, configuration, and history.",
    )
    if not sessions:
        st.info("No sessions match these filters.")
    else:
        session_labels = {
            int(row["id"]): f"{format_date(row['workout_date'])} · {row['routine_name']} / {row['workout_name']} · {row['set_count']} sets"
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
        )
        review = get_session_review(selected_id)
        st.markdown(f"### {review['workout_name']} · {format_date(review['workout_date'])}")
        st.caption(
            f"Routine: {review['routine_name']} · Completed: {format_datetime(review['completed_at'])}"
        )
        if review["notes"]:
            st.write(review["notes"])
        for item in review["exercises"]:
            with st.expander(
                f"{item['position']}. {item['exercise_name']} · {len(item['sets'])} completed sets"
            ):
                st.caption(
                    f"Historic target: {item['target_sets']} × {item['target_min_reps']}–{item['target_max_reps']}"
                )
                if item["instructions"]:
                    st.caption(item["instructions"])
                if item["sets"]:
                    st.caption("Correct a value or delete an incorrectly logged set.")
                    for set_row in item["sets"]:
                        with st.form(f"edit_logged_set_{set_row['id']}"):
                            col1, col2 = st.columns(2)
                            corrected_weight = col1.number_input(
                                "Weight", min_value=0.0, value=float(set_row["weight"]), step=0.5
                            )
                            corrected_reps = col2.number_input(
                                "Reps", min_value=1, value=int(set_row["reps"]), step=1
                            )
                            corrected_method = st.text_input(
                                "Intensity method", value=set_row["intensity_method"]
                            )
                            corrected_notes = st.text_input("Set notes", value=set_row["notes"])
                            save_col, delete_col = st.columns(2)
                            save_set = save_col.form_submit_button("Save set")
                            delete_set = delete_col.form_submit_button("Delete set")
                        if save_set and show_error(
                            lambda row=set_row: update_logged_set(
                                row["id"],
                                weight=float(corrected_weight),
                                reps=int(corrected_reps),
                                intensity_method=corrected_method,
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
                else:
                    st.caption("Skipped in this session.")

    st.divider()
    st.subheader("Exercise progress")
    progress_options = {item.id: item.name for item in exercises}
    if not progress_options:
        st.caption("No exercises available.")
        return
    progress_id = st.selectbox(
        "Choose exercise", list(progress_options), format_func=progress_options.get, key="progress_exercise"
    )
    progress = exercise_progress(progress_id, profile_id=profile_id)
    if progress.empty:
        st.caption("No logged sets for this exercise yet.")
    else:
        latest_evaluation = str(progress.iloc[-1]["evaluation"])
        latest_message = (
            f"Latest result: {latest_evaluation} · "
            f"{progress.iloc[-1]['weight']:g} weight × {int(progress.iloc[-1]['reps'])} reps"
        )
        if latest_evaluation == "Progress":
            st.success(latest_message)
        elif latest_evaluation == "Regression":
            st.error(latest_message)
        else:
            st.info(latest_message)
        st.caption("Blue line: weight · Orange dashed line: reps · Point colour: evaluation")
        st.altair_chart(progress_chart(progress), width="stretch")
        display_progress = progress.rename(
            columns={
                "date": "Date",
                "workout_name": "Workout",
                "weight": "Weight",
                "reps": "Reps",
                "evaluation": "Evaluation",
            }
        )
        display_progress["Date"] = display_progress["Date"].dt.strftime("%d/%m/%y")
        st.dataframe(display_progress, hide_index=True, width="stretch")


PAGES = {
    "Dashboard": dashboard_page,
    "Log workout": log_workout_page,
    "History": history_page,
    "Exercises": exercises_page,
    "Routines": routines_page,
    "Profiles": profiles_page,
}

active_profiles = list_profiles(active_only=True)
if not active_profiles:
    st.error("No active profiles are available. Reactivate or create a profile to continue.")
    profiles_page()
    st.stop()
profile_options = {profile.id: profile.name for profile in active_profiles}
if st.session_state.get("active_profile_id") not in profile_options:
    st.session_state["active_profile_id"] = default_profile_id()
st.selectbox(
    "Training profile",
    list(profile_options),
    format_func=profile_options.get,
    key="active_profile_id",
)
page_name = st.radio(
    "Navigate", list(PAGES), horizontal=True, label_visibility="collapsed"
)
st.caption("V3 profiles · SQLite")

PAGES[page_name]()
