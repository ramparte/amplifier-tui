#!/usr/bin/env python3
"""Bug database CLI for amplifier-tui test tracking.

SQLite-backed bug tracker for logging issues found during manual testing.
Designed for CLI use and programmatic access from Amplifier sessions.

Usage:
    python tools/bugdb.py add --test-id T1.1 --severity P1 --title "Description" [--description "Details"]
    python tools/bugdb.py list [--severity P0] [--status open] [--category "Display"]
    python tools/bugdb.py update <id> --status fixed|wontfix|duplicate
    python tools/bugdb.py show <id>
    python tools/bugdb.py stats
    python tools/bugdb.py export [--format md|json|csv]
"""

import argparse
import csv
import io
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "bugs.db"


def get_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Get database connection, creating schema if needed."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS bugs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id TEXT,
            severity TEXT NOT NULL CHECK(severity IN ('P0', 'P1', 'P2', 'P3')),
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'confirmed', 'fixed', 'wontfix', 'duplicate')),
            category TEXT,
            title TEXT NOT NULL,
            description TEXT,
            steps_to_reproduce TEXT,
            expected TEXT,
            actual TEXT,
            commit_ref TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            notes TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_bugs_severity ON bugs(severity);
        CREATE INDEX IF NOT EXISTS idx_bugs_status ON bugs(status);
        CREATE INDEX IF NOT EXISTS idx_bugs_test_id ON bugs(test_id);
        CREATE INDEX IF NOT EXISTS idx_bugs_category ON bugs(category);
    """)
    return conn


def add_bug(
    conn: sqlite3.Connection,
    *,
    test_id: str | None = None,
    severity: str,
    title: str,
    description: str | None = None,
    category: str | None = None,
    steps_to_reproduce: str | None = None,
    expected: str | None = None,
    actual: str | None = None,
    commit_ref: str | None = None,
    notes: str | None = None,
) -> int:
    """Add a bug to the database. Returns the bug ID."""
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        """INSERT INTO bugs (test_id, severity, title, description, category,
           steps_to_reproduce, expected, actual, commit_ref, created_at, updated_at, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            test_id,
            severity,
            title,
            description,
            category,
            steps_to_reproduce,
            expected,
            actual,
            commit_ref,
            now,
            now,
            notes,
        ),
    )
    conn.commit()
    assert cursor.lastrowid is not None, "INSERT should always produce a lastrowid"
    return cursor.lastrowid


def update_bug(conn: sqlite3.Connection, bug_id: int, **kwargs) -> bool:
    """Update bug fields. Returns True if bug existed."""
    row = conn.execute("SELECT id FROM bugs WHERE id = ?", (bug_id,)).fetchone()
    if not row:
        return False
    kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [bug_id]
    conn.execute(f"UPDATE bugs SET {sets} WHERE id = ?", vals)
    conn.commit()
    return True


def list_bugs(
    conn: sqlite3.Connection,
    *,
    severity: str | None = None,
    status: str | None = None,
    category: str | None = None,
    test_id: str | None = None,
) -> list[dict]:
    """List bugs with optional filters."""
    query = "SELECT * FROM bugs WHERE 1=1"
    params: list = []
    if severity:
        query += " AND severity = ?"
        params.append(severity)
    if status:
        query += " AND status = ?"
        params.append(status)
    if category:
        query += " AND category LIKE ?"
        params.append(f"%{category}%")
    if test_id:
        query += " AND test_id LIKE ?"
        params.append(f"%{test_id}%")
    query += " ORDER BY CASE severity WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END, id"
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def get_bug(conn: sqlite3.Connection, bug_id: int) -> dict | None:
    """Get a single bug by ID."""
    row = conn.execute("SELECT * FROM bugs WHERE id = ?", (bug_id,)).fetchone()
    return dict(row) if row else None


def get_stats(conn: sqlite3.Connection) -> dict:
    """Get summary statistics."""
    total = conn.execute("SELECT COUNT(*) FROM bugs").fetchone()[0]
    by_severity = {
        r["severity"]: r["count"]
        for r in conn.execute(
            "SELECT severity, COUNT(*) as count FROM bugs GROUP BY severity"
        )
    }
    by_status = {
        r["status"]: r["count"]
        for r in conn.execute(
            "SELECT status, COUNT(*) as count FROM bugs GROUP BY status"
        )
    }
    by_category = {
        r["category"] or "uncategorized": r["count"]
        for r in conn.execute(
            "SELECT category, COUNT(*) as count FROM bugs GROUP BY category ORDER BY count DESC"
        )
    }
    return {
        "total": total,
        "by_severity": by_severity,
        "by_status": by_status,
        "by_category": by_category,
    }


def format_bug_row(bug: dict) -> str:
    """Format a bug as a compact one-line summary."""
    test = bug.get("test_id") or "-"
    return f"#{bug['id']:>3}  [{bug['severity']}] [{bug['status']:>9}]  {test:<6}  {bug['title']}"


def format_bug_detail(bug: dict) -> str:
    """Format a bug with full details."""
    lines = [
        f"Bug #{bug['id']}",
        f"  Title:       {bug['title']}",
        f"  Severity:    {bug['severity']}",
        f"  Status:      {bug['status']}",
        f"  Test ID:     {bug.get('test_id') or '-'}",
        f"  Category:    {bug.get('category') or '-'}",
        f"  Commit:      {bug.get('commit_ref') or '-'}",
        f"  Created:     {bug['created_at']}",
        f"  Updated:     {bug['updated_at']}",
    ]
    if bug.get("description"):
        lines.append(f"  Description: {bug['description']}")
    if bug.get("steps_to_reproduce"):
        lines.append(f"  Steps:       {bug['steps_to_reproduce']}")
    if bug.get("expected"):
        lines.append(f"  Expected:    {bug['expected']}")
    if bug.get("actual"):
        lines.append(f"  Actual:      {bug['actual']}")
    if bug.get("notes"):
        lines.append(f"  Notes:       {bug['notes']}")
    return "\n".join(lines)


def export_markdown(bugs: list[dict]) -> str:
    """Export bugs as a markdown table."""
    lines = [
        "# Bug Report",
        "",
        f"Total: {len(bugs)} bugs",
        "",
        "| ID | Sev | Status | Test | Title | Category |",
        "|----|-----|--------|------|-------|----------|",
    ]
    for b in bugs:
        lines.append(
            f"| #{b['id']} | {b['severity']} | {b['status']} | {b.get('test_id') or '-'} "
            f"| {b['title']} | {b.get('category') or '-'} |"
        )
    return "\n".join(lines)


def export_csv(bugs: list[dict]) -> str:
    """Export bugs as CSV."""
    buf = io.StringIO()
    if not bugs:
        return ""
    writer = csv.DictWriter(buf, fieldnames=bugs[0].keys())
    writer.writeheader()
    writer.writerows(bugs)
    return buf.getvalue()


def main():
    parser = argparse.ArgumentParser(
        description="Bug database for amplifier-tui testing"
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Database path (default: bugs.db in project root)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add", help="Add a new bug")
    p_add.add_argument("--test-id", "-t", help="Test plan ID (e.g. T1.1)")
    p_add.add_argument(
        "--severity", "-s", required=True, choices=["P0", "P1", "P2", "P3"]
    )
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--description", "-d")
    p_add.add_argument("--category", "-c")
    p_add.add_argument("--steps", help="Steps to reproduce")
    p_add.add_argument("--expected")
    p_add.add_argument("--actual")
    p_add.add_argument("--commit")
    p_add.add_argument("--notes")

    # list
    p_list = sub.add_parser("list", help="List bugs")
    p_list.add_argument("--severity", choices=["P0", "P1", "P2", "P3"])
    p_list.add_argument(
        "--status", choices=["open", "confirmed", "fixed", "wontfix", "duplicate"]
    )
    p_list.add_argument("--category")
    p_list.add_argument("--test-id")

    # show
    p_show = sub.add_parser("show", help="Show bug details")
    p_show.add_argument("id", type=int)

    # update
    p_update = sub.add_parser("update", help="Update a bug")
    p_update.add_argument("id", type=int)
    p_update.add_argument(
        "--status", choices=["open", "confirmed", "fixed", "wontfix", "duplicate"]
    )
    p_update.add_argument("--severity", choices=["P0", "P1", "P2", "P3"])
    p_update.add_argument("--notes")
    p_update.add_argument("--title")

    # stats
    sub.add_parser("stats", help="Show summary statistics")

    # export
    p_export = sub.add_parser("export", help="Export bugs")
    p_export.add_argument("--format", choices=["md", "json", "csv"], default="md")
    p_export.add_argument(
        "--status", choices=["open", "confirmed", "fixed", "wontfix", "duplicate"]
    )

    args = parser.parse_args()
    conn = get_db(args.db)

    try:
        if args.command == "add":
            bug_id = add_bug(
                conn,
                test_id=args.test_id,
                severity=args.severity,
                title=args.title,
                description=args.description,
                category=args.category,
                steps_to_reproduce=args.steps,
                expected=args.expected,
                actual=args.actual,
                commit_ref=args.commit,
                notes=args.notes,
            )
            print(f"Bug #{bug_id} created [{args.severity}]: {args.title}")

        elif args.command == "list":
            bugs = list_bugs(
                conn,
                severity=args.severity,
                status=args.status,
                category=args.category,
                test_id=args.test_id,
            )
            if not bugs:
                print("No bugs found.")
            else:
                print(f"{len(bugs)} bug(s):\n")
                for b in bugs:
                    print(format_bug_row(b))

        elif args.command == "show":
            bug = get_bug(conn, args.id)
            if not bug:
                print(f"Bug #{args.id} not found.")
                sys.exit(1)
            print(format_bug_detail(bug))

        elif args.command == "update":
            updates = {}
            if args.status:
                updates["status"] = args.status
            if args.severity:
                updates["severity"] = args.severity
            if args.notes:
                updates["notes"] = args.notes
            if args.title:
                updates["title"] = args.title
            if not updates:
                print(
                    "Nothing to update. Specify --status, --severity, --notes, or --title."
                )
                sys.exit(1)
            if update_bug(conn, args.id, **updates):
                print(f"Bug #{args.id} updated: {updates}")
            else:
                print(f"Bug #{args.id} not found.")
                sys.exit(1)

        elif args.command == "stats":
            stats = get_stats(conn)
            print(f"Total bugs: {stats['total']}\n")
            print("By severity:")
            for sev in ["P0", "P1", "P2", "P3"]:
                count = stats["by_severity"].get(sev, 0)
                print(f"  {sev}: {count}")
            print("\nBy status:")
            for st, count in stats["by_status"].items():
                print(f"  {st}: {count}")
            if stats["by_category"]:
                print("\nBy category:")
                for cat, count in stats["by_category"].items():
                    print(f"  {cat}: {count}")

        elif args.command == "export":
            bugs = list_bugs(conn, status=args.status)
            if args.format == "md":
                print(export_markdown(bugs))
            elif args.format == "json":
                print(json.dumps(bugs, indent=2))
            elif args.format == "csv":
                print(export_csv(bugs))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
