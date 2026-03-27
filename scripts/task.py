"""Bench task manager CLI.

Usage:
    uv run python scripts/task.py                     # list active tasks
    uv run python scripts/task.py add "do something"  # add task
    uv run python scripts/task.py add "rebuttal" --due 2026-04-01 --priority 1
    uv run python scripts/task.py done "rebuttal"     # mark done
    uv run python scripts/task.py remove "rebuttal"   # delete task
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

TASKS_PATH = Path("~/Dropbox/bench-data/tasks.json").expanduser()


def load_tasks() -> list[dict]:
    if not TASKS_PATH.exists():
        return []
    return json.loads(TASKS_PATH.read_text())


def save_tasks(tasks: list[dict]):
    TASKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TASKS_PATH.write_text(json.dumps(tasks, indent=2))


def cmd_list(args):
    tasks = load_tasks()
    active = [t for t in tasks if t.get("status") != "done"]
    done = [t for t in tasks if t.get("status") == "done"]

    if not active:
        print("No active tasks.")
    else:
        print(f"\n📋 Active tasks ({len(active)}):\n")
        for t in sorted(active, key=lambda x: (x.get("priority", 99), x.get("due", "9999"))):
            pri = f"[P{t['priority']}] " if t.get("priority") else ""
            due = f" (due: {t['due']})" if t.get("due") else ""
            tags = f" #{' #'.join(t['tags'])}" if t.get("tags") else ""
            print(f"  ⬜ {pri}{t['title']}{due}{tags}")

    if done:
        print(f"\n✅ Done ({len(done)}):\n")
        for t in done[-5:]:
            print(f"  ✓ {t['title']}")


def cmd_add(args):
    tasks = load_tasks()
    task = {
        "title": args.title,
        "priority": args.priority,
        "status": "todo",
        "due": args.due or "",
        "added": datetime.now().strftime("%Y-%m-%d"),
        "tags": [t.strip() for t in args.tags.split(",")] if args.tags else [],
    }
    tasks.append(task)
    save_tasks(tasks)
    print(f"✅ Added: {task['title']}")


def cmd_done(args):
    tasks = load_tasks()
    found = False
    for t in tasks:
        if args.title.lower() in t["title"].lower() and t.get("status") != "done":
            t["status"] = "done"
            t["done_date"] = datetime.now().strftime("%Y-%m-%d")
            print(f"✅ Done: {t['title']}")
            found = True
            break
    if not found:
        print(f"❌ No active task matching '{args.title}'")
        return
    save_tasks(tasks)


def cmd_remove(args):
    tasks = load_tasks()
    new_tasks = [t for t in tasks if args.title.lower() not in t["title"].lower()]
    if len(new_tasks) == len(tasks):
        print(f"❌ No task matching '{args.title}'")
        return
    save_tasks(new_tasks)
    print(f"🗑️  Removed tasks matching '{args.title}'")


def main():
    parser = argparse.ArgumentParser(description="Bench task manager")
    sub = parser.add_subparsers(dest="command")

    add_p = sub.add_parser("add", help="Add a task")
    add_p.add_argument("title", help="Task description")
    add_p.add_argument("--due", "-d", help="Due date (YYYY-MM-DD)")
    add_p.add_argument("--priority", "-p", type=int, default=3, help="Priority (1=urgent, 2=high, 3=normal)")
    add_p.add_argument("--tags", "-t", help="Comma-separated tags")

    done_p = sub.add_parser("done", help="Mark a task as done")
    done_p.add_argument("title", help="Task title (partial match)")

    rm_p = sub.add_parser("remove", help="Remove a task")
    rm_p.add_argument("title", help="Task title (partial match)")

    args = parser.parse_args()

    if args.command == "add":
        cmd_add(args)
    elif args.command == "done":
        cmd_done(args)
    elif args.command == "remove":
        cmd_remove(args)
    else:
        cmd_list(args)


if __name__ == "__main__":
    main()
