"""Auto-survey generator.

Usage:
    uv run python scripts/survey.py "task and motion planning with LLMs"
    uv run python scripts/survey.py "diffusion models for robot control" --depth 30
    uv run python scripts/survey.py "video generation for robotics" --output ~/Desktop/survey.md
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

console = Console()

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.claude import ask_claude_sync
from src.utils.config import load_config
from src.utils.paper_analysis import get_knowledge_profile

log = logging.getLogger("bench.survey")


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(console=console, show_path=False, markup=True)],
    )


# ---------------------------------------------------------------------------
# Phase 1: Sonnet searches broadly
# ---------------------------------------------------------------------------

def opus_search(topic: str, depth: int) -> str:
    """Opus searches the web for relevant papers on the topic."""
    log.info("Opus searching for papers on: %s", topic)

    prompt = f"""You are a senior researcher doing a precise literature search on: "{topic}"

IMPORTANT: Stay strictly on topic. Do NOT drift to adjacent popular areas.
For example, if the topic is "LLM for task and motion planning", do NOT include VLA/visuomotor policy papers
unless they explicitly involve symbolic planning or TAMP. Relevance to the EXACT topic matters more than popularity.

Search strategy:
1. Search Semantic Scholar and arXiv with precise queries matching the exact topic
2. Find the seminal/foundational papers in this specific sub-area
3. Search for key authors who work specifically on this topic
4. Follow citation chains — check what the foundational papers cite AND what cites them
5. Look for lesser-known but highly relevant workshop papers, not just top-venue hits
6. Search for existing surveys on this exact topic

AVOID popularity bias: a niche paper that is precisely about "{topic}" is MORE valuable
than a famous paper that is only tangentially related.

For each paper found, provide:
- Title
- Authors (first 3)
- Year
- URL (arXiv or Semantic Scholar link)
- Citation count if available
- Abstract or 2-3 sentence summary
- Role: "foundational", "key_contribution", "recent", "survey", or "niche_but_relevant"

Find at least {depth} papers. Ensure diversity:
- Foundational works that defined this specific sub-area
- Key technical contributions (not just popular, but actually advancing THIS topic)
- Recent work (2024-2026) specifically on this topic
- Niche/workshop papers that are directly relevant but may be less cited
- Any existing surveys

Return as a JSON array:
[{{"title": "...", "authors": "...", "year": 2024, "url": "...", "citations": 100, "summary": "...", "role": "key_contribution"}}]"""

    response = ask_claude_sync(
        prompt,
        timeout=600,
        allowed_tools=["WebFetch", "Bash"],
    )
    return response


def parse_paper_list(response: str) -> list[dict]:
    """Extract paper list JSON from Sonnet's response."""
    # Find JSON array in the response
    start = response.find("[")
    end = response.rfind("]")
    if start == -1 or end == -1:
        log.warning("No JSON array found in search response")
        return []
    try:
        return json.loads(response[start:end + 1])
    except json.JSONDecodeError:
        # Try with markdown fence stripping
        text = response.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("["):
                    try:
                        return json.loads(part)
                    except json.JSONDecodeError:
                        continue
        log.warning("Failed to parse paper list JSON")
        return []


# ---------------------------------------------------------------------------
# Phase 1b: Gap detection
# ---------------------------------------------------------------------------

def find_gaps_and_fill(topic: str, existing_papers: list[dict], depth: int) -> list[dict]:
    """Opus reviews the paper list, identifies gaps, and searches to fill them."""
    titles = "\n".join(f"- {p.get('title', '')} ({p.get('year', '?')})" for p in existing_papers)

    prompt = f"""You are reviewing a literature search on: "{topic}"

Here are the papers found so far:
{titles}

Your task:
1. What important sub-topics or approaches are MISSING from this list?
2. Are there specific papers you know should be included but aren't?
3. Are there niche but important papers (workshop papers, lesser-known but technically deep) that are missing?
4. Are there foundational papers from adjacent fields that this topic builds on?

Now search for the missing papers. Focus on filling the gaps, NOT repeating what's already found.
Find papers that are precisely relevant to "{topic}" — not just popular papers from adjacent areas.

Return as a JSON array (same format):
[{{"title": "...", "authors": "...", "year": 2024, "url": "...", "citations": 100, "summary": "...", "role": "key_contribution"}}]

If no gaps found, return []."""

    try:
        response = ask_claude_sync(
            prompt,
            timeout=600,
            allowed_tools=["WebFetch", "Bash"],
        )
        return parse_paper_list(response)
    except Exception as e:
        log.warning("Gap search failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Phase 2: Opus deep-reads key papers
# ---------------------------------------------------------------------------

def opus_deep_read(papers: list[dict], topic: str, max_read: int = 15) -> list[dict]:
    """Sonnet reads full papers and extracts key information."""
    log.info("Sonnet deep-reading top %d papers...", min(len(papers), max_read))

    # Prioritize: foundational first, then key, then recent
    role_order = {"foundational": 0, "survey": 1, "key_contribution": 2, "recent": 3}
    papers_sorted = sorted(papers, key=lambda p: (role_order.get(p.get("role", "recent"), 9), -p.get("citations", 0)))

    for p in papers_sorted[:max_read]:
        url = p.get("url", "")
        title = p.get("title", "")
        if not url:
            continue

        prompt = f"""Read the full paper at: {url}

Survey topic: "{topic}"

After reading the entire paper, extract:
1. **Problem**: What specific problem does this paper address?
2. **Approach**: What is their method? (2-3 sentences)
3. **Key insight**: What's the novel idea that makes this work?
4. **Results**: Main quantitative results or claims
5. **Limitations**: What doesn't work or is unclear?
6. **Builds on**: What prior work does this directly extend?
7. **Enabled**: What later work did this make possible?

Be thorough but concise. Focus on what matters for the survey."""

        try:
            response = ask_claude_sync(
                prompt,
                timeout=600,
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

## Papers collected ({n_papers} total, {n_read} deep-read):

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
        authors = p.get("authors", "?")
        if isinstance(authors, list):
            authors = ", ".join(a.get("name", str(a)) for a in authors[:3])
        year = p.get("year", "?")
        citations = p.get("citations", "?")
        role = p.get("role", "")

        entry = f"**{p.get('title', '')}** ({authors}, {year}) [citations: {citations}, role: {role}]"
        if p.get("summary"):
            entry += f"\nSummary: {p['summary']}"
        if p.get("deep_read"):
            entry += f"\nDeep read notes:\n{p['deep_read']}"
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
# Notion push
# ---------------------------------------------------------------------------

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

    # Phase 1: Opus searches
    console.print("[cyan]Phase 1: Opus searching...[/cyan]")
    search_response = opus_search(topic, depth)
    papers = parse_paper_list(search_response)
    console.print(f"  Round 1: found {len(papers)} papers")

    if not papers:
        console.print("[red]No papers found. Try rephrasing the topic.[/red]")
        return

    # Phase 1b: Gap detection — Opus reviews the list and searches for what's missing
    console.print("[cyan]Phase 1b: Opus checking for gaps...[/cyan]")
    gap_papers = find_gaps_and_fill(topic, papers, depth)
    if gap_papers:
        console.print(f"  Round 2: found {len(gap_papers)} additional papers")
        papers.extend(gap_papers)

    console.print(f"  Total: {len(papers)} papers")

    # Phase 2: Opus deep-reads
    max_read = min(depth, len(papers))
    console.print(f"[cyan]Phase 2: Opus deep-reading top {max_read} papers...[/cyan]")
    read_papers = opus_deep_read(papers, topic, max_read=max_read)

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
        "citations": p.get("citations"), "role": p.get("role"),
        "summary": p.get("summary"), "deep_read": p.get("deep_read"),
    } for p in read_papers]
    data_path.write_text(json.dumps(raw, indent=2, default=str))
    console.print(f"[green]Paper data saved to: {data_path}[/green]")

    # Push to Notion
    console.print("[cyan]Pushing to Notion...[/cyan]")
    push_to_notion(topic, full_survey)


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
