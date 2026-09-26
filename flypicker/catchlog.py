"""Stores every search and every 'caught / no luck' tap. This becomes the training data for a
future ranker, including the misses that fishing reports never record."""

import json
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get("FLYPICKER_DB", "flypicker.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS searches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  request TEXT NOT NULL,
  engine TEXT NOT NULL,
  conditions TEXT NOT NULL,
  shown TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outcomes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  search_id INTEGER NOT NULL REFERENCES searches(id),
  at TEXT NOT NULL,
  fly_id TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('caught', 'no_luck')),
  fish_count INTEGER,
  notes TEXT
);
"""


def _connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_search(request: dict, result: dict, path: str | None = None) -> int:
    with _connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO searches (at, request, engine, conditions, shown) VALUES (?, ?, ?, ?, ?)",
            (_now(), json.dumps(request), result["engine"], json.dumps(result["conditions"]),
             json.dumps([f["id"] for f in result["flies"]])),
        )
        return cur.lastrowid


def log_outcome(search_id: int, fly_id: str, outcome: str, fish_count: int | None = None,
                notes: str | None = None, path: str | None = None) -> None:
    with _connect(path) as conn:
        if conn.execute("SELECT 1 FROM searches WHERE id = ?", (search_id,)).fetchone() is None:
            raise KeyError(f"No search {search_id}")
        conn.execute(
            "INSERT INTO outcomes (search_id, at, fly_id, outcome, fish_count, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (search_id, _now(), fly_id, outcome, fish_count, notes),
        )
