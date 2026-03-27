"""Dropbox data helpers — read/write JSON files in the shared data dir."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: Path, default: Any = None) -> Any:
    """Load a JSON file. Returns default if file doesn't exist."""
    if not path.exists():
        return default if default is not None else {}
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    """Atomically write data as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
    tmp.rename(path)
