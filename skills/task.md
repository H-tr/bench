---
name: task
description: Manage Bench tasks — add, list, complete, or remove tasks from your personal task list
user_invocable: true
---

Manage the user's Bench task list stored at `~/Dropbox/bench-data/tasks.json`.

The file is a JSON array of task objects:
```json
[
  {
    "title": "Finish CoRL rebuttal",
    "priority": 1,
    "status": "todo",
    "due": "2026-04-01",
    "added": "2026-03-27",
    "tags": ["paper"]
  }
]
```

Based on the user's request:

- **Add task**: Parse the natural language request into a task object. Extract title, due date (if mentioned), priority (1=urgent, 2=high, 3=normal), and tags. Write it to the JSON file.
- **List tasks**: Read and display active tasks sorted by priority then due date.
- **Complete task**: Mark a task as `"status": "done"` by matching the title.
- **Remove task**: Delete a task from the list.

Always read the current file first, modify it, then write it back. Use `~/Dropbox/bench-data/tasks.json` as the path.

If no arguments are provided, list all active tasks.

Examples:
- `/task add finish CoRL rebuttal by Friday` → adds with due date
- `/task add buy groceries` → adds with priority 3
- `/task done CoRL rebuttal` → marks as done
- `/task` → lists all active tasks
