"""Bench personal assistant — standalone interactive entry point.

Run:  uv run python src/assistant.py
      uv run python src/assistant.py --section calendar
      uv run python src/assistant.py --section email
      uv run python src/assistant.py --section tasks
      uv run python src/assistant.py --section meetings
      uv run python src/assistant.py --section suggest
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.markdown import Markdown

from src.modules.assistant import AssistantModule
from src.utils.config import load_config

console = Console()

SECTIONS = ["calendar", "email", "meetings", "tasks", "all"]


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(console=console, show_path=False, markup=True)],
    )


def main():
    parser = argparse.ArgumentParser(description="Bench personal assistant")
    parser.add_argument(
        "--section", "-s",
        choices=SECTIONS,
        default="all",
        help="Run a specific section only (default: all)",
    )
    args = parser.parse_args()

    setup_logging()
    config = load_config()
    data_dir = str(Path(config["paths"]["dropbox_data"]).expanduser())

    mod = AssistantModule(config=config, data_dir=data_dir)

    if args.section == "all":
        result = mod.run()
    else:
        result = mod.run_section(args.section)

    # Render output
    if not result.items:
        console.print("[yellow]No items to show.[/]")
        return

    for item in result.items:
        if isinstance(item, dict) and item.get("text"):
            console.print(Markdown(item["text"]))
            console.print()
        elif isinstance(item, dict) and item.get("title"):
            console.print(f"  {item['title']}")


if __name__ == "__main__":
    main()
