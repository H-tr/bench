"""Clear all cached/seen data so the next run fetches everything fresh."""

import json
from pathlib import Path

DATA_DIR = Path("~/Dropbox/bench-data").expanduser()

FILES_TO_CLEAR = [
    "seen_papers.json",
    "seen_news.json",
    "seen_opportunities.json",
    "my_stats.json",
]

def main():
    for name in FILES_TO_CLEAR:
        path = DATA_DIR / name
        if path.exists():
            path.unlink()
            print(f"  Deleted {path}")
        else:
            print(f"  Skipped {path} (not found)")

    print("\nCache cleared. Next run will fetch everything fresh.")


if __name__ == "__main__":
    main()
