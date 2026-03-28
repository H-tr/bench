"""Auto-survey generator.

Usage:
    uv run python scripts/survey.py "task and motion planning"
    uv run python scripts/survey.py "diffusion models for robot control" --depth 30
    uv run python scripts/survey.py "video generation for robotics" --output ~/Desktop/survey.md
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

import httpx
from rich.console import Console
from rich.logging import RichHandler

console = Console()

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.claude import ask_claude_sync
from src.utils.config import load_config
from src.utils.paper_analysis import get_knowledge_profile

S2_API = "https://api.semanticscholar.org/graph/v1"
ARXIV_API = "https://export.arxiv.org/api/query"

log = logging.getLogger("bench.survey")


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(console=console, show_path=False, markup=True)],
    )


# ---------------------------------------------------------------------------
# Phase 1: Search — cast a wide net
# ---------------------------------------------------------------------------

def search_semantic_scholar(topic: str, limit: int = 50) -> list[dict]:
    """Search Semantic Scholar for papers on a topic."""
    papers = []
    for offset in range(0, limit, 20):
        try:
            resp = httpx.get(
                f"{S2_API}/paper/search",
                params={
                    "query": topic,
                    "fields": "title,authors,url,abstract,year,citationCount,publicationDate",
                    "limit": min(20, limit - offset),
                    "offset": offset,
                },
                timeout=15,
            )
            if resp.status_code == 429:
                log.warning("S2 rate limited, waiting 30s...")
                time.sleep(30)
                continue
            resp.raise_for_status()
            data = resp.json()
            papers.extend(data.get("data", []))
            time.sleep(3)
        except Exception as e:
            log.warning("S2 search failed (offset %d): %s", offset, e)
            break
    return papers


def search_arxiv(topic: str, limit: int = 50) -> list[dict]:
    """Search arXiv for papers on a topic."""
    try:
        resp = httpx.get(
            ARXIV_API,
            params={
                "search_query": f'all:"{topic}"',
                "start": 0,
                "max_results": limit,
                "sortBy": "relevance",
                "sortOrder": "descending",
            },
            timeout=30,
        )
        if resp.status_code == 429:
            log.warning("arXiv rate limited, waiting 30s...")
            time.sleep(30)
            return []
        resp.raise_for_status()
    except Exception as e:
        log.warning("arXiv search failed: %s", e)
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ElementTree.fromstring(resp.text)

    papers = []
    for entry in root.findall("atom:entry", ns):
        title = entry.findtext("atom:title", "", ns).strip().replace("\n", " ")
        paper_id = entry.findtext("atom:id", "", ns).strip()
        abstract = entry.findtext("atom:summary", "", ns).strip().replace("\n", " ")
        authors = ", ".join(
            a.findtext("atom:name", "", ns) for a in entry.findall("atom:author", ns)
        )
        papers.append({
            "title": title,
            "paperId": paper_id,
            "url": paper_id,
            "authors": [{"name": a.strip()} for a in authors.split(",")],
            "abstract": abstract,
            "source": "arxiv",
        })
    return papers


def deduplicate(papers: list[dict]) -> list[dict]:
    """Deduplicate by title similarity."""
    seen_titles = set()
    unique = []
    for p in papers:
        title_key = p.get("title", "").lower().strip()[:80]
        if title_key and title_key not in seen_titles:
            seen_titles.add(title_key)
            unique.append(p)
    return unique


# ---------------------------------------------------------------------------
# Phase 2: Sonnet reads and filters
# ---------------------------------------------------------------------------

def sonnet_filter(papers: list[dict], topic: str) -> list[dict]:
    """Sonnet scores papers by relevance to the survey topic."""
    log.info("Sonnet filtering %d papers...", len(papers))
    scored = []

    # Score in batches of 20
    for i in range(0, len(papers), 20):
        batch = papers[i:i + 20]
        paper_list = ""
        for j, p in enumerate(batch):
            authors = ", ".join(a.get("name", "") for a in p.get("authors", [])[:3])
            citations = p.get("citationCount", "?")
            year = p.get("year", "?")
            paper_list += f"\n[{j}] {p.get('title', '')} ({year}, cited {citations}x)\nAuthors: {authors}\nAbstract: {(p.get('abstract') or '')[:200]}\n"

        prompt = f"""Survey topic: "{topic}"

Score each paper's relevance to this survey topic (1-10).
10 = foundational/must-cite, 7+ = clearly relevant, <5 = tangential.
Also classify: "foundational", "key_contribution", "application", "tangential".

Papers:
{paper_list}

Return ONLY JSON array: [{{"index": 0, "score": 8, "role": "foundational", "reason": "one line"}}]"""

        try:
            response = ask_claude_sync(prompt, model_override="sonnet")
            start = response.find("[")
            end = response.rfind("]")
            if start != -1 and end != -1:
                results = json.loads(response[start:end + 1])
                for item in results:
                    idx = item.get("index", -1)
                    if 0 <= idx < len(batch):
                        batch[idx]["survey_score"] = item.get("score", 0)
                        batch[idx]["survey_role"] = item.get("role", "")
                        batch[idx]["survey_reason"] = item.get("reason", "")
        except Exception as e:
            log.warning("Scoring batch failed: %s", e)

        scored.extend(batch)

    # Sort by score and return top papers
    scored = [p for p in scored if p.get("survey_score", 0) >= 5]
    scored.sort(key=lambda x: (-x.get("survey_score", 0), -x.get("citationCount", 0)))
    return scored


def sonnet_deep_read(papers: list[dict], topic: str, max_read: int = 15) -> list[dict]:
    """Sonnet reads full papers and extracts key information."""
    log.info("Sonnet deep-reading top %d papers...", min(len(papers), max_read))

    for p in papers[:max_read]:
        url = p.get("url", "")
        title = p.get("title", "")

        prompt = f"""Read the full paper at: {url}

Survey topic: "{topic}"

After reading, extract:
1. **Problem**: What specific problem does this paper address?
2. **Approach**: What is their method? (2-3 sentences)
3. **Key insight**: What's the novel idea that makes this work?
4. **Results**: Main quantitative results or claims
5. **Limitations**: What doesn't work or is unclear?
6. **Relation to survey**: How does this fit in the landscape of "{topic}"? What did it build on, what did it enable?

Return as structured text, not JSON. Be thorough but concise."""

        try:
            response = ask_claude_sync(
                prompt,
                model_override="sonnet",
                timeout=300,
                allowed_tools=["WebFetch", "Bash"],
            )
            p["deep_read"] = response
            log.info("  Read: %s", title[:60])
        except Exception as e:
            log.warning("  Deep read failed for %s: %s", title[:40], e)

    return papers


# ---------------------------------------------------------------------------
# Phase 3: Opus synthesizes the survey
# ---------------------------------------------------------------------------

SURVEY_PROMPT = """You are writing a research survey on: "{topic}"

## Researcher context (tailor the survey for them):
{knowledge_context}

## Papers collected ({n_papers} total, top {n_read} deep-read):

{paper_summaries}

## Your task: Write a comprehensive, opinionated survey.

Use this structure:

### 1. Introduction & Problem Definition
- What is the core problem? Why does it matter?
- What makes it hard?

### 2. Taxonomy of Approaches
- Organize existing work into clear categories/families of methods
- Draw a taxonomy tree or table

### 3. Timeline & Evolution
- How did the field evolve? What were the key inflection points?
- Which papers opened new directions vs. which are incremental?

### 4. Key Papers & Contributions
- For each major approach, discuss 3-5 most important papers
- What did each contribute? How do they build on each other?
- Compare strengths and weaknesses across approaches

### 5. State of the Art
- What works best today? Under what conditions?
- Where is there consensus? Where is there disagreement?

### 6. Open Problems & Future Directions
- What are the unsolved challenges?
- What's the most promising direction?
- Connection to the researcher's own work

### 7. Recommended Reading Order
- If someone new to this area had to read 5 papers, which 5 and in what order?

## Rules:
- Be opinionated — don't just list papers, argue for what matters
- Use the deep-read summaries for papers you have them for
- Cite papers as [AuthorLastName et al., Year]
- Include a references section at the end
- Be thorough but not padded — every sentence should earn its place"""


def opus_synthesize(topic: str, papers: list[dict], config: dict) -> str:
    """Opus synthesizes all paper readings into a coherent survey."""
    log.info("Opus synthesizing survey...")

    knowledge = get_knowledge_profile(config)

    # Build paper summaries
    summaries = []
    for p in papers:
        authors = ", ".join(a.get("name", "") for a in p.get("authors", [])[:3])
        year = p.get("year", "?")
        citations = p.get("citationCount", "?")
        score = p.get("survey_score", "?")
        role = p.get("survey_role", "")

        entry = f"**{p.get('title', '')}** ({authors}, {year}) [citations: {citations}, relevance: {score}/10, role: {role}]"
        if p.get("deep_read"):
            entry += f"\nDeep read notes:\n{p['deep_read']}"
        elif p.get("survey_reason"):
            entry += f"\nNote: {p['survey_reason']}"
        summaries.append(entry)

    paper_text = "\n\n---\n\n".join(summaries)

    prompt = SURVEY_PROMPT.format(
        topic=topic,
        knowledge_context=knowledge,
        n_papers=len(papers),
        n_read=len([p for p in papers if p.get("deep_read")]),
        paper_summaries=paper_text,
    )

    return ask_claude_sync(
        prompt,
        timeout=600,
        allowed_tools=["WebFetch", "Bash"],
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_survey(topic: str, depth: int = 20, output_path: str | None = None):
    config = load_config()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_output = Path(f"~/Dropbox/bench-data/surveys/{topic.replace(' ', '_')[:40]}_{timestamp}.md").expanduser()
    output = Path(output_path) if output_path else default_output
    output.parent.mkdir(parents=True, exist_ok=True)

    console.print(f"\n[bold]Survey: {topic}[/bold]\n")

    # Phase 1: Search
    console.print("[cyan]Phase 1: Searching...[/cyan]")
    s2_papers = search_semantic_scholar(topic, limit=depth * 2)
    arxiv_papers = search_arxiv(topic, limit=depth)
    all_papers = deduplicate(s2_papers + arxiv_papers)
    console.print(f"  Found {len(all_papers)} unique papers")

    if not all_papers:
        console.print("[red]No papers found. Try a different topic.[/red]")
        return

    # Phase 2: Sonnet filters and reads
    console.print("[cyan]Phase 2: Sonnet filtering...[/cyan]")
    filtered = sonnet_filter(all_papers, topic)
    console.print(f"  {len(filtered)} papers passed relevance filter")

    max_read = min(depth, len(filtered))
    console.print(f"[cyan]Phase 2b: Sonnet deep-reading top {max_read} papers...[/cyan]")
    read_papers = sonnet_deep_read(filtered, topic, max_read=max_read)

    # Phase 3: Opus synthesizes
    console.print("[cyan]Phase 3: Opus synthesizing survey...[/cyan]")
    survey = opus_synthesize(topic, read_papers, config)

    # Save locally
    full_survey = f"# Survey: {topic}\n\nGenerated: {datetime.now().isoformat()}\n\n{survey}"
    output.write_text(full_survey)
    console.print(f"\n[green]Survey saved to: {output}[/green]")

    # Save raw data
    data_path = output.with_suffix(".json")
    raw = [{
        "title": p.get("title"), "url": p.get("url"), "year": p.get("year"),
        "citations": p.get("citationCount"), "score": p.get("survey_score"),
        "role": p.get("survey_role"), "deep_read": p.get("deep_read"),
    } for p in read_papers]
    data_path.write_text(json.dumps(raw, indent=2, default=str))
    console.print(f"[green]Paper data saved to: {data_path}[/green]")

    # Push to Notion — Literature & Reading Notes section
    console.print("[cyan]Pushing to Notion...[/cyan]")
    push_to_notion(topic, full_survey)


# Literature & Reading Notes page ID
NOTION_LIT_REVIEW_PAGE_ID = "31c49a6e-a20e-8133-a1ba-e4840f674106"


def push_to_notion(topic: str, survey_content: str) -> None:
    """Create a sub-page under Literature & Reading Notes in Notion."""
    prompt = f"""Create a new Notion page as a child of page ID "{NOTION_LIT_REVIEW_PAGE_ID}".

Title: "📖 Survey: {topic}"

Content (use this exact markdown):

{survey_content}

Return ONLY the page URL."""

    try:
        response = ask_claude_sync(prompt, model_override="sonnet", timeout=600)
        for line in response.strip().split("\n"):
            if "notion.so" in line:
                url = line.strip().split("(")[-1].rstrip(")") if "(" in line else line.strip()
                console.print(f"[green]Notion page: {url}[/green]")
                return
        console.print("[yellow]Survey pushed but couldn't extract URL[/yellow]")
    except Exception as e:
        console.print(f"[red]Notion push failed: {e}[/red]")


def main():
    parser = argparse.ArgumentParser(description="Auto-survey generator")
    parser.add_argument("topic", help="Survey topic (e.g. 'task and motion planning')")
    parser.add_argument("--depth", type=int, default=20, help="How many papers to deep-read (default: 20)")
    parser.add_argument("--output", "-o", help="Output file path (default: ~/Dropbox/bench-data/surveys/)")
    args = parser.parse_args()

    setup_logging()
    run_survey(args.topic, depth=args.depth, output_path=args.output)


if __name__ == "__main__":
    main()
