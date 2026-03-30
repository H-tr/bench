"""Digest compiler: assembles all module results and pushes to Notion via Claude Code CLI."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from src.modules.base import BaseModule, ModuleResult
from src.utils.claude import ask_claude_sync
from src.utils.data import save_json

log = logging.getLogger("bench.digest")


class DigestModule(BaseModule):
    name = "digest"
    section_title = "DIGEST"

    def run(self, module_results: list[ModuleResult] | None = None) -> ModuleResult:
        if not module_results:
            return self._skip("No module results to compile")

        today = datetime.now()
        date_str = today.strftime("%Y-%m-%d")
        weekday = today.strftime("%A")

        # Build the digest content (also collects paper analyses for sub-pages)
        self._paper_analyses: list[dict] = []
        content = self._build_content(module_results, date_str, weekday)

        # Archive locally
        if self.config.get("digest", {}).get("archive_locally", True):
            archive_dir = Path(self.data_dir) / "digests"
            archive_dir.mkdir(parents=True, exist_ok=True)
            save_json(archive_dir / f"{date_str}.json", {
                "date": date_str,
                "content": content,
                "results": [
                    {"module": r.module_name, "items": r.items, "errors": r.errors}
                    for r in module_results
                ],
            })

        # Push to Notion via Claude Code CLI
        notion_url = None
        try:
            notion_url = self._push_to_notion_via_claude(content, date_str, weekday)
            if notion_url:
                log.info("Digest pushed to Notion: %s", notion_url)
                # Create sub-pages for paper delta briefings
                if self._paper_analyses:
                    self._create_analysis_subpages(notion_url, self._paper_analyses)
        except Exception as e:
            log.error("Notion push failed: %s", e)

        errors = []
        for r in module_results:
            errors.extend(r.errors)

        return self._result(items=[{
            "date": date_str,
            "notion_url": notion_url,
            "sections": len([r for r in module_results if r.ok and r.items]),
            "total_items": sum(len(r.items) for r in module_results if r.ok),
            "errors": errors,
        }])

    def _build_content(self, results: list[ModuleResult], date_str: str, weekday: str) -> str:
        """Build markdown content for the digest."""
        lines = [f"# 📅 {date_str} {weekday}\n"]

        for r in results:
            if r.skipped or not r.items:
                continue

            lines.append(f"\n## {r.section_title}\n")

            for item in r.items:
                if isinstance(item, dict):
                    # Assistant items — render the text block directly
                    if item.get("type") in ("calendar", "email", "group_meeting",
                                             "reading_group", "deadlines", "tasks",
                                             "habits", "paper_suggestions"):
                        lines.append(item.get("text", ""))
                        lines.append("")
                    elif item.get("type") == "stats":
                        lines.append(f"**{item.get('text', '')}**")
                        for change in item.get("changes", []):
                            lines.append(f"  - 📈 {change}")
                    elif item.get("type") == "opportunity":
                        url = item.get("url", "")
                        title = item.get("title", "Untitled")
                        company = item.get("company", "")
                        summary = item.get("summary", "")
                        link = f"[{title}]({url})" if url else title
                        lines.append(f"- 💼 **{company}**: {link}")
                        if summary:
                            lines.append(f"  {summary}")
                    elif item.get("score"):
                        # Paper — one-liner in digest, analysis goes to sub-page
                        url = item.get("url", "")
                        title = item.get("title", "Untitled")
                        link = f"[{title}]({url})" if url else title
                        score = item.get("score", "")
                        summary = item.get("summary", "")
                        tracked = item.get("tracked_author", "")
                        prefix = f"🔔 **{tracked}**: " if tracked else ""
                        lines.append(f"- {prefix}{link} [{score}/10]")
                        if summary:
                            lines.append(f"  {summary}")
                        # Delta briefings collected for sub-pages (not inline)
                        if item.get("analysis"):
                            self._paper_analyses.append({
                                "title": title,
                                "url": url,
                                "analysis": item["analysis"],
                            })
                    elif item.get("summary"):
                        # News item
                        url = item.get("url", "")
                        title = item.get("title", "Untitled")
                        source = item.get("source", "")
                        link = f"[{title}]({url})" if url else title
                        lines.append(f"- {link} ({source})")
                        lines.append(f"  {item['summary']}")
                    elif item.get("text"):
                        lines.append(f"- {item['text']}")

        # Errors section
        all_errors = [e for r in results for e in r.errors]
        if all_errors:
            lines.append(f"\n## ⚠️ ERRORS\n")
            for err in all_errors:
                lines.append(f"- {err}")

        return "\n".join(lines)

    def _push_to_notion_via_claude(self, content: str, date_str: str, weekday: str) -> str | None:
        """Push digest to Notion using Claude Code CLI (which has Notion MCP access)."""
        parent_id = self.config.get("digest", {}).get("notion_parent_page_id", "")
        if not parent_id:
            log.warning("notion_parent_page_id not configured, skipping Notion push")
            return None

        # Escape content for the prompt
        escaped_content = content.replace('"', '\\"').replace('`', '\\`')

        prompt = f"""Create a new Notion page as a child of page ID "{parent_id}".

Title: "📅 {date_str} {weekday}"

Content (use this exact markdown):

{content}

After creating the page, return ONLY the page URL. Nothing else."""

        try:
            response = ask_claude_sync(
                prompt,
                timeout=1800,
                allowed_tools=["mcp__claude_ai_Notion__notion-create-pages"],
            )
            # Extract URL from response
            for line in response.strip().split("\n"):
                line = line.strip()
                if "notion.so" in line:
                    # Clean up any markdown link formatting
                    if "(" in line and ")" in line:
                        line = line.split("(")[-1].rstrip(")")
                    return line.strip()
            log.warning("No Notion URL found in Claude response: %s", response[:200])
            return None
        except Exception as e:
            log.error("Claude Notion push failed: %s", e)
            return None

    def _create_analysis_subpages(self, digest_url: str, analyses: list[dict]) -> None:
        """Create sub-pages under the digest for each paper's delta briefing."""
        # Extract page ID from URL
        page_id = digest_url.rstrip("/").split("/")[-1].split("?")[0]
        # Remove any title prefix (Notion URLs are like /Title-hexid)
        if "-" in page_id:
            page_id = page_id.split("-")[-1]

        for paper in analyses:
            title = paper.get("title", "Untitled")[:80]
            analysis = paper.get("analysis", "")
            url = paper.get("url", "")

            prompt = f"""Create a new Notion page as a child of page ID "{page_id}".

Title: "📊 {title}"

Content:

**Paper:** [{title}]({url})

---

{analysis}

Return ONLY the page URL."""

            try:
                ask_claude_sync(
                    prompt,
                    timeout=300,
                    allowed_tools=["mcp__claude_ai_Notion__notion-create-pages"],
                )
                log.info("  Created analysis sub-page: %s", title[:40])
            except Exception as e:
                log.warning("  Failed to create sub-page for %s: %s", title[:40], e)
