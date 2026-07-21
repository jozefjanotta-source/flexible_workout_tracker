# Flexible Workout Tracker — Version 4

A flexible workout tracking application built with Python, Streamlit, Pandas, and SQLite-compatible storage. It supports reusable exercises and routines, simple one-set logging, safe draft cancellation, same-routine comparisons, completed-session review, exports, combined weight/reps progress, and separate training profiles.

Version 4 can run locally with SQLite or use Turso Cloud for persistent access from a phone, laptop, and desktop. Exercises and routine templates are shared, while sessions, previous results, dashboards, history, comparisons, progress, and exports are isolated by profile.

## Design highlights

- Routines are data, not code: the app does not depend on a fixed training program.
- Exercises, routines, workouts, and workout-exercise entries can be deactivated without erasing history.
- A completed session stores snapshots of its names, exercise order, targets, and instructions. Later routine edits only affect future sessions.
- SQLite foreign keys, constraints, parameterized queries, and transactions protect data integrity.
- The optional `Sample Full Body` routine is starter content and can be edited or deactivated.
- Heavy Duty mode fixes every exercise at exactly one working set; older multi-set history remains preserved.
- The phone-friendly set card uses a reps dropdown, a 0.25 kg weight stepper, and fixed intensity-method choices instead of a spreadsheet-style input row.
- Weights show one decimal normally and two only for quarter-kilogram values such as 80.25 or 80.75.
- Each working set can optionally record how many reps used the selected intensity method; regular reps remain the progress measure.
- Completed sets can be corrected or deleted without changing their session snapshots.
- Routine duplication copies active templates without copying history.
- History filters apply to both CSV and formatted Excel exports.
- A full SQLite archive preserves exercises, routines, configuration, and history in one file.
- Profiles can be created, renamed, activated, and archived without deleting their history.
- A persistent profile selector helps ensure each workout is logged for the correct person.
- The same database layer supports local SQLite and an optional synced Turso Cloud database.
- An unsaved workout can be cancelled with a two-step confirmation; cancellation writes nothing to history.
- The Compare page keeps selections within one routine and shows workout sessions and exercises side by side.
- Previous results and dashboard progress are loaded in bulk instead of opening one cloud connection per exercise.
- Exports and full backups are prepared only when requested, reducing navigation delays.

## Project modules

- `database.py` — connections and transactions
- `init_db.py` — schema and starter-data initialization
- `profile_management.py` — profile creation, editing, and activation
- `exercise_management.py` — exercise library operations
- `routine_management.py` — routines, workouts, exercise targets, and ordering
- `workout_logging.py` — completed sessions, sets, previous results, and reviews
- `progress_calculations.py` — history data and progress calculations
- `app.py` — Streamlit user interface
- `tests/test_workflows.py` — main service-level workflow tests

## Setup

Python 3.11 or newer is recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python init_db.py
```

Database initialization is idempotent. By default it creates `data/workout_tracker.db`, adds a small exercise library, and adds one optional sample routine. To omit the routine:

```bash
python init_db.py --no-sample-routine
```

To use a different database file, set `WORKOUT_DB_PATH` before running the initializer and app.

## Cloud database

For persistent cloud use, configure these secrets outside Git:

```text
TURSO_DATABASE_URL="libsql://your-database.turso.io"
TURSO_AUTH_TOKEN="your-private-database-token"
```

When these values exist, the app uses a small local cache and explicitly pulls before reads and pushes after successful transactions. Without them, it continues using `data/workout_tracker.db` normally.

On Streamlit Community Cloud, add both values in the app's **Settings → Secrets** screen. Never commit database tokens or `.streamlit/secrets.toml`.

## Launch

```bash
streamlit run app.py
```

Then open the local URL printed by Streamlit, normally `http://localhost:8501`.

## Test

```bash
python -m unittest discover -s tests -v
```

The tests use temporary databases and do not modify the application database. Run them with both supported engines:

```bash
python -m unittest discover -s tests -v
WORKOUT_DB_BACKEND=turso python -m unittest discover -s tests -v
```

## Export and archive

Open **History**, apply the routine, workout, exercise, and date filters, expand **Export and archive**, and select **Prepare downloads**. **Download Excel** creates a workbook with `Sessions` and `Sets` sheets. **Download CSV** exports the detailed set rows.

**Archive full database** downloads a consistent SQLite backup of all local app data. To restore an archive, stop Streamlit, keep a copy of the current database, and replace `data/workout_tracker.db` with the downloaded `.db` file.

## Privacy and scope

Training profiles separate records inside one trusted workspace; they are not separate login accounts. Every invited viewer can currently switch between all profiles, so a hosted deployment should remain private and be shared only with trusted users until per-user authentication is added.

This version intentionally excludes Apple Health, Athlytic, Bevel, nutrition tracking, and advanced recovery calculations.
