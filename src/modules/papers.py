"""Paper tracking: arXiv fetch, relevance scoring, Zotero import."""

from src.modules.base import BaseModule, ModuleResult


class PapersModule(BaseModule):
    name = "papers"
    section_title = "📄 PAPERS"

    def run(self) -> ModuleResult:
        # Phase 1: arXiv fetch, Claude scoring, Zotero import
        return self._skip("Not yet implemented (Phase 1)")
