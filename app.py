"""Streamlit user interface for the flexible workout tracker."""

from __future__ import annotations

from datetime import date, datetime
from typing import Callable

import pandas as pd
import streamlit as st

from exercise_management import (
    ExerciseError,
    create_exercise,
    list_exercises,
    update_exercise,
)
from init_db import initialize_database
from progress_calculations import days_since_previous_workout, exercise_progress
from routine_management import (
    RoutineError,
    add_exercise_to_workout,
    create_routine,
    create_workout,
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
    ExerciseLog,
    SetEntry,
    WorkoutLogError,
    get_previous_result,
    get_session_review,
    list_sessions,
    save_completed_session,
)


st.set_page_config(page_title="Workout Tracker", page_icon="🏋️", layout="wide", initial_sidebar_state="collapsed")
initialize_database()

st.markdown(
    """
    <style>
    .block-container {max-width: 1120px; padding-top: 2rem;}
    [data-testid="stMetric"] {background: rgba(128, 128, 128, 0.10); border: 1px solid rgba(128, 128, 128, 0.22); border-radius: 0.7rem; padding: 0.8rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def show_error(action: Callable[[], object]) -> bool:
    """Run a UI action and show expected domain/database errors cleanly."""
    try:
        action()
        return True
    except (ExerciseError, RoutineError, WorkoutLogError, ValueError) as exc:
        st.error(str(exc))
        return False
    except Exception as exc:  # UI boundary: do not crash the whole app.
        st.error(f"Unexpected error: {exc}")
        return False


def format_sets(sets: list[dict[str, object]]) -> str:
    if not sets:
        return "No completed sets"
    return " · ".join(f"{row['weight']:g} × {row['reps']}" for row in sets)


def dashboard_page() -> None:
    st.title("Workout tracker")
    st.caption("Flexible routines, straightforward logging, and useful history.")
    routines = list_routines(active_only=True)
    exercises = list_exercises(active_only=True)
    sessions = list_sessions()
    days = days_since_previous_workout()
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
    st.dataframe(frame[["Date", "Routine", "Workout", "Exercises", "Sets"]], hide_index=True, width="stretch")


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
                target_sets = col3.number_input("Working sets", 1, 20, 3)
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
        st.caption(
            f"Target: {item.target_sets} sets of {item.target_min_reps}–{item.target_max_reps} reps"
            + (f" · {item.instructions}" if item.instructions else "")
        )
        previous = get_previous_result(item.exercise_id)
        if previous:
            st.info(
                f"Previous · {previous['workout_date']} · {previous['workout_name']}: "
                f"{format_sets(previous['sets'])}"
            )
        else:
            st.caption("No previous result for this exercise.")
        initial = pd.DataFrame(
            [
                {"Done": False, "Weight": 0.0, "Reps": item.target_min_reps, "Intensity method": "", "Notes": ""}
                for _ in range(item.target_sets)
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

    if st.button("Complete and save workout", type="primary", width="stretch"):
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
        routine_id=routine_id or None,
        workout_id=workout_id or None,
        exercise_id=exercise_id or None,
        date_from=date_from,
        date_to=date_to,
    )
    if not sessions:
        st.info("No sessions match these filters.")
    else:
        session_labels = {
            int(row["id"]): f"{row['workout_date']} · {row['routine_name']} / {row['workout_name']} · {row['set_count']} sets"
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
        st.markdown(f"### {review['workout_name']} · {review['workout_date']}")
        st.caption(f"Routine: {review['routine_name']} · Completed: {review['completed_at']}")
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
                    st.dataframe(pd.DataFrame(item["sets"]), hide_index=True, width="stretch")
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
    progress = exercise_progress(progress_id)
    if progress.empty:
        st.caption("No logged sets for this exercise yet.")
    else:
        metric = st.radio(
            "Chart metric",
            ["estimated_1rm", "max_weight", "volume"],
            format_func=lambda value: {
                "estimated_1rm": "Estimated 1RM",
                "max_weight": "Maximum weight",
                "volume": "Training volume",
            }[value],
            horizontal=True,
        )
        st.line_chart(progress.set_index("date")[[metric]])
        st.dataframe(progress, hide_index=True, width="stretch")


PAGES = {
    "Dashboard": dashboard_page,
    "Log workout": log_workout_page,
    "History": history_page,
    "Exercises": exercises_page,
    "Routines": routines_page,
}

page_name = st.radio(
    "Navigate", list(PAGES), horizontal=True, label_visibility="collapsed"
)
st.caption("Local V1 · SQLite")

PAGES[page_name]()
