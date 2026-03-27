"""Digest compiler: assembles all module results and pushes to Notion."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.modules.base import BaseModule, ModuleResult


class DigestModule(BaseModule):
    name = "digest"
    section_title = "DIGEST"

    def run(self, module_results: list[ModuleResult] | None = None) -> ModuleResult:
        """Compile results from all other modules into a digest.

        Unlike other modules, digest receives the collected results.
        The runner calls this specially after all other modules finish.
        """
        if not module_results:
            return self._skip("No module results to compile")

        today = datetime.now().strftime("%Y-%m-%d %A")
        errors = []
        for r in module_results:
            errors.extend(r.errors)

        digest = {
            "date": today,
            "sections": [
                {"title": r.section_title, "items": r.items}
                for r in module_results
                if r.ok and r.items
            ],
            "errors": errors,
        }

        self.log.info("Digest compiled for %s (%d sections)", today, len(digest["sections"]))

        # Phase 2: Notion push + local archive
        return self._result(items=[digest])
