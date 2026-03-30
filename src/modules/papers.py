"""Paper tracking: arXiv fetch, Semantic Scholar author tracking, Claude scoring."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

import httpx

from src.modules.base import BaseModule, ModuleResult
from src.utils.claude import ask_claude_sync
from src.utils.data import load_json, save_json

ARXIV_API = "https://export.arxiv.org/api/query"
S2_API = "https://api.semanticscholar.org/graph/v1"

MAX_HTTP_RETRIES = 3
HTTP_RETRY_WAIT = 30  # seconds


def _http_get(url: str, params: dict | None = None, timeout: int = 30) -> httpx.Response:
    """HTTP GET with retry on 429 rate limit."""
    for attempt in range(1, MAX_HTTP_RETRIES + 1):
        resp = httpx.get(url, params=params, timeout=timeout)
        if resp.status_code == 429:
            wait = HTTP_RETRY_WAIT * attempt
            log.warning("Rate limited (429), waiting %ds (attempt %d/%d)...", wait, attempt, MAX_HTTP_RETRIES)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()  # Raise the 429 if all retries exhausted
    return resp  # unreachable

log = logging.getLogger("bench.papers")


def _extract_json_array(text: str) -> list[dict]:
    """Extract a JSON array from Claude's response, handling markdown fences and extra text."""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("["):
                text = part
                break
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []


class PapersModule(BaseModule):
    name = "papers"
    section_title = "📄 PAPERS"

    def run(self) -> ModuleResult:
        cfg = self.config.get("papers", {})
        seen_path = Path(self.data_dir) / "seen_papers.json"
        seen = set(load_json(seen_path, default=[]))

        all_papers: list[dict] = []

        # 1. Fetch from arXiv
        try:
            arxiv_papers = self._fetch_arxiv(cfg)
            log.info("  arXiv returned %d papers", len(arxiv_papers))
        except Exception as e:
            log.error("arXiv fetch failed: %s", e)
            arxiv_papers = []

        # 2. Fetch tracked authors from Semantic Scholar
        try:
            author_papers = self._fetch_tracked_authors()
            log.info("  Tracked authors returned %d papers", len(author_papers))
        except Exception as e:
            log.error("Semantic Scholar fetch failed: %s", e)
            author_papers = []

        # 3. Fetch from tracked institutions via Semantic Scholar
        try:
            inst_papers = self._fetch_institution_papers()
            log.info("  Institutions returned %d papers", len(inst_papers))
        except Exception as e:
            log.error("Institution fetch failed: %s", e)
            inst_papers = []

        # Deduplicate against seen
        new_papers = []
        new_ids = set()
        for p in arxiv_papers + author_papers + inst_papers:
            pid = p.get("id", p.get("paperId", ""))
            if not pid or pid in seen or pid in new_ids:
                continue
            new_ids.add(pid)
            new_papers.append(p)

        log.info("  %d new papers after dedup", len(new_papers))

        if not new_papers:
            return self._result(items=[{"text": "No new papers today."}])

        # 3. STAGE 1: Fast pre-filter with abstracts (no web)
        log.info("  Stage 1: Pre-filtering %d papers by abstract...", len(new_papers))
        scored = self._score_papers_batched(new_papers, cfg)

        prefilter_threshold = cfg.get("prefilter_threshold", 5)
        candidates = [p for p in scored if p.get("score", 0) >= prefilter_threshold]
        # Always include tracked author papers
        for p in scored:
            if p.get("tracked_author") and p not in candidates:
                candidates.append(p)
        candidates = sorted(candidates, key=lambda x: x.get("score", 0), reverse=True)[:15]
        log.info("  Stage 1: %d candidates passed pre-filter", len(candidates))

        # 4. STAGE 2: Deep-read candidates — reads full paper via web
        if candidates:
            log.info("  Stage 2: Reading %d full papers...", len(candidates))
            self._deep_score_papers(candidates, cfg)

        threshold = cfg.get("relevance_threshold", 7)
        max_papers = cfg.get("max_papers_in_digest", 10)
        top_papers = [p for p in candidates if p.get("deep_score", p.get("score", 0)) >= threshold]
        top_papers = sorted(top_papers, key=lambda x: x.get("deep_score", x.get("score", 0)), reverse=True)[:max_papers]
        log.info("  Stage 2: %d papers scored >= %d after deep read", len(top_papers), threshold)

        # 5. STAGE 3: Opus delta analysis for top papers
        max_analyze = cfg.get("max_papers_to_analyze", 5)
        if top_papers:
            from src.utils.paper_analysis import analyze_papers_batch
            log.info("  Stage 3: Opus analyzing top %d papers...", min(len(top_papers), max_analyze))
            analyze_papers_batch(top_papers[:max_analyze], self.config, self.data_dir)

        # 5. Mark all new papers as seen (after scoring succeeded)
        seen.update(new_ids)
        save_json(seen_path, list(seen))

        items = []
        for p in top_papers:
            item = {
                "title": p["title"],
                "authors": p.get("authors", ""),
                "url": p.get("url", ""),
                "summary": p.get("deep_summary", p.get("summary", p["title"])),
                "score": p.get("deep_score", p.get("score", 0)),
                "tracked_author": p.get("tracked_author", ""),
            }
            if p.get("analysis"):
                item["analysis"] = p["analysis"]
            items.append(item)

        if not items:
            items = [{"text": "No papers above relevance threshold today."}]

        return self._result(items=items)

    def _fetch_arxiv(self, cfg: dict) -> list[dict]:
        """Fetch recent papers from arXiv matching categories and keywords."""
        categories = cfg.get("arxiv_categories", ["cs.RO", "cs.AI"])
        keywords = cfg.get("keywords", [])
        max_results = cfg.get("max_results_per_category", 50)

        cat_query = " OR ".join(f"cat:{c}" for c in categories)
        kw_query = " OR ".join(f'all:"{k}"' for k in keywords[:5])
        query = f"({cat_query}) AND ({kw_query})" if kw_query else cat_query

        params = {
            "search_query": query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        resp = _http_get(ARXIV_API, params=params, timeout=30)

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ElementTree.fromstring(resp.text)

        papers = []
        for entry in root.findall("atom:entry", ns):
            title = entry.findtext("atom:title", "", ns).strip().replace("\n", " ")
            paper_id = entry.findtext("atom:id", "", ns).strip()
            summary = entry.findtext("atom:summary", "", ns).strip().replace("\n", " ")
            authors = ", ".join(
                a.findtext("atom:name", "", ns)
                for a in entry.findall("atom:author", ns)
            )
            papers.append({
                "id": paper_id,
                "title": title,
                "authors": authors,
                "abstract": summary[:500],
                "url": paper_id,
                "source": "arxiv",
            })

        return papers

    def _fetch_tracked_authors(self) -> list[dict]:
        """Fetch recent papers from tracked authors via Semantic Scholar."""
        authors = self.config.get("tracked_authors", [])
        if not authors:
            return []

        papers = []
        for author in authors:
            s2_id = author.get("semantic_scholar_id")
            if not s2_id:
                continue

            try:
                url = f"{S2_API}/author/{s2_id}/papers"
                params = {
                    "fields": "title,authors,url,abstract,year,publicationDate",
                    "limit": 5,
                    "sort": "publicationDate:desc",
                }
                resp = _http_get(url, params=params, timeout=15)
                data = resp.json()

                for p in data.get("data", []):
                    pub_date = p.get("publicationDate", "")
                    if pub_date:
                        try:
                            pd = datetime.strptime(pub_date, "%Y-%m-%d")
                            if pd < datetime.now() - timedelta(days=30):
                                continue
                        except ValueError:
                            pass

                    paper_authors = ", ".join(
                        a.get("name", "") for a in p.get("authors", [])[:5]
                    )
                    papers.append({
                        "id": p.get("paperId", ""),
                        "title": p.get("title", ""),
                        "authors": paper_authors,
                        "abstract": (p.get("abstract") or "")[:500],
                        "url": p.get("url", ""),
                        "source": "semantic_scholar",
                        "tracked_author": author["name"],
                    })

                time.sleep(3)  # Rate limit — S2 free tier is strict
            except Exception as e:
                log.warning("Failed to fetch papers for %s: %s", author["name"], e)

        return papers

    def _fetch_institution_papers(self) -> list[dict]:
        """Fetch recent papers from tracked institutions via Semantic Scholar."""
        institutions = self.config.get("tracked_institutions", [])
        if not institutions:
            return []

        keywords = self.config.get("papers", {}).get("keywords", [])[:3]
        papers = []

        for inst in institutions:
            # Search S2 for recent papers mentioning this institution + our keywords
            query = f"{inst} {keywords[0]}" if keywords else inst
            try:
                url = f"{S2_API}/paper/search"
                params = {
                    "query": query,
                    "fields": "title,authors,url,abstract,year,publicationDate",
                    "limit": 5,
                    "year": f"{datetime.now().year}",
                }
                resp = _http_get(url, params=params, timeout=15)
                data = resp.json()

                for p in data.get("data", []):
                    pub_date = p.get("publicationDate", "")
                    if pub_date:
                        try:
                            pd = datetime.strptime(pub_date, "%Y-%m-%d")
                            if pd < datetime.now() - timedelta(days=30):
                                continue
                        except ValueError:
                            pass

                    paper_authors = ", ".join(
                        a.get("name", "") for a in p.get("authors", [])[:5]
                    )
                    papers.append({
                        "id": p.get("paperId", ""),
                        "title": p.get("title", ""),
                        "authors": paper_authors,
                        "abstract": (p.get("abstract") or "")[:500],
                        "url": p.get("url", ""),
                        "source": "semantic_scholar",
                        "tracked_institution": inst,
                    })

                time.sleep(3)  # Rate limit
            except Exception as e:
                log.warning("Failed to fetch papers for %s: %s", inst, e)

        return papers

    def _score_papers_batched(self, papers: list[dict], cfg: dict) -> list[dict]:
        """Score papers in batches of 15 to avoid prompt length issues."""
        batch_size = 15
        for i in range(0, len(papers), batch_size):
            batch = papers[i : i + batch_size]
            self._score_batch(batch, cfg)
        return papers

    def _score_batch(self, papers: list[dict], cfg: dict) -> None:
        """Score a batch of papers using Claude. Modifies papers in place."""
        researcher_name = self.config.get("researcher", {}).get("name", "a robotics researcher")
        keywords = cfg.get("keywords", [])

        paper_list = ""
        for i, p in enumerate(papers):
            tracked = f" [TRACKED AUTHOR: {p['tracked_author']}]" if p.get("tracked_author") else ""
            paper_list += f"\n[{i}] {p['title']}{tracked}\nAuthors: {p.get('authors', 'N/A')}\nAbstract: {p.get('abstract', 'N/A')[:250]}\n"

        prompt = f"""Score each paper 1-10 for {researcher_name} who works on: {', '.join(keywords[:6])}.

7+ = genuinely want to read. Papers marked [TRACKED AUTHOR] are from key researchers to follow — score them at least 7 unless the topic is completely unrelated, and prioritize them in the final ranking.
Write a one-line summary: what they did + why it matters.

{paper_list}

Return ONLY a JSON array: [{{"index": 0, "score": 7, "summary": "one line"}}]"""

        try:
            response = ask_claude_sync(prompt)
            scores = _extract_json_array(response)
            if not scores:
                raise ValueError("No valid JSON array in response")
        except Exception as e:
            log.error("Claude scoring failed for batch: %s", e)
            # Fallback: tracked author papers get 7, others get 5
            for p in papers:
                p["score"] = 7 if p.get("tracked_author") else 5
                p["summary"] = p["title"]
            return

        for item in scores:
            idx = item.get("index", -1)
            if 0 <= idx < len(papers):
                papers[idx]["score"] = item.get("score", 0)
                papers[idx]["summary"] = item.get("summary", papers[idx]["title"])

    def _deep_score_papers(self, papers: list[dict], cfg: dict) -> None:
        """Stage 2: Reads each full paper via web and re-scores. Modifies papers in place."""
        researcher_name = self.config.get("researcher", {}).get("name", "a robotics researcher")
        keywords = cfg.get("keywords", [])

        for p in papers:
            url = p.get("url", "")
            title = p.get("title", "")
            if not url:
                continue

            tracked_note = f"\nNOTE: This paper is by a tracked author ({p['tracked_author']}) — score at least 7 unless completely off-topic." if p.get("tracked_author") else ""
            prompt = f"""You are scoring a paper for {researcher_name} who works on: {', '.join(keywords[:6])}.{tracked_note}

Fetch and READ the full paper at: {url}

After reading the entire paper, provide:
1. A score 1-10 (7+ = genuinely important, not incremental)
2. A one-line summary: the key insight + why it matters
3. Whether this is incremental or genuinely novel

Return ONLY valid JSON: {{"score": 8, "summary": "one line", "novelty": "incremental|novel|paradigm_shift"}}"""

            try:
                response = ask_claude_sync(
                    prompt,
                    timeout=300,
                    allowed_tools=["WebFetch", "Bash"],
                )
                # Parse JSON from response
                result = _extract_json_array(f"[{response}]")  # Wrap single object in array
                if not result:
                    # Try parsing as single JSON object
                    import json
                    start = response.find("{")
                    end = response.rfind("}")
                    if start != -1 and end != -1:
                        result = [json.loads(response[start:end + 1])]

                if result:
                    p["deep_score"] = result[0].get("score", p.get("score", 0))
                    p["deep_summary"] = result[0].get("summary", p.get("summary", ""))
                    p["novelty"] = result[0].get("novelty", "")
                    log.info("    %s → %d/10 (%s)", title[:50], p["deep_score"], p["novelty"])
                else:
                    p["deep_score"] = p.get("score", 0)
            except Exception as e:
                log.warning("    Deep score failed for %s: %s", title[:40], e)
                p["deep_score"] = p.get("score", 0)
