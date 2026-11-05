"""Back up the SQLite database into app/data/backups/ (safe while the app is running, WAL mode included).

    python tools/backup_db.py [label] [--db PATH] [--out-dir DIR]

Why not `copy yt_summarizer.sqlite ...`: in WAL mode (NS-28) the newest commits may still sit in the side file
`yt_summarizer.sqlite-wal`, so a plain copy of the .sqlite file alone can miss them (and copying the three files
while the app writes can catch them out of step). SQLite's backup API gives one consistent snapshot, with the WAL
content folded in, and does not block the app for more than a moment.

The backup is a single ordinary .sqlite file (journal_mode back to "delete" inside it); no -wal / -shm files.
Prints the path and the row counts of the main tables, so the result can be checked at a glance.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_DB = os.path.join(ROOT, "app", "data", "db", "yt_summarizer.sqlite")
DEFAULT_OUT = os.path.join(ROOT, "app", "data", "backups")
TABLES = ("videos", "subtitles_formatted", "processing_queue", "app_settings")


def backup(db_path: str = DEFAULT_DB, out_dir: str = DEFAULT_OUT, label: str = "manual") -> str:
    """Write a consistent copy of `db_path` into `out_dir`; returns the new file's path."""
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"database not found: {db_path}")
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(db_path))[0]
    safe_label = "".join(c if c.isalnum() or c in "-_" else "-" for c in label) or "manual"
    target = os.path.join(out_dir, f"{stem}-{safe_label}-{datetime.now():%Y%m%d-%H%M%S}.sqlite")
    if os.path.exists(target):
        raise FileExistsError(target)
    # read-only source: the backup can never change the live file
    source = sqlite3.connect("file:" + db_path.replace("\\", "/") + "?mode=ro", uri=True, timeout=30)
    try:
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
            dest.execute("PRAGMA journal_mode=DELETE")
        finally:
            dest.close()
    finally:
        source.close()
    return target


def counts(db_path: str) -> dict[str, int]:
    conn = sqlite3.connect("file:" + db_path.replace("\\", "/") + "?mode=ro", uri=True)
    try:
        result = {}
        for table in TABLES:
            try:
                result[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                result[table] = -1
        return result
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("label", nargs="?", default="manual", help="short name put into the file name")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--out-dir", default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    path = backup(args.db, args.out_dir, args.label)
    print(path)
    print({"size_bytes": os.path.getsize(path), **counts(path)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
