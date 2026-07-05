"""Migrate existing SQLite data to ChromaDB.

Reads from old SQLite databases (knowledge.db, tasks.db, todos.db, corrections.db)
and writes through the new ChromaDB-backed store classes.

Run: python migrate_to_chroma.py

Non-destructive: old DB files are left in place.
"""

import json
import logging
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

WORKSPACE = Path("/home/scout/projects/sandbox/workspace")


def maybe_migrate_knowledge():
    src = WORKSPACE / ".context" / "knowledge" / "knowledge.db"
    if not src.exists():
        logger.info("knowledge.db not found, skipping")
        return 0

    from windowed_context_db import WindowedContextDB

    dst = WindowedContextDB(str(WORKSPACE / ".context" / "knowledge"))
    if dst.count() > 0:
        logger.info("knowledge store already has %d chunks, skipping migration", dst.count())
        return 0

    conn = sqlite3.connect(str(src))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM chunks").fetchall()
    except sqlite3.OperationalError:
        logger.warning("knowledge.db has no 'chunks' table, skipping")
        return 0

    count = 0
    for row in rows:
        tags_raw = row["tags"]
        tags = json.loads(tags_raw) if isinstance(tags_raw, str) and tags_raw else []
        dst.add(row["content"], source=row["source"], tags=tags)
        count += 1

    conn.close()
    logger.info("Migrated %d knowledge chunks from %s", count, src)
    return count


def maybe_migrate_tasks():
    src = WORKSPACE / ".tasks" / "tasks.db"
    if not src.exists():
        logger.info("tasks.db not found, skipping")
        return 0

    from task_store import TaskStore

    dst = TaskStore(str(WORKSPACE / ".tasks"))
    if dst.count() > 0:
        logger.info("task store already has %d tasks, skipping migration", dst.count())
        return 0

    conn = sqlite3.connect(str(src))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM tasks").fetchall()
    except sqlite3.OperationalError:
        logger.warning("tasks.db has no 'tasks' table, skipping")
        return 0

    from task_store import TaskContext

    count = 0
    for row in rows:
        task = TaskContext(
            task_id=row["task_id"],
            task_description=row["task_description"],
            session_id=row["session_id"],
            files_involved=json.loads(row["files_involved"]) if row["files_involved"] else [],
            decisions=json.loads(row["decisions"]) if row["decisions"] else [],
            blockers=json.loads(row["blockers"]) if row["blockers"] else [],
            code_created=json.loads(row["code_created"]) if row["code_created"] else [],
            status=row["status"],
            created_at=row["created_at"],
            last_updated=row["last_updated"],
        )
        dst.save_task(task)
        count += 1

    conn.close()
    logger.info("Migrated %d tasks from %s", count, src)
    return count


def maybe_migrate_todos():
    src = WORKSPACE / ".todos" / "todos.db"
    if not src.exists():
        logger.info("todos.db not found, skipping")
        return 0

    from todo_list import TodoList

    dst = TodoList(str(WORKSPACE / ".todos"))
    existing = sum(dst.count_by_status().values())
    if existing > 0:
        logger.info("todo store already has %d todos, skipping migration", existing)
        return 0

    conn = sqlite3.connect(str(src))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM todos").fetchall()
    except sqlite3.OperationalError:
        logger.warning("todos.db has no 'todos' table, skipping")
        return 0

    from todo_list import TodoItem

    count = 0
    for row in rows:
        todo = TodoItem(
            id=row["id"],
            description=row["description"],
            status=row["status"],
            parent_id=row["parent_id"],
            session_id=row["session_id"],
            discoveries=json.loads(row["discoveries"]) if row["discoveries"] else [],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            iteration_count=row["iteration_count"],
        )
        # Chroma-backed create_todo generates a new id/hash, so we insert directly
        # into the underlying store to preserve the original id
        dst._store.add_one(
            "todos", todo.id,
            metadata=dst._todo_to_metadata(todo),
            document=todo.description,
        )
        count += 1

    conn.close()
    logger.info("Migrated %d todos from %s", count, src)
    return count


def maybe_migrate_corrections():
    src = WORKSPACE / ".corrections" / "corrections.db"
    if not src.exists():
        logger.info("corrections.db not found, skipping")
        return 0

    from correction_store import CorrectionStore

    dst = CorrectionStore(str(WORKSPACE / ".corrections"))
    if dst.count() > 0:
        logger.info("correction store already has %d corrections, skipping migration", dst.count())
        return 0

    conn = sqlite3.connect(str(src))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM corrections").fetchall()
    except sqlite3.OperationalError:
        logger.warning("corrections.db has no 'corrections' table, skipping")
        return 0

    import uuid

    count = 0
    for row in rows:
        dst._store.add_one(
            "corrections", str(uuid.uuid4()),
            metadata={
                "topic": row["topic"],
                "incorrect_output": row["incorrect_output"],
                "correct_output": row["correct_output"],
                "context": row["context"] or "",
                "created_at": row["created_at"],
                "applied_count": row["applied_count"],
            },
            document=row["topic"],
        )
        count += 1

    conn.close()
    logger.info("Migrated %d corrections from %s", count, src)
    return count


def main():
    logger.info("Starting migration from SQLite → ChromaDB")
    total = 0
    total += maybe_migrate_knowledge()
    total += maybe_migrate_tasks()
    total += maybe_migrate_todos()
    total += maybe_migrate_corrections()
    logger.info("Migration complete. %d total items migrated.", total)
    logger.info("Old SQLite databases left in place. Verify and delete manually.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
