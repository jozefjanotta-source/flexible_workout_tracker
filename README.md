# Flexible Workout Tracker — Version 4

A responsive, multi-profile workout tracker built with Python and Streamlit. It stores reusable exercise and routine templates separately from completed workout history, supports a Heavy Duty–style single working set, and can run against either a local SQLite database or a synced Turso database.

This README describes the current repository state and is intended as a six-month re-entry guide.

## What the application does

- Maintains a shared exercise library and reusable routines/workouts.
- Logs one working set per configured exercise with weight, reps, an optional intensity method, intensity reps, and notes.
- Shows the previous result while logging and evaluates progress from the heaviest set in each session.
- Preserves historical names, order, targets, and instructions as snapshots, so later template edits do not rewrite history.
- Separates workout sessions, dashboards, comparisons, progress, history, and exports by training profile; routines and exercises remain shared.
- Lets users review, correct, or delete completed sets and permanently delete a completed session with confirmation.
- Filters history and exports the filtered result as CSV or a formatted two-sheet Excel workbook.
- Creates a complete SQLite archive on demand.
- Uses responsive, touch-friendly Streamlit pages with top navigation and a dark theme.

Profiles are data partitions, not authenticated accounts. Anyone who can open the deployed app can currently switch profiles, so deployments should be private and limited to trusted users.

## Folder structure

```text
flexible_workout_tracker/
├── app.py                         # Streamlit entrypoint and navigation
├── streamlit_ui.py                # Shared UI and all page implementations
├── database.py                    # SQLite/Turso connection and transaction layer
├── init_db.py                     # Schema, migrations, and starter data
├── exercise_management.py         # Exercise-library service layer
├── profile_management.py          # Training-profile service layer
├── routine_management.py          # Routine/workout template service layer
├── workout_logging.py             # Completed-session persistence and review
├── progress_calculations.py       # History, comparison, and progress queries
├── export_management.py           # Formatted Excel export generation
├── requirements.txt               # Runtime/test Python dependencies
├── assets/
│   └── style.css                  # Responsive layout and visual styling
├── ui_pages/
│   ├── home.py                    # Home/dashboard page adapter
│   ├── workout.py                 # Workout logger page adapter
│   ├── compare.py                 # Same-routine comparison page adapter
│   ├── history.py                 # History/review/export page adapter
│   ├── routines.py                # Routine editor page adapter
│   ├── exercises.py               # Exercise editor page adapter
│   └── profiles.py                # Profile manager page adapter
├── tests/
│   ├── test_workflows.py          # Service, schema, export, and data-isolation tests
│   └── test_app_smoke.py          # Streamlit rendering and key UI-flow tests
├── data/
│   ├── workout_tracker.db         # Default local database (runtime data)
│   └── backups/                   # Manually retained database snapshots
├── .streamlit/
│   └── config.toml                # Streamlit theme configuration
└── .devcontainer/
    └── devcontainer.json          # Development-container configuration
```

The files in `ui_pages/` intentionally contain only an import and one page-function call. Streamlit needs separate page paths for native navigation, while the actual implementation stays centralized in `streamlit_ui.py`.

## Purpose of every Python file

| File | Responsibility |
| --- | --- |
| `app.py` | Configures Streamlit, loads CSS, declares top-level pages, handles post-rerun navigation, renders the shared header, and runs the selected page. |
| `database.py` | Selects local SQLite or Turso, supplies row-compatible results, serializes access with a process lock, pulls/pushes Turso state, wraps reads and transactions, and creates consistent database backups. |
| `init_db.py` | Defines the complete SQL schema and indexes, creates/updates a database idempotently, seeds exercises and an optional sample routine, and applies recorded migrations. Also provides the initialization CLI. |
| `exercise_management.py` | Validates and performs CRUD-style operations for exercises. Deactivation is preferred to deletion so historical references remain valid. |
| `profile_management.py` | Creates, edits, lists, activates, and archives profiles; prevents archiving the last active profile and provides a stable default profile for service calls. |
| `routine_management.py` | Creates, duplicates, edits, lists, and deactivates routines and workouts; adds, edits, reorders, and removes workout exercises; normalizes exercise positions. |
| `workout_logging.py` | Validates and saves completed sessions atomically, including immutable snapshots and logged sets; retrieves previous results and session reviews; edits/deletes logged sets; deletes complete sessions. |
| `progress_calculations.py` | Runs read-only Pandas/SQL queries for days since training, exercise progress, latest dashboard status, same-routine comparisons, and filterable detailed history. |
| `export_management.py` | Converts filtered session/history data into an in-memory `.xlsx` file with `Sessions` and `Sets` sheets, tables, filters, date formats, and sensible widths. |
| `streamlit_ui.py` | Initializes the database for UI use, manages the selected profile and draft state, formats values, builds charts, and implements Home, Profiles, Exercises, Routines, Log Workout, History, and Compare pages. |
| `ui_pages/home.py` | Calls `dashboard_page()`. |
| `ui_pages/workout.py` | Calls `log_workout_page()`. |
| `ui_pages/compare.py` | Calls `comparison_page()`. |
| `ui_pages/history.py` | Calls `history_page()`. |
| `ui_pages/routines.py` | Calls `routines_page()`. |
| `ui_pages/exercises.py` | Calls `exercises_page()`. |
| `ui_pages/profiles.py` | Calls `profiles_page()`. |
| `tests/test_workflows.py` | Exercises service workflows, snapshots, profile isolation, constraints, comparisons, history, exports, backups, set/session deletion, and both supported database engines. |
| `tests/test_app_smoke.py` | Uses Streamlit's testing API to render every page and verify cancellation, single-set controls, intensity reps, save/navigation, formatting, previous-result display, and delete confirmation. |

## Data flow

### Application startup and reads

```text
app.py
  → selected ui_pages/*.py adapter
  → streamlit_ui.py page function
  → management/progress/logging service function
  → database.connection_scope()
  → optional Turso pull → SQL query → mapped rows/Pandas DataFrame
  → Streamlit widgets, cards, tables, and charts
```

`initialize_app_database()` runs before page work and calls the idempotent initializer, so missing tables, starter records, and migrations are handled automatically.

### Completed workout write

```text
profile + routine/workout selection
  → Streamlit session-state draft (nothing persisted yet)
  → ExerciseLog(SetEntry(...)) objects
  → workout_logging.save_completed_session()
  → one database.transaction()
      1. validate the active profile/template and every set
      2. insert workout_sessions
      3. copy template values into session_exercises snapshots
      4. insert logged_sets
      5. commit; push when Turso sync is active
  → clear draft → open the completed session in History
```

Cancelling a draft only clears Streamlit session state and writes nothing. A transaction exception rolls back the entire save, preventing partial sessions.

### History, progress, and exports

`workout_sessions` joins to `session_exercises` and then `logged_sets`. History filters are translated into parameterized SQL. Progress and comparisons select the heaviest set per exercise/session (reps break equal-weight ties), then label each result `Baseline`, `Progress`, `No progress`, or `Regression` relative to the preceding result. The same filtered data feeds the CSV and Excel downloads. Full archive generation bypasses those filters and copies the whole SQLite database consistently.

## Database schema

SQLite is the canonical on-disk format. Turso uses a local SQLite-compatible cache synchronized with the configured remote database. Foreign keys are enabled for every connection, writes use transactions, and WAL mode is requested.

| Table | Key columns and purpose |
| --- | --- |
| `schema_migrations` | `version` PK, `applied_at`. Records idempotent data/schema migrations. |
| `profiles` | `id` PK; case-insensitive unique `name`; `notes`, `active`, timestamps. Owns session history. |
| `exercises` | `id` PK; case-insensitive unique `name`; muscle group, equipment, notes, active flag, timestamps. Shared exercise library. |
| `routines` | `id` PK; case-insensitive unique `name`; description, active flag, timestamps. Shared plan template. |
| `workouts` | `id` PK; `routine_id` FK; name, description, position, active flag, timestamps; unique `(routine_id, name)`. A day/workout inside a routine. |
| `workout_exercises` | `id` PK; `workout_id` and `exercise_id` FKs; position, rep range, target sets, instructions, active flag, timestamps; unique `(workout_id, exercise_id)`. Current template configuration. Heavy Duty migration/UI fixes `target_sets` to 1, while the column preserves older data compatibility. |
| `workout_sessions` | `id` PK; `profile_id` FK; nullable routine/workout FKs; snapshot names, workout date, completion time, notes, created time. One completed workout. |
| `session_exercises` | `id` PK; `session_id` FK with cascade delete; nullable source exercise/config FKs; snapshot name, position, targets, and instructions. Preserves what the user performed at that time. |
| `logged_sets` | `id` PK; `session_exercise_id` FK with cascade delete; set number, weight, reps, intensity method, intensity reps, notes; unique `(session_exercise_id, set_number)`. |

Relationship summary:

```text
profiles 1 ── * workout_sessions * ── 0..1 routines
                                  * ── 0..1 workouts
routines 1 ── * workouts 1 ── * workout_exercises * ── 1 exercises
workout_sessions 1 ── * session_exercises 1 ── * logged_sets
session_exercises * ── 0..1 exercises / workout_exercises (source references)
```

Deleting a completed session cascades through its session snapshots and sets. Template records are normally archived/deactivated, not deleted. The snapshot columns deliberately duplicate names and targets to keep old sessions readable after template changes.

## Features added in the current version

- Multiple training profiles with profile-scoped history, previous results, dashboards, comparisons, progress, and exports.
- Optional synced Turso Cloud storage with explicit pull-before-read and push-after-commit behavior; local SQLite remains the default.
- Fixed one-working-set Heavy Duty workflow while retaining older multi-set history.
- Phone-friendly logging cards with nullable controls, a 0.25 kg weight step, reps choices from 1–100, and fixed intensity methods.
- Optional intensity-rep count (1–20) for a selected intensity method; ordinary reps remain the progress metric.
- Two-step cancellation of an unsaved workout and two-step permanent deletion of a completed workout.
- Editing and deleting individual completed sets without mutating session snapshots.
- Routine duplication that copies active structure but never history.
- Same-routine workout/session comparison with progress labels.
- Filtered CSV and formatted Excel history exports plus a complete SQLite archive.
- Native top navigation, compact expanders, responsive dark styling, profile selector, progress badges, and bulk-loading of previous/progress results.
- Lazy export/backup generation: download data is prepared only when requested.

## Functions added or modified

This is the current public/important function map; private helpers are included where they encode behavior worth remembering.

- `database.py`: `get_db_path`, `get_connection`, `connection_scope`, `transaction`, and `create_database_backup`; Turso helpers `_uses_turso`, `_get_turso_connection`, `_pull_remote`, `_push_remote`, and `_turso_row_factory`; `MappingRow` keeps Turso rows compatible with SQLite-style keyed access.
- `init_db.py`: `initialize_database`, `_seed_sample_routine`, `_apply_migrations`, `_migration_applied`, and CLI `main`. Current migrations enforce one-set defaults, add `intensity_reps`, and attach legacy sessions to a default profile.
- `profile_management.py`: `create_profile`, `update_profile`, `list_profiles`, and `default_profile_id`.
- `exercise_management.py`: `create_exercise`, `update_exercise`, `set_exercise_active`, `list_exercises`, and `get_exercise`.
- `routine_management.py`: `create_routine`, `duplicate_routine`, `update_routine`, `list_routines`, `create_workout`, `update_workout`, `list_workouts`, `add_exercise_to_workout`, `update_workout_exercise`, `remove_exercise_from_workout`, `move_workout_exercise`, and `list_workout_exercises`; `_validate_targets` and `_normalize_positions` protect configuration consistency.
- `workout_logging.py`: `save_completed_session`, `update_logged_set`, `delete_logged_set`, `delete_completed_session`, `get_previous_result`, bulk `get_previous_results`, `list_sessions`, and `get_session_review`; `_validate_set` enforces set rules. `SetEntry` and `ExerciseLog` are the write DTOs.
- `progress_calculations.py`: `days_since_previous_workout`, `exercise_progress`, bulk `latest_exercise_progress`, `workout_comparison_dataframe`, and `history_dataframe`; `_evaluate_result` supplies the four progress labels.
- `export_management.py`: `build_history_workbook` plus `_excel_value`, `_as_date`, `_as_datetime`, and `_write_sheet` for Excel-safe values and formatting.
- `streamlit_ui.py`: `initialize_app_database`, `show_error`, `format_weight`, `format_sets`, `current_profile_id`, `format_date`, `format_datetime`, `progress_chart`, all seven page functions, `_workout_exercise_card`, `_delete_completed_workout_dialog`, and `render_shared_header`.

## Configuration

Python 3.11 or newer is recommended.

| Setting | Required | Meaning |
| --- | --- | --- |
| `WORKOUT_DB_PATH` | No | Overrides the default local path `data/workout_tracker.db`. Useful for tests or separate local datasets. |
| `WORKOUT_DB_BACKEND=turso` | No | Exercises the local Turso-compatible engine without requiring a remote URL; primarily useful for testing. |
| `TURSO_DATABASE_URL` | No | Enables remote Turso sync, for example `libsql://…`. |
| `TURSO_AUTH_TOKEN` | With remote URL | Private token for the configured Turso database. |
| `TURSO_LOCAL_DB_PATH` | No | Overrides the Turso cache path; default is `/tmp/flexible_workout_tracker_cloud.db`. |
| `SSL_CERT_FILE` | No | Explicit CA bundle override. If absent, `database.py` supplies Certifi's bundle for the Turso client. |

For Streamlit Community Cloud, put `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` in **Settings → Secrets**. Do not commit tokens or `.streamlit/secrets.toml`.

### Dependencies

`requirements.txt` pins compatible ranges:

- `streamlit` — application UI, navigation, charts, and UI tests.
- `pandas` — query results, history filters, CSV generation, and progress transformations.
- `altair` — progress/comparison charts.
- `openpyxl` — formatted Excel workbook generation and export tests.
- `pyturso` — local/remote Turso-compatible connections and sync.
- `certifi` — maintained TLS certificate bundle for cloud connections.

SQLite and `unittest` come from Python's standard library.

## Install and initialize

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python init_db.py
```

Initialization is safe to repeat. It creates the configured database, seeds nine exercises, and adds the editable `Sample Full Body` routine. To seed only the exercise library:

```bash
python init_db.py --no-sample-routine
```

To initialize a specific database without changing the environment:

```bash
python init_db.py --db /absolute/path/to/workouts.db
```

## Run the application

```bash
source .venv/bin/activate
streamlit run app.py
```

Open the URL Streamlit prints, normally `http://localhost:8501`. On first use, confirm the selected profile, then create/edit exercises and routines under **Manage** or start the sample workout.

## Test the application

```bash
python -m unittest discover -s tests -v
```

The suite uses temporary databases and does not change `data/workout_tracker.db`. To also exercise the Turso-compatible backend locally:

```bash
WORKOUT_DB_BACKEND=turso python -m unittest discover -s tests -v
```

## Export, backup, and restore

On **History**, choose routine/workout/exercise/date filters, open **Export and archive**, and click **Prepare downloads**. CSV contains detailed set rows; Excel contains `Sessions` and `Sets` sheets. Filters apply to both history exports.

**Archive full database** downloads all templates, profiles, migrations, and history as one SQLite file. To restore a local archive:

1. Stop Streamlit.
2. Copy the current `data/workout_tracker.db` somewhere safe.
3. Replace it with the downloaded `.db` file.
4. Restart the app; initialization will apply any newer migrations.

For Turso deployments, treat the remote database as authoritative and test restore/sync procedures in a disposable environment before replacing production data.

## Future improvement ideas

- Add authentication and bind profiles to accounts so hosted users cannot inspect or switch to other profiles.
- Add an explicit Turso conflict/offline policy, sync status, retry feedback, and a tested remote restore workflow.
- Split `streamlit_ui.py` into page-specific view modules as the UI grows, leaving shared widgets/state in a smaller common module.
- Add browser-level end-to-end tests for responsive layouts, exports, editing, deletion, and profile switching.
- Add a migration test that upgrades representative databases from every historical schema version.
- Make progress evaluation configurable (estimated 1RM, volume, rep-range rules, bodyweight movements) rather than relying only on weight/reps of the heaviest set.
- Add routine versioning or a deliberate “apply template change to future sessions” audit trail.
- Add import/restore validation and scheduled encrypted backups.
- Add accessibility checks, keyboard navigation, and more explicit empty/loading/error states.
- Add optional recovery/readiness integrations only after privacy, authentication, and data ownership are clearly defined.

The current scope intentionally excludes nutrition tracking, Apple Health, Athlytic, Bevel, and advanced recovery calculations.
