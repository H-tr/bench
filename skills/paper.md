---
name: paper
description: Analyze a paper with a personalized delta briefing — what's NEW to you, honest assessment, and takeaways
user_invocable: true
---

The user wants a deep, personalized analysis of a research paper. This is NOT a summary — it's a **delta briefing** that extracts only what is NEW to this specific researcher.

## Steps

1. **Get the paper**: The user provides an arXiv URL, paper title, or PDF path. Fetch the abstract (and full text if possible) from arXiv or the provided source.

2. **Get the researcher's knowledge profile**: Read `~/Dropbox/bench-data/knowledge_profile.md`. If it doesn't exist, read the Notion "Research Hub" page and "Research Proposal" page to understand what the researcher already knows, then save a profile to that file.

3. **Generate the delta briefing** using these 6 questions:

### 1. PROBLEM (1 sentence)
What specific problem is this paper solving?

### 2. NOVELTY CLASS
Is this: (a) incremental improvement, (b) novel combination of known ideas, or (c) genuinely new paradigm? One-line justification.

### 3. BACKGROUND DELTA
What does the researcher NOT already know? Check their profile — skip concepts in their expertise. What are the classical/naive solutions?

### 4. KEY INSIGHT (2-3 sentences)
What is the unique, non-obvious insight? What would you miss from just the abstract?

### 5. TAKEAWAYS FOR YOUR WORK
Connection to the researcher's current projects? Techniques worth borrowing?

### 6. HONEST ASSESSMENT
- **What are the authors hiding/downplaying?**
- **Fundamental limitations:** conceptually questionable, more data/compute WON'T fix
- **Engineering gaps:** solvable with more resources
- **Verdict:** Toy demo or real step forward? Will this matter in 2 years?

## Rules
- Be brutally concise. No filler.
- Skip background the researcher already knows.
- If you don't know something, say so — don't hallucinate.
- The researcher values thinking time over reading time.

## Examples
- `/paper https://arxiv.org/abs/2401.12345`
- `/paper diffusion policy for robot manipulation`
- `/paper ~/Downloads/some_paper.pdf`
