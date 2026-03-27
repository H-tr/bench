"""Personal intelligence: citations, author tracking, opportunities."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from src.modules.base import BaseModule, ModuleResult
from src.utils.claude import ask_claude_sync
from src.utils.data import load_json, save_json

log = logging.getLogger("bench.intelligence")

S2_API = "https://api.semanticscholar.org/graph/v1"


class IntelligenceModule(BaseModule):
    name = "intelligence"
    section_title = "📊 MY STATS & OPPORTUNITIES"

    def run(self) -> ModuleResult:
        items: list[dict] = []

        # 1. Track own citations if configured
        try:
            stats = self._fetch_own_stats()
            if stats:
                items.append(stats)
        except Exception as e:
            log.warning("Own stats fetch failed: %s", e)

        # 2. Search for opportunities
        try:
            opps = self._search_opportunities()
            items.extend(opps)
        except Exception as e:
            log.warning("Opportunity search failed: %s", e)

        if not items:
            return self._result(items=[{"text": "No new stats or opportunities today."}])

        return self._result(items=items)

    def _fetch_own_stats(self) -> dict | None:
        """Fetch the researcher's own citation stats from Semantic Scholar."""
        s2_id = self.config.get("researcher", {}).get("semantic_scholar_id", "")
        if not s2_id:
            return None

        url = f"{S2_API}/author/{s2_id}"
        params = {"fields": "name,hIndex,citationCount,paperCount"}
        resp = httpx.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        stats_path = Path(self.data_dir) / "my_stats.json"
        prev = load_json(stats_path, default={})

        current = {
            "name": data.get("name", ""),
            "h_index": data.get("hIndex", 0),
            "citations": data.get("citationCount", 0),
            "papers": data.get("paperCount", 0),
            "date": str(data),
        }

        # Detect changes
        changes = []
        if prev:
            if current["citations"] != prev.get("citations", 0):
                diff = current["citations"] - prev.get("citations", 0)
                changes.append(f"+{diff} citations" if diff > 0 else f"{diff} citations")
            if current["h_index"] != prev.get("h_index", 0):
                changes.append(f"h-index: {prev.get('h_index', 0)} → {current['h_index']}")

        save_json(stats_path, current)

        return {
            "type": "stats",
            "text": f"h-index: {current['h_index']} | Citations: {current['citations']} | Papers: {current['papers']}",
            "changes": changes,
        }

    def _search_opportunities(self) -> list[dict]:
        """Search for relevant opportunities using Claude + web search."""
        opp_cfg = self.config.get("opportunities", {})
        keywords = opp_cfg.get("keywords", [])
        locations = opp_cfg.get("locations", [])
        researcher = self.config.get("researcher", {})
        linkedin_url = researcher.get("linkedin_url", "")

        if not keywords:
            return []

        seen_path = Path(self.data_dir) / "seen_opportunities.json"
        seen = set(load_json(seen_path, default=[]))

        # Use Claude to search for opportunities
        location_str = ", ".join(locations) if locations else "anywhere"
        keyword_str = ", ".join(keywords[:5])
        profile_ref = f"\nThe researcher's LinkedIn: {linkedin_url}" if linkedin_url else ""

        prompt = f"""Search for recent job/research opportunities in these areas: {keyword_str}
Preferred locations: {location_str}
The researcher is {researcher.get('name', 'a robotics researcher')} working on robot manipulation, reasoning, and planning at NUS Singapore.{profile_ref}

Look for:
- Research scientist / postdoc positions at top labs and robotics companies
- PhD positions at universities with strong robotics programs
- Relevant grants or fellowships
- Positions at companies like Physical Intelligence, Figure AI, Google DeepMind, NVIDIA, Boston Dynamics, etc.

Return ONLY a JSON array of opportunities: [{{"title": "...", "company": "...", "url": "...", "summary": "one line why this is relevant"}}]
Max 5 most relevant opportunities. If you can't find current listings, return [].
"""

        try:
            response = ask_claude_sync(prompt, system_prompt="You are a job/opportunity search assistant. Return only valid JSON.")
            response = response.strip()
            if response.startswith("```"):
                response = response.split("\n", 1)[1].rsplit("```", 1)[0]
            opps = json.loads(response)
        except Exception as e:
            log.error("Opportunity search failed: %s", e)
            return []

        results = []
        for opp in opps:
            key = opp.get("url", opp.get("title", ""))
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "type": "opportunity",
                "title": opp.get("title", ""),
                "company": opp.get("company", ""),
                "url": opp.get("url", ""),
                "summary": opp.get("summary", ""),
            })

        save_json(seen_path, list(seen))
        return results
