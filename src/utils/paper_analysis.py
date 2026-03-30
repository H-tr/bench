"""Paper analysis engine — personalized delta briefings.

The core idea: your brain is the bottleneck. For each paper, extract ONLY
what is NEW to you. Skip background you already know. Focus on insights,
hidden weaknesses, and actionable takeaways.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.utils.claude import ask_claude_sync
from src.utils.data import load_json, save_json

log = logging.getLogger("bench.paper_analysis")

KNOWLEDGE_PROFILE_PATH = Path("~/Dropbox/bench-data/knowledge_profile.md").expanduser()

ANALYSIS_PROMPT = """You are a critical research paper analyst for {researcher_name}.

## Researcher's knowledge profile (skip anything they already know):
{knowledge_context}

## Paper to analyze:
Title: {title}
Authors: {authors}
URL: {url}
Abstract: {abstract}

IMPORTANT: Fetch the full paper from the URL above. Read it thoroughly — the abstract is just a starting point.
Use the full text to give a deep, detailed analysis. If you can access the PDF, read it entirely.

## Your task: Generate a DELTA BRIEFING — only what is NEW to this researcher.

### 1. PROBLEM (1 sentence)
What specific problem is this paper solving?

### 2. NOVELTY CLASS
Is this: (a) incremental improvement on existing methods, (b) novel combination of known ideas, or (c) genuinely new paradigm/area? Give a one-line justification.

### 3. BACKGROUND DELTA
What background does this researcher NOT already know? Check their profile above — skip concepts they're already expert in. Only explain what's genuinely new context for them. If they know everything needed, say "None — you have full context."
What are the classical/naive solutions to this problem?

### 4. KEY INSIGHT (2-3 sentences max)
What is the unique, non-obvious insight? What would you miss by just reading the abstract? Why does this work when simpler approaches don't?

### 5. TAKEAWAYS FOR YOUR WORK
How does this connect to the researcher's current work? Any ideas it sparks? Any techniques worth borrowing?

### 6. HONEST ASSESSMENT
- **What are the authors hiding/downplaying?** (every paper has something)
- **Fundamental limitations:** What is conceptually questionable — things that more data/compute WON'T fix?
- **Engineering gaps:** What limitations are solvable with more resources/effort?
- **Verdict:** Is this a toy demo or a real step forward? Will this matter in 2 years?

Be brutally concise. No filler. The researcher values thinking time over reading time."""


def get_knowledge_profile(config: dict) -> str:
    """Load the researcher's knowledge profile.

    Tries local file first, falls back to config description.
    """
    # Try loading from file
    if KNOWLEDGE_PROFILE_PATH.exists():
        return KNOWLEDGE_PROFILE_PATH.read_text().strip()

    # Fall back: build from config
    researcher = config.get("researcher", {})
    keywords = config.get("papers", {}).get("keywords", [])
    tracked = config.get("tracked_authors", [])

    profile = f"""Name: {researcher.get('name', 'Unknown')}
Research focus: {', '.join(keywords)}
Tracks authors: {', '.join(a['name'] for a in tracked)}"""

    return profile


def build_knowledge_profile(config: dict) -> str:
    """Build a comprehensive knowledge profile by fetching from Notion.

    Call this periodically to keep the profile fresh.
    """
    researcher = config.get("researcher", {})
    name = researcher.get("name", "researcher")

    log.info("Building knowledge profile from Notion...")

    prompt = f"""I need to build a knowledge profile for {name} based on their Notion workspace.

Search their Notion for:
1. Their "Research Hub" page — especially the Research Vision section
2. Their "Research Proposal" page — research directions and methodology
3. Their Research Projects database — active projects and their descriptions

From all of this, create a concise knowledge profile that covers:
- Their core expertise areas (what they deeply understand)
- Methods and techniques they use regularly
- Specific topics they've researched (from their projects)
- Their current research direction and open questions
- Key concepts they're familiar with (no need to explain these)

Format as a bullet-point profile. Be specific — list actual techniques, frameworks, and domains.
This profile will be used to personalize paper analysis: things in this profile will be SKIPPED
(the researcher already knows them), so only genuinely NEW information gets highlighted."""

    try:
        # Longer timeout since it needs to search + fetch Notion pages.
        profile = ask_claude_sync(prompt, timeout=1800)
        # Save to file
        KNOWLEDGE_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        KNOWLEDGE_PROFILE_PATH.write_text(profile)
        log.info("Knowledge profile saved to %s", KNOWLEDGE_PROFILE_PATH)
        return profile
    except Exception as e:
        log.error("Failed to build knowledge profile: %s", e)
        return get_knowledge_profile(config)


def analyze_paper(
    title: str,
    authors: str,
    abstract: str,
    config: dict,
    url: str = "",
) -> str:
    """Generate a personalized delta briefing for a paper."""
    researcher_name = config.get("researcher", {}).get("name", "researcher")
    knowledge = get_knowledge_profile(config)

    prompt = ANALYSIS_PROMPT.format(
        researcher_name=researcher_name,
        knowledge_context=knowledge,
        title=title,
        authors=authors,
        abstract=abstract,
        url=url,
    )

    return ask_claude_sync(
        prompt,
        timeout=600,
        allowed_tools=["WebFetch", "Bash"],
    )


def analyze_papers_batch(papers: list[dict], config: dict, data_dir: str) -> list[dict]:
    """Analyze a batch of top papers and return enriched paper dicts."""
    analyses_dir = Path(data_dir) / "paper_analyses"
    analyses_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for p in papers:
        title = p.get("title", "")
        paper_id = p.get("id", "").replace("/", "_").replace(":", "_")

        # Check cache
        cache_path = analyses_dir / f"{paper_id}.json"
        cached = load_json(cache_path, default=None)
        if cached and cached.get("analysis"):
            p["analysis"] = cached["analysis"]
            results.append(p)
            continue

        log.info("  Analyzing: %s", title[:60])
        try:
            analysis = analyze_paper(
                title=title,
                authors=p.get("authors", ""),
                abstract=p.get("abstract", ""),
                config=config,
                url=p.get("url", ""),
            )
            p["analysis"] = analysis

            # Cache the analysis
            save_json(cache_path, {"title": title, "analysis": analysis})
        except Exception as e:
            log.warning("  Analysis failed for %s: %s", title[:40], e)
            p["analysis"] = None

        results.append(p)

    return results
