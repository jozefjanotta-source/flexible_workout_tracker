# Developer Guide

This guide explains how Flexible Workout Tracker works internally. It is written for a Python developer who understands functions, classes, imports, context managers, SQL basics, and HTTP-style application concepts, but may be new to Streamlit or layered application design.

For installation, configuration, the complete file inventory, and database schema, see [README.md](README.md).

## Architecture at a glance

The application uses a small layered architecture:

```text
Browser
  │
  ▼
app.py + ui_pages/             navigation layer
  │
  ▼
streamlit_ui.py                presentation and UI-state layer
  │
  ├── exercise_management.py
  ├── profile_management.py
  ├── routine_management.py    domain/service layer
  ├── workout_logging.py
  ├── progress_calculations.py
  └── export_management.py
              │
              ▼
          database.py          persistence boundary
              │
              ▼
       SQLite or Turso cache
```

There is no web API server between Streamlit and the service functions. Streamlit runs Python from top to bottom after each user interaction. Page functions call ordinary Python service functions, which execute parameterized SQL through `database.py`.

The main architectural rule is:

> UI code decides what to display; service code decides what is valid; the database layer decides how connections, transactions, and synchronization work.

Keeping that rule intact makes features easier to test and prevents business rules from becoming tied to Streamlit widgets.

## The layers in detail

### 1. Navigation layer

`app.py` is the executable entrypoint. It:

1. Calls `st.set_page_config()` before rendering anything.
2. Loads `assets/style.css`.
3. creates `st.Page` objects for the files under `ui_pages/`.
4. Groups pages into primary and **Manage** navigation.
5. Processes `navigate_after_rerun`, which lets a page request navigation after state has been cleared.
6. Renders the shared profile header.
7. Runs the selected page.

Each `ui_pages/*.py` file is intentionally tiny. For example, `ui_pages/workout.py` imports and calls `log_workout_page()`. Streamlit needs a file path for native page navigation, but keeping the implementation in `streamlit_ui.py` avoids seven disconnected mini-apps.

### 2. Presentation and state layer

`streamlit_ui.py` contains all page functions and shared UI helpers. Its responsibilities include:

- rendering widgets, cards, tables, charts, dialogs, and messages;
- reading and writing `st.session_state`;
- converting widget values into service-layer dataclasses;
- calling service functions and displaying expected errors;
- coordinating reruns and navigation;
- formatting dates, weights, sets, and progress charts.

It should not contain raw database writes. A UI action such as “create exercise” calls `create_exercise()` rather than running an `INSERT` itself.

Streamlit's execution model matters: clicking a widget normally reruns the entire selected page. Persistent values therefore live in `st.session_state` or in Streamlit widgets with stable keys. Local Python variables are rebuilt on every rerun.

### 3. Domain/service layer

The service modules group behavior by subject:

- `profile_management.py` — profiles and profile invariants.
- `exercise_management.py` — the exercise library.
- `routine_management.py` — routine, workout, and workout-exercise templates.
- `workout_logging.py` — completed-session writes, corrections, deletion, previous results, and review.
- `progress_calculations.py` — read-only analytical queries returned as Pandas DataFrames.
- `export_management.py` — conversion of already-selected data into a formatted workbook.

These modules can be called without Streamlit. That is why most behavior can be tested quickly using temporary databases in `tests/test_workflows.py`.

Domain-specific exceptions such as `ExerciseError`, `ProfileError`, `RoutineError`, and `WorkoutLogError` carry messages suitable for users. `streamlit_ui.show_error()` catches them at the UI boundary.

Small frozen dataclasses such as `Exercise`, `Profile`, `WorkoutExercise`, `SetEntry`, and `ExerciseLog` make data shapes explicit. `frozen=True` prevents accidental mutation after construction.

### 4. Persistence layer

`database.py` is the only module that knows how to choose between ordinary SQLite and Turso. It provides two context managers:

```python
with connection_scope(db_path) as connection:
    rows = connection.execute("SELECT ...", parameters).fetchall()

with transaction(db_path) as connection:
    connection.execute("INSERT ...", parameters)
```

Use `connection_scope()` for reads. It opens the selected backend, pulls remote changes when applicable, and always closes the connection.

Use `transaction()` for writes. It pulls first, commits and pushes on success, rolls back on any exception, and always closes the connection. A process-level re-entrant lock serializes local access and sync operations.

`MappingRow` and `_turso_row_factory()` make Turso results support the same `row["column"]` access pattern as `sqlite3.Row`. Service modules therefore do not need backend-specific branches.

`init_db.py` owns the schema and migrations. Initialization is idempotent, so the UI can call it at startup without recreating existing data.

## How modules communicate

Imports point mostly downward through the layers:

```text
app.py
  └── streamlit_ui.py
        ├── init_db.py ───────────────┐
        ├── *_management.py ──────────┤
        ├── workout_logging.py ───────┤
        ├── progress_calculations.py ─┤
        └── export_management.py      │
                                      ▼
                                  database.py
```

There are two intentional service-to-service relationships:

- `workout_logging.py` uses `default_profile_id()` and `list_workout_exercises()` because saving requires a profile and a current template.
- `init_db.py` uses `database.transaction()` to create and migrate the schema through the same backend abstraction.

Communication uses ordinary values rather than global service objects:

- IDs identify database records.
- Dataclasses represent structured inputs and outputs.
- Lists of dataclasses represent library/template records.
- Dictionaries represent flexible session reviews and query rows.
- Pandas DataFrames represent tabular history, progress, and export data.
- Domain exceptions communicate validation failures upward.

Dependency direction is important. `database.py` must not import UI or service modules, and service modules should not import Streamlit. Reversing these dependencies would create circular imports and make non-UI tests harder.

## Why the code is structured this way

### Templates and history are different concepts

Exercises, routines, workouts, and workout exercises describe what the user plans to do. Completed sessions describe what actually happened. The schema separates these concepts.

When `save_completed_session()` runs, it copies the routine name, workout name, exercise name, order, rep targets, set target, and instructions into session tables. These are snapshots. Renaming a routine tomorrow must not rename a workout completed last month.

This controlled duplication is deliberate. Normalized source references remain available when possible, but historical display does not depend on mutable templates.

### Deactivation protects references

Template records usually have an `active` flag instead of being deleted. Deactivating an exercise or routine removes it from future choices while preserving old sessions and allowing reactivation.

Completed sessions are different: the user can permanently delete them. Database `ON DELETE CASCADE` removes their session exercises and sets without touching routine templates.

### Transactions prevent partial workouts

A workout session spans three tables. If the application inserted the session but failed while inserting a set, the database would contain incomplete history. `save_completed_session()` wraps all inserts in one transaction, so either the complete session is stored or nothing is.

### Services make testing inexpensive

The application avoids putting core rules inside button callbacks. Tests can call `save_completed_session()` or `duplicate_routine()` directly, using a temporary database and no browser. Streamlit smoke tests are reserved for behavior that genuinely depends on widgets, session state, or navigation.

### Bulk reads matter for cloud use

`get_previous_results()` and `latest_exercise_progress()` fetch data for several exercises in one connection/query path. Repeating a connection per exercise is tolerable on local SQLite but creates unnecessary latency and sync work with a cloud database.

## Most important files

Read these files in this order when returning to the project:

1. `README.md` — current capabilities, schema, configuration, and commands.
2. `app.py` — page inventory and navigation behavior.
3. `streamlit_ui.py` — how users interact with each workflow and how session state is managed.
4. `init_db.py` — authoritative schema, migrations, and starter data.
5. `workout_logging.py` — the most important write path and historical snapshot logic.
6. `database.py` — transactions, SQLite/Turso selection, synchronization, and backups.
7. `routine_management.py` — template construction and ordering rules.
8. `progress_calculations.py` — definitions of “best set” and “progress.”
9. `tests/test_workflows.py` — executable examples of intended domain behavior.
10. `tests/test_app_smoke.py` — executable examples of important UI behavior.

If you only have fifteen minutes, focus on `app.py`, `log_workout_page()`, `save_completed_session()`, `SCHEMA`, and the workflow tests.

## Step-by-step application flow

### A. Process startup

1. The developer runs `streamlit run app.py`.
2. Python imports `streamlit_ui.py` while `app.py` creates pages.
3. The cached `initialize_app_database()` calls `initialize_database()` once for the current database identity and schema version.
4. `initialize_database()` opens a transaction, runs `CREATE TABLE IF NOT EXISTS`, seeds starter records, and applies missing migrations.
5. `app.py` loads the navigation and shared header.
6. `render_shared_header()` loads active profiles and stores the selected ID in `st.session_state["active_profile_id"]`.
7. The selected `ui_pages/*.py` adapter calls its page function.

### B. Normal read-only page

Consider Home:

1. `dashboard_page()` asks `current_profile_id()` for the selected profile.
2. It calls functions such as `days_since_previous_workout()` and `latest_exercise_progress()`.
3. Each function builds parameterized SQL and opens `connection_scope()`.
4. For Turso, the connection pulls remote changes before executing the query.
5. Results are converted into Python values or a DataFrame.
6. The page renders metrics, cards, and an Altair chart.
7. A widget interaction causes Streamlit to rerun this flow with updated state.

### C. Creating or editing a template

Consider adding an exercise to a workout:

1. `routines_page()` loads active routines, workouts, exercises, and existing configuration.
2. The user chooses an exercise and rep targets.
3. The page calls `add_exercise_to_workout()` through `show_error()`.
4. The service validates the target range and opens `transaction()`.
5. It finds the next position, reactivates an existing matching row or inserts a new row, and commits.
6. The page calls `st.rerun()` so all displayed configuration comes from the database again.

### D. Logging and saving a workout

1. `log_workout_page()` reads the active profile and lists active routines.
2. The selected routine determines the available workouts.
3. `list_workout_exercises()` loads the ordered template.
4. `get_previous_results()` loads the last result for all configured exercises in one query, scoped to the active profile.
5. `_workout_exercise_card()` renders one expander per exercise. Stable, versioned widget keys keep draft values across reruns.
6. The draft exists only in `st.session_state`; no database row is created yet.
7. When **Complete and save** is clicked, the page checks that every marked-complete exercise has weight and reps.
8. Widget dictionaries are converted into immutable `SetEntry` objects, grouped into `ExerciseLog` objects.
9. `save_completed_session()` checks that at least one set exists, all exercises belong to the chosen workout, every set is valid, and the profile/template is active.
10. Inside one transaction it inserts the session, immutable exercise snapshots, and logged sets.
11. On success, the UI stores the new session ID, removes all draft widget keys, requests navigation to History, and reruns.
12. `app.py` sees `navigate_after_rerun == "History"` and switches pages.
13. History opens the newly saved session and displays a success message.

If the user chooses **Cancel workout**, a second confirmation is shown. Confirming removes only draft keys, navigates Home, and does not call the persistence layer.

### E. Reviewing, editing, and deleting history

1. `history_page()` builds filter controls.
2. It passes the selected profile, routine, workout, exercise, and dates to both `list_sessions()` and `history_dataframe()`.
3. Selecting a session calls `get_session_review()`, which reads snapshot data rather than current template labels.
4. Editing a set calls `update_logged_set()`; deleting one calls `delete_logged_set()` and renumbers remaining sets.
5. Deleting a whole workout requires a dialog confirmation. `delete_completed_session()` checks profile ownership before deleting the parent session; cascades remove child rows.
6. Any prepared download cache is cleared after data changes so exports cannot serve stale history.

### F. Comparing progress

1. `comparison_page()` requires one routine and optionally selected workouts from that routine.
2. `workout_comparison_dataframe()` chooses the heaviest set for each exercise in each session. Higher reps break an equal-weight tie.
3. `_evaluate_result()` compares each result with the preceding result for that exercise.
4. The page displays sessions and exercises side by side with `Baseline`, `Progress`, `No progress`, or `Regression` labels.

### G. Export and backup

1. History filters produce a session list and detailed set DataFrame.
2. Export bytes are generated only after **Prepare downloads** is clicked.
3. CSV comes from the DataFrame; `build_history_workbook()` creates the Excel `Sessions` and `Sets` sheets in memory.
4. `create_database_backup()` creates a consistent complete SQLite copy. With Turso, it first pulls and checkpoints the cache.

## Where to add new features

Use the narrowest layer that owns the behavior.

| Change | Primary location | Usually also update |
| --- | --- | --- |
| New page | `streamlit_ui.py`, a new `ui_pages/*.py`, and `app.py` | CSS and UI smoke tests |
| New widget or page layout | Relevant function in `streamlit_ui.py` | `assets/style.css`, smoke tests |
| Exercise/profile/routine rule | Corresponding `*_management.py` | UI call site and workflow tests |
| Completed-workout field or validation | `workout_logging.py` | schema/migration, UI, history/export, tests |
| New progress metric | `progress_calculations.py` | charts/page copy and tests |
| New export format | A focused export module or `export_management.py` | History download controls and tests |
| New table or column | `SCHEMA` and `_apply_migrations()` in `init_db.py` | affected dataclasses, queries, exports, tests |
| Database backend behavior | `database.py` | both-backend tests and deployment docs |
| Theme or responsive behavior | `assets/style.css` | visual/UI testing |

### Recommended implementation sequence

For a feature that stores new data:

1. Describe the invariant: what must always be true?
2. Change `SCHEMA` for fresh databases.
3. Add an idempotent migration for existing databases.
4. Extend the relevant dataclasses and service functions.
5. Add or update SQL queries that read the field.
6. Add service-level tests using a temporary database.
7. Add the Streamlit controls and display.
8. Update exports and snapshots if the field is historically meaningful.
9. Add a UI smoke test for the critical interaction.
10. Run both the normal and Turso-compatible test commands.
11. Update `README.md` and this guide if architecture or workflows changed.

If a new template field must remain historically accurate, copy it into `session_exercises` or another snapshot table during save. Merely joining to the current template will silently rewrite the meaning of old workouts.

## Common pitfalls

### Forgetting that Streamlit reruns the page

A button click does not continue a long-lived page object; Streamlit executes the script again. Put cross-rerun draft state in widgets or `st.session_state`, use stable unique keys, and call `st.rerun()` after mutations when the page should reload canonical database state.

Do not store important unsaved data only in a local list and expect it to survive the next interaction.

### Reusing stale widget keys

Streamlit may retain old values when widget defaults or meaning change. Workout keys include `DRAFT_WIDGET_VERSION` for this reason. Increment that version when an incompatible draft-widget change should invalidate old session state.

### Writing SQL in the UI

Raw database work in `streamlit_ui.py` bypasses domain validation and makes behavior harder to test. Add a service function and call it from the UI.

### Opening one connection per item

Avoid calling a read function inside a loop when a bulk query is possible. This is especially expensive with Turso because connections may pull remote state. Follow the pattern of `get_previous_results()`.

### Using the wrong context manager

- Read with `connection_scope()`.
- Write with `transaction()`.

Manual `commit()` calls in service functions bypass the consistent push/rollback behavior.

### Assuming SQLite and Turso exceptions are identical

Catch `database.INTEGRITY_ERRORS` for uniqueness/constraint conflicts that should become domain errors. This tuple includes the available backend exception types.

### Mutating history through template joins

History screens should read `routine_name`, `workout_name`, and `exercise_name` snapshots from session tables. Showing current template values makes old sessions appear to change after an edit.

### Deleting template data unnecessarily

Prefer setting `active = 0`. Physical deletion can break references or remove the ability to understand older records. Permanent deletion is intentionally limited to completed sessions/sets through explicit UI confirmations.

### Adding only a migration or only the base schema

Fresh databases use `SCHEMA`; existing databases use `_apply_migrations()`. A schema change must normally update both. Give each migration a unique version and make it safe to run once on any supported old database.

When a schema change affects cached UI initialization, update `APP_SCHEMA_VERSION` so Streamlit does not reuse an old cached initialization result.

### Forgetting profile scope

Exercises and routine templates are shared. Session-derived information is private to a profile within the app. Previous results, history, dashboards, progress, comparisons, edits, deletes, and exports must pass or verify `profile_id`.

### Preparing exports too early

Excel archives and full backups can be expensive. Keep generation behind an explicit request, and clear cached prepared downloads whenever the underlying history changes.

### Testing against the real database

Pass `db_path` into service functions and use `tempfile.TemporaryDirectory()` in tests. Never point automated tests at `data/workout_tracker.db`.

### Relying on Python's bare `python` command

Activate `.venv` first or call `.venv/bin/python` explicitly. On some systems only `python3` is available outside the virtual environment.

## Testing strategy

Run the complete suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Then exercise the Turso-compatible path:

```bash
WORKOUT_DB_BACKEND=turso .venv/bin/python -m unittest discover -s tests -v
```

Add most new behavior to `tests/test_workflows.py`. These tests are fast and should verify database state and domain outputs, not implementation details.

Add a test to `tests/test_app_smoke.py` when the feature depends on:

- whether a page renders;
- a particular widget or option;
- `st.session_state` behavior;
- dialogs, reruns, or page navigation;
- integration between widget values and a service call.

Tests are also good examples of how to call the service layer without Streamlit. Start there when learning an unfamiliar workflow.

## A practical debugging checklist

When a feature behaves incorrectly:

1. Reproduce it with a temporary/local database if possible.
2. Identify the layer: widget state, service validation, SQL/data, or backend sync.
3. Inspect `st.session_state` keys and confirm the page rerun path for UI issues.
4. Call the service function directly with a temporary `db_path` to separate UI from domain behavior.
5. Inspect snapshot tables as well as template tables for history issues.
6. Check whether `profile_id` was passed consistently.
7. Confirm a write used `transaction()` and did not swallow an exception.
8. For Turso-only behavior, compare the same test with local SQLite and look at pull/push boundaries.
9. Add a failing regression test before changing the code.
10. Run the full suite after the focused test passes.

The codebase is intentionally straightforward: functions and SQL are preferred over a large framework or ORM. Preserve that clarity. Add abstraction when it removes genuine duplication or protects an invariant, not merely to introduce another layer.
