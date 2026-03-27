# Bench

A researcher's daily automation system. Two parts: a **daily digest** (papers, news, opportunities → Notion) and a **personal assistant** (email, calendar, tasks, meetings).

## Setup

```bash
uv sync                    # install everything
cp .env.example .env       # fill in API keys (optional, most things use Claude Code MCP)
vim config.yaml            # set your research keywords, tracked authors, etc.
```

## Daily Digest

Runs once a day (manually or via cron). Fetches papers, news, opportunities and pushes a digest to Notion.

```bash
uv run python src/runner.py
```

What it does:
1. **papers** — arXiv + tracked authors (Semantic Scholar), scored by Claude, top picks surfaced
2. **intelligence** — your citation stats, job/grant opportunities
3. **news** — RSS feeds (TechCrunch, BBC, HN, IEEE, etc.), company blogs, filtered by Claude
4. **digest** — compiles everything into a daily Notion page

## Personal Assistant

Run anytime. Checks your email, calendar, meetings, and tasks.

```bash
uv run python src/assistant.py              # everything
uv run python src/assistant.py -s calendar  # just calendar
uv run python src/assistant.py -s email     # just email
uv run python src/assistant.py -s meetings  # group meeting + reading group
uv run python src/assistant.py -s tasks     # tasks + deadlines + habits
uv run python src/assistant.py -s suggest   # paper suggestions for reading group
```

## Task Management

```bash
uv run python scripts/task.py                              # list tasks
uv run python scripts/task.py add "finish rebuttal" -d 2026-04-01 -p 1
uv run python scripts/task.py done "rebuttal"              # mark done
uv run python scripts/task.py remove "rebuttal"            # delete
```

Or use `/task` in any Claude Code session in this repo.

## Utilities

```bash
uv run python scripts/clear_cache.py       # clear seen papers/news for fresh run
```

## Cron (optional)

```
0 7 * * * cd /path/to/bench && uv run python src/runner.py >> ~/Dropbox/bench-data/logs/cron.log 2>&1
```

## Config

All settings in `config.yaml`: tracked authors, arXiv categories, keywords, RSS feeds, Google Sheet URLs, daily habits, model choice, and module toggles.

## Data

Persistent data in `~/Dropbox/bench-data/` — synced across machines via Dropbox.
