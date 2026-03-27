# Bench

A researcher's daily automation system. Fetches papers, tracks citations, monitors news, manages tasks, and pushes a concise daily digest to Notion.

## Setup

1. Install [uv](https://docs.astral.sh/uv/):
   ```
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Clone and install:
   ```
   git clone <repo-url> bench && cd bench
   uv sync
   ```

3. Configure:
   ```
   cp .env.example .env
   # Fill in your API keys in .env
   # Edit config.yaml with your research keywords, categories, etc.
   ```

4. Run:
   ```
   uv run python src/runner.py
   ```

5. (Optional) Set up cron for daily runs:
   ```
   crontab -e
   # Add: 0 7 * * * cd /path/to/bench && uv run python src/runner.py >> ~/Dropbox/bench-data/logs/cron.log 2>&1
   ```

## Config

All settings live in `config.yaml`: arXiv categories, keywords, relevance thresholds, RSS feeds, deadlines, and module toggles.

## Data

Persistent data (seen papers, tasks, logs, digests) is stored in `~/Dropbox/bench-data/` — synced across machines via Dropbox.

## Modules

| Module | What it does |
|--------|-------------|
| papers | arXiv fetch, relevance scoring, Zotero import |
| intelligence | Citation tracking, author monitoring, opportunities |
| news | RSS feeds, AI/robotics industry news |
| assistant | Tasks, calendar, deadlines, reminders |
| digest | Compiles everything, pushes to Notion |

Disable any module in `config.yaml` under `modules:`.
