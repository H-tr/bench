"""News & industry: RSS feeds, filtering, summaries."""

from src.modules.base import BaseModule, ModuleResult


class NewsModule(BaseModule):
    name = "news"
    section_title = "📰 NEWS"

    def run(self) -> ModuleResult:
        # Phase 3: RSS fetch, keyword filter, Claude summaries
        return self._skip("Not yet implemented (Phase 3)")
