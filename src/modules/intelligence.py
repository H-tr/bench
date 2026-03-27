"""Personal intelligence: citations, author tracking, opportunities."""

from src.modules.base import BaseModule, ModuleResult


class IntelligenceModule(BaseModule):
    name = "intelligence"
    section_title = "📊 MY STATS"

    def run(self) -> ModuleResult:
        # Phase 4: citation tracking, author monitoring, opportunities
        return self._skip("Not yet implemented (Phase 4)")
