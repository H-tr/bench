# Bench

A researcher's daily automation system. Fetches papers, tracks citations, monitors news, manages tasks, and pushes a concise daily digest to Notion.

## Setup

```bash
uv sync                    # install everything
cp .env.example .env       # fill in API keys
vim config.yaml            # set your research keywords, categories, etc.
```

## Usage

```bash
uv run python src/runner.py
```

## What happens when you run it

1. **Load config** — reads `config.yaml` and `.env`
2. **Run modules in order**, each producing a section for the digest:
   - **assistant** — checks calendar, deadlines, tasks, suggests today's priorities
   - **papers** — fetches new arXiv papers, scores relevance with Claude, imports top picks to Zotero
   - **intelligence** — tracks your citations, co-authors' new papers, job/grant opportunities
   - **news** — pulls RSS feeds, filters AI/robotics news, generates one-line summaries
3. **Compile digest** — the digest module collects all results and pushes a single-page summary to Notion
4. **Print summary** — shows a table of what ran, what succeeded, and what errored

Each module is independent. If one crashes, the others still run. Disable any module in `config.yaml` under `modules:`. Logs are saved to `~/Dropbox/bench-data/logs/`.

## Cron (optional)

```
0 7 * * * cd /path/to/bench && uv run python src/runner.py >> ~/Dropbox/bench-data/logs/cron.log 2>&1
```

## Config

All settings live in `config.yaml`: arXiv categories, keywords, relevance thresholds, RSS feeds, deadlines, and module toggles.

## Data

Persistent data (seen papers, tasks, logs, digests) is stored in `~/Dropbox/bench-data/` — synced across machines via Dropbox.
