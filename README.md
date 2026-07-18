# Flexible Workout Tracker — Version 1

A local workout tracking application built with Python, Streamlit, Pandas, and SQLite. It supports a reusable exercise library, multiple routines and workouts, ordered workout templates, completed-set logging, session review, history filters, and basic exercise progress.

## Design highlights

- Routines are data, not code: the app does not depend on a fixed training program.
- Exercises, routines, workouts, and workout-exercise entries can be deactivated without erasing history.
- A completed session stores snapshots of its names, exercise order, targets, and instructions. Later routine edits only affect future sessions.
- SQLite foreign keys, constraints, parameterized queries, and transactions protect data integrity.
- The optional `Sample Full Body` routine is starter content and can be edited or deactivated.

## Project modules

- `database.py` — connections and transactions
- `init_db.py` — schema and starter-data initialization
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

## Launch

```bash
streamlit run app.py
```

Then open the local URL printed by Streamlit, normally `http://localhost:8501`.

## Test

```bash
python -m unittest discover -s tests -v
```

The tests use temporary databases and do not modify the application database.

## V1 scope

This version intentionally excludes authentication, cloud hosting, Apple Health, Athlytic, Bevel, nutrition tracking, and advanced recovery calculations. See the final implementation handoff for reasonable Version 2 candidates.

