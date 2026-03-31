"""Auto-survey generator.

Usage:
    uv run python scripts/survey.py "task and motion planning with LLMs"
    uv run python scripts/survey.py "diffusion models for robot control" --depth 30
    uv run python scripts/survey.py "video generation for robotics" --output ~/Desktop/survey.md
    uv run python scripts/survey.py "robot control" --provider codex
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
from src.utils.codex import ask_codex_sync
from src.utils.config import load_config
from src.utils.paper_analysis import get_knowledge_profile

# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------

def _ask(prompt: str, provider: str, *, timeout: int = 1800, allowed_tools: list[str] | None = None) -> str:
    """Route a prompt to the selected provider."""
    if provider == "codex":
        return ask_codex_sync(prompt, timeout=timeout)
    # default: claude
    return ask_claude_sync(prompt, timeout=timeout, allowed_tools=allowed_tools)

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

TITLE_PROMPT = """Given this rough research topic description, generate a concise, professional survey title.

Description: "{topic}"

Return ONLY the title text, nothing else. No quotes, no "Survey:" prefix, no explanation.
Example: if the description is "how LLMs are used for planning robot tasks", a good title might be "Large Language Models for Task and Motion Planning in Robotics"."""


SEARCH_PROMPT = """You are a senior researcher doing a precise literature search on: "{topic}"
Focus on this specific angle: {focus}

IMPORTANT: Stay strictly on topic. Do NOT drift to adjacent popular areas.
AVOID popularity bias: a niche paper precisely about this topic is MORE valuable
than a famous paper only tangentially related.

Search Semantic Scholar, arXiv, and the web. Follow citation chains. Find ~{count} items.

For each item, provide:
- Title, Authors (first 3 or maintainers), Year, URL, Citation count (0 if N/A), 2-sentence summary
- Role: "foundational", "key_contribution", "recent", "survey", or "niche_but_relevant"

Return ONLY a JSON array:
[{{"title": "...", "authors": "...", "year": 2024, "url": "...", "citations": 100, "summary": "...", "role": "key_contribution"}}]"""

RESOURCE_SEARCH_PROMPT = """You are a senior researcher cataloguing practical resources for: "{topic}"
Focus on: {focus}

Search GitHub, the web, university course pages, and documentation sites.
Find ~{count} resources.

For each resource, provide:
- Title, Authors/Maintainers, Year (of last update), URL, Stars/Citations (0 if unknown), 2-sentence summary
- Role: "software", "tutorial", "course", or "benchmark"

Return ONLY a JSON array:
[{{"title": "...", "authors": "...", "year": 2024, "url": "...", "citations": 0, "summary": "...", "role": "software"}}]"""


def _get_notable_groups() -> list[str]:
    """Load notable research groups from config."""
    try:
        config = load_config()
        return config.get("survey", {}).get("notable_groups", [])
    except Exception:
        return []


def opus_search(topic: str, depth: int, provider: str = "claude") -> str:
    """Searches in multiple focused rounds to avoid timeout."""
    log.info("[%s] Searching for papers on: %s", provider, topic)

    # Build the group-aware search focus
    groups = _get_notable_groups()
    group_names = ", ".join(groups[:15]) if groups else "major robotics/AI labs worldwide"

    search_tools = ["WebSearch", "WebFetch", "Bash"]

    # Split into focused sub-searches so each call is manageable
    paper_focuses = [
        f"foundational and seminal papers that started the area of {topic}",
        f"key technical contributions and methods (2020-2024) in {topic}",
        f"most recent work (2024-2026) and state-of-the-art in {topic}",
        f"niche, lesser-known, or workshop papers specifically about {topic} — avoid popular/obvious ones",
        (
            f"papers on {topic} from a diverse range of research groups worldwide, "
            f"including but not limited to: {group_names}. "
            f"Do NOT only search for big-name labs — also look for good work from "
            f"smaller or newer groups. Search broadly across English AND Chinese venues."
        ),
    ]

    resource_focuses = [
        (
            f"GitHub repositories, open-source libraries, and software tools for {topic} — "
            f"look for actively maintained projects, popular frameworks, and reference implementations"
        ),
        (
            f"tutorials, lecture notes, university courses, blog posts, and documentation "
            f"that teach or explain {topic}"
        ),
    ]

    all_papers = []
    per_focus = max(8, depth // (len(paper_focuses) + len(resource_focuses)))

    total_rounds = len(paper_focuses) + len(resource_focuses)

    # Paper search rounds
    for i, focus in enumerate(paper_focuses):
        log.info("  Search round %d/%d: %s", i + 1, total_rounds, focus[:60])
        prompt = SEARCH_PROMPT.format(topic=topic, focus=focus, count=per_focus)

        try:
            response = _ask(prompt, provider, timeout=1800, allowed_tools=search_tools)
            papers = parse_paper_list(response)
            log.info("    Found %d papers", len(papers))
            all_papers.extend(papers)
        except Exception as e:
            log.warning("    Search round %d failed: %s", i + 1, e)

    # Resource search rounds (software, tutorials, courses)
    for i, focus in enumerate(resource_focuses):
        round_num = len(paper_focuses) + i + 1
        log.info("  Search round %d/%d: %s", round_num, total_rounds, focus[:60])
        prompt = RESOURCE_SEARCH_PROMPT.format(topic=topic, focus=focus, count=per_focus)

        try:
            response = _ask(prompt, provider, timeout=1800, allowed_tools=search_tools)
            resources = parse_paper_list(response)
            log.info("    Found %d resources", len(resources))
            all_papers.extend(resources)
        except Exception as e:
            log.warning("    Resource round %d failed: %s", i + 1, e)

    # Return as JSON string for compatibility with parse_paper_list
    return json.dumps(all_papers)


def parse_paper_list(response: str) -> list[dict]:
    """Extract paper list JSON from response."""
    if not response or not response.strip():
        log.warning("Empty response from LLM")
        return []

    # Find JSON array in the response
    start = response.find("[")
    end = response.rfind("]")
    if start == -1 or end == -1:
        log.warning("No JSON array found in search response. First 500 chars:\n%s", response[:500])
        return []
    try:
        return json.loads(response[start:end + 1])
    except json.JSONDecodeError as e:
        log.warning("JSON parse failed: %s", e)
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
        log.warning("All JSON parse attempts failed. First 500 chars:\n%s", response[:500])
        return []


# ---------------------------------------------------------------------------
# Phase 1b: Gap detection
# ---------------------------------------------------------------------------

GAP_ANALYSIS_PROMPT = """You are reviewing a literature search on: "{topic}"

Here are the papers and resources found so far:
{titles}

Your task:
1. What important sub-topics or approaches are MISSING from this list?
2. Are there niche but important angles (workshop papers, lesser-known but technically deep) that are missing?
3. Are there foundational papers from adjacent fields that this topic builds on?
4. Are there important software tools, GitHub repos, tutorials, or courses missing?

Return ONLY a JSON array of 2-4 short search focus strings that describe the missing areas.
Example: ["reinforcement learning approaches to X", "open-source simulators for X"]

If no significant gaps, return []."""


def find_gaps_and_fill(topic: str, existing_papers: list[dict], depth: int, provider: str = "claude") -> list[dict]:
    """Reviews the paper list, identifies gaps, and searches to fill them.

    Split into two lightweight steps:
    1. Fast gap analysis (no tools, short timeout) to identify missing sub-topics.
    2. Reuse SEARCH_PROMPT with those gap topics as focuses.
    """
    titles = "\n".join(f"- {p.get('title', '')} ({p.get('year', '?')})" for p in existing_papers)

    # Step 1: Identify gaps (no tools needed, short timeout)
    prompt = GAP_ANALYSIS_PROMPT.format(topic=topic, titles=titles)
    try:
        response = _ask(prompt, provider, timeout=300)
    except Exception as e:
        log.warning("Gap analysis failed: %s", e)
        return []

    # Parse the gap focus strings
    gap_focuses = _parse_gap_focuses(response)
    if not gap_focuses:
        log.info("No gaps identified")
        return []

    log.info("Identified %d gap areas: %s", len(gap_focuses), gap_focuses)

    # Step 2: Search for papers in each gap area using existing search infra
    all_gap_papers = []
    per_focus = max(5, depth // (len(gap_focuses) * 2))

    for i, focus in enumerate(gap_focuses):
        log.info("  Gap search %d/%d: %s", i + 1, len(gap_focuses), focus[:60])
        search_prompt = SEARCH_PROMPT.format(topic=topic, focus=focus, count=per_focus)
        try:
            response = _ask(search_prompt, provider, timeout=900, allowed_tools=["WebSearch", "WebFetch", "Bash"])
            papers = parse_paper_list(response)
            log.info("    Found %d papers", len(papers))
            all_gap_papers.extend(papers)
        except Exception as e:
            log.warning("    Gap search round %d failed: %s", i + 1, e)

    return all_gap_papers


def _parse_gap_focuses(response: str) -> list[str]:
    """Extract gap focus strings from the analysis response."""
    start = response.find("[")
    end = response.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        result = json.loads(response[start:end + 1])
        if isinstance(result, list) and all(isinstance(s, str) for s in result):
            return result[:4]  # Cap at 4 focuses
        return []
    except json.JSONDecodeError:
        return []


# ---------------------------------------------------------------------------
# Phase 2: Opus deep-reads key papers
# ---------------------------------------------------------------------------

def _citation_count(value: object) -> int:
    """Return a sortable citation count from model-produced paper metadata."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        normalized = value.strip().replace(",", "")
        if not normalized:
            return 0
        try:
            return int(float(normalized))
        except ValueError:
            return 0
    return 0


def opus_deep_read(papers: list[dict], topic: str, max_read: int = 15, provider: str = "claude") -> list[dict]:
    """Deep-reads full papers and extracts key information."""
    log.info("[%s] Deep-reading top %d papers...", provider, min(len(papers), max_read))

    # Prioritize: foundational first, then key, then recent
    role_order = {"foundational": 0, "survey": 1, "key_contribution": 2, "recent": 3}
    papers_sorted = sorted(
        papers,
        key=lambda p: (
            role_order.get(p.get("role", "recent"), 9),
            -_citation_count(p.get("citations")),
        ),
    )

    for p in papers_sorted[:max_read]:
        url = p.get("url", "")
        title = p.get("title", "")
        if not url:
            continue

        role = p.get("role", "")
        if role in ("software", "tutorial", "course", "benchmark"):
            prompt = f"""Read the resource at: {url}

Survey topic: "{topic}"

This is a {role} resource. After reading, extract:
1. **Purpose**: What does this tool/resource do?
2. **Key features**: Main capabilities or topics covered
3. **Maturity**: How actively maintained? Community size? Documentation quality?
4. **Usage**: How is it typically used in practice?
5. **Limitations**: What are the known shortcomings?
6. **Alternatives**: What are competing tools/resources?

Be thorough but concise. Focus on what matters for the survey."""
        else:
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
            response = _ask(prompt, provider, timeout=1800, allowed_tools=["WebSearch", "WebFetch", "Bash"])
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

### 5. Software, Tools & Practical Resources
- What libraries, frameworks, and GitHub repos exist?
- What tutorials, courses, or documentation are most useful for getting started?
- Compare tools: maturity, community, ease of use

### 6. State of the Art
- What works best today? Under what conditions?
- Where is there consensus? Where is there disagreement?

### 7. Open Problems & Future Directions
- What are the unsolved challenges?
- What's the most promising direction?
- Connection to the researcher's own work

### 8. Recommended Reading Order
- If someone new to this area had to read 5 papers, which 5 and in what order?
- What tools should they install first?

## Rules:
- Be opinionated — don't just list papers, argue for what matters
- Use the deep-read summaries for papers you have them for
- Cite papers as [AuthorLastName et al., Year]
- For software/tools, include the GitHub URL or project page
- Include a references section at the end
- Be thorough but not padded — every sentence should earn its place
- DEFINE EVERY TERM ON FIRST USE: whenever you introduce a technical concept, acronym, or framework for the first time, immediately follow it with a brief parenthetical or inline definition (1–2 sentences). Make the definition concrete — say what it *is*, how it works at a high level, and how it differs from the closest related concept. For example: "Signal Temporal Logic (STL), a formal language for specifying time-bounded constraints over continuous signals (unlike Linear Temporal Logic which operates on discrete Boolean propositions), enables..." Do NOT assume the reader knows any term, even common ones like PDDL, affordance, or MDP.
- WRITE LIKE A HUMAN: avoid em dashes (—) and avoid using a colon to introduce a clause mid-sentence. Instead, restructure into natural prose. For example, prefer "This approach builds on X and extends it to Y" over "This approach — which builds on X — extends it to Y"; prefer "The key insight is that..." over "Key insight: ...". Colons are fine in headings and lists, but not as sentence punctuation.
- IMPORTANT: Output the FULL survey text directly in your response. Do NOT use any file-writing tools. Just print the entire markdown survey as your answer."""


def opus_synthesize(topic: str, papers: list[dict], config: dict, provider: str = "claude") -> str:
    """Synthesizes all paper readings into a coherent survey."""
    log.info("[%s] Synthesizing survey...", provider)

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

    return _ask(prompt, provider, timeout=1800, allowed_tools=["WebSearch", "WebFetch", "Bash"])


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

After creating the page, return ONLY the page URL. Nothing else."""

    try:
        response = ask_claude_sync(
            prompt,
            model_override="sonnet",
            timeout=1800,
            allowed_tools=["mcp__claude_ai_Notion__notion-create-pages"],
        )
        for line in response.strip().split("\n"):
            line = line.strip()
            if "notion.so" in line:
                if "(" in line and ")" in line:
                    line = line.split("(")[-1].rstrip(")")
                console.print(f"[green]Notion page: {line}[/green]")
                return
        console.print("[yellow]Survey pushed but couldn't extract URL[/yellow]")
        console.print(f"[dim]Claude response: {response[:300]}[/dim]")
    except Exception as e:
        console.print(f"[red]Notion push failed: {e}[/red]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _checkpoint_dir(topic: str) -> Path:
    """Return the checkpoint directory for a given topic."""
    slug = topic.replace(" ", "_")[:40]
    d = Path(f"~/Dropbox/bench-data/surveys/.checkpoints/{slug}").expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_checkpoint(topic: str, phase: str, data: object) -> None:
    """Save intermediate results to a checkpoint file."""
    path = _checkpoint_dir(topic) / f"{phase}.json"
    path.write_text(json.dumps(data, indent=2, default=str))
    log.info("Checkpoint saved: %s", path)


def _load_checkpoint(topic: str, phase: str) -> object | None:
    """Load a checkpoint file if it exists."""
    path = _checkpoint_dir(topic) / f"{phase}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            log.info("Checkpoint loaded: %s (%s)", phase, path)
            return data
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Corrupt checkpoint %s, re-running: %s", path, e)
    return None


def _dedup_papers(papers: list[dict]) -> list[dict]:
    """Deduplicate papers by title."""
    seen = set()
    unique = []
    for p in papers:
        key = p.get("title", "").lower().strip()[:80]
        if key and key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def generate_title(topic: str, provider: str = "claude") -> str:
    """Ask the LLM to generate a proper survey title from a rough description."""
    log.info("Generating survey title from description: %s", topic)
    try:
        response = _ask(TITLE_PROMPT.format(topic=topic), provider, timeout=120)
        title = response.strip().strip('"').strip("'")
        # Take only the first line in case the model returns extra text
        title = title.split("\n")[0].strip()
        if title:
            return title
    except Exception as e:
        log.warning("Title generation failed: %s", e)
    return topic  # fallback to the raw description


def run_survey(topic: str, depth: int = 20, output_path: str | None = None, provider: str = "claude", skip_gaps: bool = False):
    config = load_config()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_output = Path(f"~/Dropbox/bench-data/surveys/{topic.replace(' ', '_')[:40]}_{timestamp}.md").expanduser()
    output = Path(output_path) if output_path else default_output
    output.parent.mkdir(parents=True, exist_ok=True)

    # Generate a proper title from the rough description
    title = generate_title(topic, provider=provider)
    console.print(f"\n[bold]Survey: {title}[/bold] [dim](topic: {topic}, provider: {provider})[/dim]\n")

    # ── Phase 1: search ──────────────────────────────────────────────
    papers = _load_checkpoint(topic, "phase1_papers")
    if papers is not None:
        console.print(f"[dim]Phase 1: loaded {len(papers)} papers from checkpoint[/dim]")
    else:
        console.print(f"[cyan]Phase 1: [{provider}] searching...[/cyan]")
        search_response = opus_search(topic, depth, provider=provider)
        papers = parse_paper_list(search_response)
        papers = _dedup_papers(papers)
        console.print(f"  Found {len(papers)} unique papers across all rounds")
        _save_checkpoint(topic, "phase1_papers", papers)

    if not papers:
        console.print("[red]No papers found. Try rephrasing the topic.[/red]")
        return

    # ── Phase 1b: gap detection ──────────────────────────────────────
    gap_papers = _load_checkpoint(topic, "phase1b_gaps")
    if gap_papers is not None:
        console.print(f"[dim]Phase 1b: loaded {len(gap_papers)} gap papers from checkpoint[/dim]")
    elif skip_gaps:
        console.print("[dim]Phase 1b: skipped (--skip-gaps)[/dim]")
        gap_papers = []
        _save_checkpoint(topic, "phase1b_gaps", gap_papers)
    else:
        console.print(f"[cyan]Phase 1b: [{provider}] checking for gaps...[/cyan]")
        gap_papers = find_gaps_and_fill(topic, papers, depth, provider=provider)
        _save_checkpoint(topic, "phase1b_gaps", gap_papers)

    if gap_papers:
        console.print(f"  Found {len(gap_papers)} additional papers from gap analysis")
        papers.extend(gap_papers)
        papers = _dedup_papers(papers)

    console.print(f"  Total: {len(papers)} papers")

    # ── Phase 2: deep-reads ──────────────────────────────────────────
    read_papers = _load_checkpoint(topic, "phase2_deepread")
    if read_papers is not None:
        console.print(f"[dim]Phase 2: loaded {len(read_papers)} deep-read papers from checkpoint[/dim]")
    else:
        max_read = min(depth, len(papers))
        console.print(f"[cyan]Phase 2: [{provider}] deep-reading top {max_read} papers...[/cyan]")
        read_papers = opus_deep_read(papers, topic, max_read=max_read, provider=provider)
        _save_checkpoint(topic, "phase2_deepread", read_papers)

    # ── Phase 3: synthesize ──────────────────────────────────────────
    survey = _load_checkpoint(topic, "phase3_survey")
    if survey is not None:
        console.print("[dim]Phase 3: loaded survey from checkpoint[/dim]")
    else:
        console.print(f"[cyan]Phase 3: [{provider}] synthesizing survey...[/cyan]")
        survey = opus_synthesize(topic, read_papers, config, provider=provider)
        _save_checkpoint(topic, "phase3_survey", survey)

    # ── Save final outputs ───────────────────────────────────────────
    full_survey = f"# {title}\n\nGenerated: {datetime.now().isoformat()}\n\n{survey}"
    output.write_text(full_survey)
    console.print(f"\n[green]Survey saved to: {output}[/green]")

    data_path = output.with_suffix(".json")
    raw = [{
        "title": p.get("title"), "url": p.get("url"), "year": p.get("year"),
        "citations": p.get("citations"), "role": p.get("role"),
        "summary": p.get("summary"), "deep_read": p.get("deep_read"),
    } for p in read_papers]
    data_path.write_text(json.dumps(raw, indent=2, default=str))
    console.print(f"[green]Paper data saved to: {data_path}[/green]")

    # Push to Notion (always via Claude Sonnet, regardless of provider)
    console.print("[cyan]Pushing to Notion...[/cyan]")
    push_to_notion(title, full_survey)


def main():
    parser = argparse.ArgumentParser(description="Auto-survey generator")
    parser.add_argument("topic", help="Survey topic (e.g. 'task and motion planning')")
    parser.add_argument("--depth", type=int, default=20, help="How many papers to deep-read (default: 20)")
    parser.add_argument("--output", "-o", help="Output file path (default: ~/Dropbox/bench-data/surveys/)")
    parser.add_argument(
        "--provider",
        choices=["claude", "codex"],
        default="claude",
        help="LLM provider to use: 'claude' (default) or 'codex'",
    )
    parser.add_argument("--skip-gaps", action="store_true", help="Skip Phase 1b gap detection")
    parser.add_argument("--fresh", action="store_true", help="Clear checkpoints and start from scratch")
    args = parser.parse_args()

    setup_logging()

    if args.fresh:
        import shutil
        cp_dir = _checkpoint_dir(args.topic)
        if cp_dir.exists():
            shutil.rmtree(cp_dir)
            console.print(f"[yellow]Cleared checkpoints: {cp_dir}[/yellow]")

    run_survey(args.topic, depth=args.depth, output_path=args.output, provider=args.provider, skip_gaps=args.skip_gaps)


if __name__ == "__main__":
    main()
