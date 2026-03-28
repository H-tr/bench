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
        profile_ref = f"\nLinkedIn: {linkedin_url}" if linkedin_url else ""

        # Load knowledge profile for context on who this person is
        from src.utils.paper_analysis import get_knowledge_profile
        knowledge = get_knowledge_profile(self.config)

        prompt = f"""First, read the researcher's profile below to understand who they are,
their career stage, and what kind of opportunities would be relevant:

{knowledge}
{profile_ref}

Now search for opportunities that FIT THIS SPECIFIC PERSON's career stage and situation.
Preferred locations: {location_str}

IMPORTANT:
- Match opportunities to their actual career stage (student? postdoc? faculty? industry?)
- Do NOT suggest obvious positions everyone knows about (e.g. if they're a PhD student, don't suggest senior research scientist roles at Google/NVIDIA/PI)
- Find things they might NOT know about: niche fellowships, internships, workshops, visiting programs, competitions, grants, collaboration calls
- Be specific about deadlines and eligibility
- Only include things with actual URLs you've verified

Return ONLY a JSON array: [{{"title": "...", "company": "...", "url": "...", "summary": "one line why — include deadline/eligibility"}}]
Max 5 most relevant. If nothing found, return [].
"""

        try:
            response = ask_claude_sync(prompt, model_override="sonnet", allowed_tools=["WebFetch", "Bash"])
            # Extract JSON
            start = response.find("[")
            end = response.rfind("]")
            if start != -1 and end != -1:
                opps = json.loads(response[start:end + 1])
            else:
                opps = []
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
