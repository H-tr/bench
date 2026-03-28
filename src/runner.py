"""Bench runner — master orchestrator."""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from src.modules import ALL_MODULES
from src.modules.base import ModuleResult
from src.modules.digest import DigestModule
from src.utils.config import load_config

console = Console()

# Execution order: digest always runs last, after collecting results
MODULE_ORDER = ["assistant", "papers", "intelligence", "news"]


def setup_logging(data_dir: Path) -> None:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"bench_{datetime.now():%Y%m%d_%H%M%S}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            RichHandler(console=console, show_path=False, markup=True),
            logging.FileHandler(log_file),
        ],
    )


def run_pipeline(config: dict) -> None:
    data_dir = Path(config["paths"]["dropbox_data"]).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(data_dir)

    log = logging.getLogger("bench")
    log.info("Bench starting — %s", datetime.now().strftime("%Y-%m-%d %A %H:%M"))

    # Refresh knowledge profile (used for personalized paper analysis)
    from src.utils.paper_analysis import build_knowledge_profile, KNOWLEDGE_PROFILE_PATH
    if not KNOWLEDGE_PROFILE_PATH.exists():
        log.info("Building knowledge profile from Notion (first run)...")
        build_knowledge_profile(config)
    else:
        # Refresh weekly
        age_days = (datetime.now().timestamp() - KNOWLEDGE_PROFILE_PATH.stat().st_mtime) / 86400
        if age_days > 7:
            log.info("Refreshing knowledge profile (%.0f days old)...", age_days)
            build_knowledge_profile(config)

    enabled = config.get("modules", {})
    results: list[ModuleResult] = []

    for name in MODULE_ORDER:
        if not enabled.get(name, False):
            log.info("Module [bold yellow]%s[/] disabled, skipping", name)
            continue

        module_cls = ALL_MODULES.get(name)
        if module_cls is None:
            log.warning("Unknown module: %s", name)
            continue

        log.info("Running [bold cyan]%s[/]…", name)
        t0 = time.time()
        try:
            module = module_cls(config=config, data_dir=str(data_dir))
            result = module.run()
        except Exception as e:
            log.exception("Module %s crashed", name)
            result = ModuleResult(
                module_name=name, section_title=name.upper(), errors=[str(e)]
            )
        elapsed = time.time() - t0
        log.info("  %s finished in %.1fs (ok=%s)", name, elapsed, result.ok)
        results.append(result)

    # Digest runs last, receiving all results
    if enabled.get("digest", False):
        log.info("Compiling [bold green]digest[/]…")
        digest_mod = DigestModule(config=config, data_dir=str(data_dir))
        digest_result = digest_mod.run(module_results=results)
        results.append(digest_result)

    # Summary table
    _print_summary(results)
    log.info("Bench finished.")


def _print_summary(results: list[ModuleResult]) -> None:
    table = Table(title="Bench Run Summary", show_lines=True)
    table.add_column("Module", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Items", justify="right")
    table.add_column("Note")

    for r in results:
        if r.skipped:
            status = "[yellow]SKIP[/]"
            note = r.skip_reason
        elif r.errors:
            status = "[red]ERROR[/]"
            note = "; ".join(r.errors)
        else:
            status = "[green]OK[/]"
            note = ""
        table.add_row(r.module_name, status, str(len(r.items)), note)

    console.print(table)


def main():
    config = load_config()
    run_pipeline(config)


if __name__ == "__main__":
    main()
