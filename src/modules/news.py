"""News & industry: RSS feeds, company tracking, Claude filtering."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import feedparser
import httpx

from src.modules.base import BaseModule, ModuleResult
from src.utils.claude import ask_claude_sync
from src.utils.data import load_json, save_json

log = logging.getLogger("bench.news")


class NewsModule(BaseModule):
    name = "news"
    section_title = "📰 NEWS"

    def run(self) -> ModuleResult:
        cfg = self.config.get("news", {})
        seen_path = Path(self.data_dir) / "seen_news.json"
        seen = set(load_json(seen_path, default=[]))

        all_items: list[dict] = []

        # 1. RSS feeds
        for feed_url in cfg.get("rss_feeds", []):
            try:
                items = self._fetch_rss(feed_url)
                all_items.extend(items)
            except Exception as e:
                log.warning("RSS feed failed (%s): %s", feed_url, e)

        # 2. Company blogs/news (scrape via web fetch)
        for company in cfg.get("companies", []):
            try:
                items = self._fetch_company_news(company)
                all_items.extend(items)
            except Exception as e:
                log.warning("Company news failed (%s): %s", company.get("name", "?"), e)

        # Deduplicate
        new_items = []
        for item in all_items:
            key = item.get("url", item.get("title", ""))
            if key and key not in seen:
                seen.add(key)
                new_items.append(item)

        save_json(seen_path, list(seen))

        if not new_items:
            return self._result(items=[{"text": "No new news today."}])

        # 3. Filter and summarize with Claude
        filtered = self._filter_news(new_items, cfg)

        max_items = cfg.get("max_items_in_digest", 8)
        return self._result(items=filtered[:max_items])

    def _fetch_rss(self, feed_url: str) -> list[dict]:
        """Parse an RSS feed and return items."""
        feed = feedparser.parse(feed_url)
        items = []
        for entry in feed.entries[:20]:
            items.append({
                "title": entry.get("title", "").strip(),
                "url": entry.get("link", ""),
                "published": entry.get("published", ""),
                "description": (entry.get("summary", "") or "")[:300],
                "source": feed.feed.get("title", feed_url),
            })
        return items

    def _fetch_company_news(self, company: dict) -> list[dict]:
        """Fetch latest news/blog from a company page."""
        url = company.get("url", "")
        name = company.get("name", "")
        if not url:
            return []

        try:
            # Try RSS first
            resp = httpx.get(url, timeout=15, follow_redirects=True)
            if "xml" in resp.headers.get("content-type", ""):
                feed = feedparser.parse(resp.text)
                return [
                    {
                        "title": e.get("title", "").strip(),
                        "url": e.get("link", ""),
                        "published": e.get("published", ""),
                        "description": (e.get("summary", "") or "")[:300],
                        "source": name,
                    }
                    for e in feed.entries[:5]
                ]

            # Otherwise, ask Claude to extract news items from the page
            text = resp.text[:5000]
            prompt = f"""Extract news/blog post titles and URLs from this {name} webpage HTML.
Return JSON array: [{{"title": "...", "url": "..."}}]
Only include actual articles/posts, not navigation links. Max 5 items.
If no articles found, return [].

HTML snippet:
{text}"""

            response = ask_claude_sync(prompt, system_prompt="Extract structured data from HTML. Return only valid JSON.")
            response = response.strip()
            if response.startswith("```"):
                response = response.split("\n", 1)[1].rsplit("```", 1)[0]
            articles = json.loads(response)

            return [
                {
                    "title": a.get("title", ""),
                    "url": a.get("url", ""),
                    "source": name,
                }
                for a in articles
                if a.get("title")
            ]
        except Exception as e:
            log.warning("Company fetch failed for %s: %s", name, e)
            return []

    def _filter_news(self, items: list[dict], cfg: dict) -> list[dict]:
        """Use Claude to filter and one-line summarize news items."""
        keywords = cfg.get("keywords", [])
        researcher_name = self.config.get("researcher", {}).get("name", "a robotics researcher")

        item_list = ""
        for i, item in enumerate(items[:25]):
            item_list += f"\n[{i}] {item['title']} ({item.get('source', '')})\n{item.get('description', '')[:150]}\n"

        prompt = f"""Filter these news items for {researcher_name}, a robotics & AI researcher.

Keep items that are:
- AI/ML/robotics breakthroughs, product launches, funding, acquisitions
- Major world events (geopolitics, wars, policy changes) that affect tech/research
- Anything a tech-savvy researcher would want to know about today

Drop: celebrity gossip, sports, purely local news, clickbait.
Write a one-line summary for each kept item.

Items:
{item_list}

Return ONLY valid JSON array: [{{"index": 0, "summary": "one line", "relevant": true}}]
Only include items where relevant=true."""

        try:
            response = ask_claude_sync(prompt, system_prompt="You are a news filter. Return only valid JSON.")
            response = response.strip()
            if response.startswith("```"):
                response = response.split("\n", 1)[1].rsplit("```", 1)[0]
            scored = json.loads(response)
        except Exception as e:
            log.error("Claude news filter failed: %s", e)
            return items[:8]

        result = []
        for s in scored:
            idx = s.get("index", -1)
            if 0 <= idx < len(items) and s.get("relevant", False):
                item = items[idx].copy()
                item["summary"] = s.get("summary", item["title"])
                result.append(item)

        return result
