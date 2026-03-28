"""Personal assistant: email, calendar, tasks, group meetings, reading group, paper suggestions."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from src.modules.base import BaseModule, ModuleResult
from src.utils.claude import ask_claude_sync
from src.utils.data import load_json, save_json

log = logging.getLogger("bench.assistant")


class AssistantModule(BaseModule):
    name = "assistant"
    section_title = "📋 TODAY"

    def run_section(self, section: str) -> ModuleResult:
        """Run a single section of the assistant."""
        cfg = self.config.get("assistant", {})
        cal_cfg = self.config.get("calendar", {})
        deadline_cfg = self.config.get("deadlines", {})
        today = datetime.now().strftime("%Y-%m-%d %A")
        items: list[dict] = []

        runners = {
            "calendar": lambda: self._check_calendar(today) if cal_cfg.get("enabled", True) else None,
            "email": lambda: self._check_email(cfg) if cfg.get("email_enabled", True) else None,
            "meetings": lambda: self._run_meetings(cfg, today),
            "tasks": lambda: self._run_tasks(cfg, deadline_cfg, today),
        }

        fn = runners.get(section)
        if fn:
            try:
                result = fn()
                if isinstance(result, list):
                    items.extend([{"type": section, "text": r} for r in result if r])
                elif result:
                    items.append({"type": section, "text": result})
            except Exception as e:
                log.warning("%s failed: %s", section, e)

        return self._result(items=items) if items else self._result(items=[{"text": f"No {section} items."}])

    def _run_meetings(self, cfg: dict, today: str) -> list[str]:
        results = []
        gm = self._check_group_meeting(cfg, today)
        if gm:
            results.append(gm)
        rg = self._check_reading_group(cfg, today)
        if rg:
            results.append(rg)
        return results

    def _run_tasks(self, cfg: dict, deadline_cfg: dict, today: str) -> list[str]:
        results = []
        dl = self._check_deadlines(deadline_cfg, today)
        if dl:
            results.append(dl)
        tasks = self._get_tasks()
        if tasks:
            results.append(tasks)
        habits = cfg.get("daily_habits", [])
        if habits:
            habit_text = "\n".join(f"  - [ ] {h}" for h in habits)
            results.append(f"**If time allows:**\n{habit_text}")
        return results

    def run(self) -> ModuleResult:
        cfg = self.config.get("assistant", {})
        cal_cfg = self.config.get("calendar", {})
        deadline_cfg = self.config.get("deadlines", {})
        today = datetime.now().strftime("%Y-%m-%d %A")
        items: list[dict] = []

        # 1. Calendar
        if cal_cfg.get("enabled", True):
            try:
                cal = self._check_calendar(today)
                if cal:
                    items.append({"type": "calendar", "text": cal})
            except Exception as e:
                log.warning("Calendar check failed: %s", e)

        # 2. Email
        if cfg.get("email_enabled", True):
            try:
                emails = self._check_email(cfg)
                if emails:
                    items.append({"type": "email", "text": emails})
            except Exception as e:
                log.warning("Email check failed: %s", e)

        # 3. Group meeting schedule
        try:
            gm = self._check_group_meeting(cfg, today)
            if gm:
                items.append({"type": "group_meeting", "text": gm})
        except Exception as e:
            log.warning("Group meeting check failed: %s", e)

        # 4. Reading group schedule
        try:
            rg = self._check_reading_group(cfg, today)
            if rg:
                items.append({"type": "reading_group", "text": rg})
        except Exception as e:
            log.warning("Reading group check failed: %s", e)

        # 5. Deadlines
        try:
            dl = self._check_deadlines(deadline_cfg, today)
            if dl:
                items.append({"type": "deadlines", "text": dl})
        except Exception as e:
            log.warning("Deadline check failed: %s", e)

        # 6. Tasks
        try:
            tasks = self._get_tasks()
            if tasks:
                items.append({"type": "tasks", "text": tasks})
        except Exception as e:
            log.warning("Task loading failed: %s", e)

        # 7. Daily habits (only if schedule not packed)
        habits = cfg.get("daily_habits", [])
        if habits:
            habit_text = "\n".join(f"  - [ ] {h}" for h in habits)
            items.append({"type": "habits", "text": f"**If time allows:**\n{habit_text}"})

        if not items:
            return self._result(items=[{"text": "No assistant items today."}])

        return self._result(items=items)

    def _check_calendar(self, today: str) -> str | None:
        """Check today's calendar via Claude CLI (Google Calendar MCP)."""
        log.info("  Checking calendar...")
        response = ask_claude_sync(
            f"List all my calendar events for today ({today}). "
            f"For each event show: time, title, and location/link if any. "
            f"Format as a compact list. If no events, say 'No events today.'",
            model_override="sonnet",
        )
        if not response or "error" in response.lower()[:50]:
            return None
        return f"**🗓️ Calendar:**\n{response}"

    def _check_email(self, cfg: dict) -> str | None:
        """Check recent important emails via Claude CLI (Gmail MCP)."""
        log.info("  Checking email...")
        max_items = cfg.get("email_max_items", 5)
        response = ask_claude_sync(
            f"Check my Gmail inbox for the most important/actionable emails from the last 24 hours. "
            f"Show the top {max_items} emails: sender, subject, and a one-line summary of what action is needed (if any). "
            f"Skip newsletters and automated notifications unless they're urgent. "
            f"Format as a compact list.",
            model_override="sonnet",
        )
        if not response or "error" in response.lower()[:50]:
            return None
        return f"**📧 Email:**\n{response}"

    def _check_group_meeting(self, cfg: dict, today: str) -> str | None:
        """Check group meeting schedule from Google Sheet."""
        sheet_url = cfg.get("group_meeting_sheet", "")
        name = cfg.get("researcher_name_in_sheets", "tianrun")
        if not sheet_url:
            return None

        log.info("  Checking group meeting sheet...")
        response = ask_claude_sync(
            f"Fetch this Google Sheet: {sheet_url}\n\n"
            f"This is a group meeting schedule. Find:\n"
            f"1. When is {name}'s next turn to present? (date and topic if listed)\n"
            f"2. Who is presenting this week?\n"
            f"3. Any upcoming presentations by {name} in the next 2 weeks?\n\n"
            f"Today is {today}. Be concise.",
            model_override="sonnet",
        )
        if not response or "error" in response.lower()[:50]:
            return None
        return f"**🎤 Group Meeting:**\n{response}"

    def _check_reading_group(self, cfg: dict, today: str) -> str | None:
        """Check reading group schedule from Google Sheet."""
        sheet_url = cfg.get("reading_group_sheet", "")
        name = cfg.get("researcher_name_in_sheets", "tianrun")
        if not sheet_url:
            return None

        log.info("  Checking reading group sheet...")
        response = ask_claude_sync(
            f"Fetch this Google Sheet: {sheet_url}\n\n"
            f"This is a reading group schedule where members share papers. Find:\n"
            f"1. When is {name}'s next turn to present a paper?\n"
            f"2. Who is presenting this week and what paper?\n"
            f"3. Any upcoming slots for {name} in the next 2 weeks?\n\n"
            f"Today is {today}. Be concise.",
            model_override="sonnet",
        )
        if not response or "error" in response.lower()[:50]:
            return None
        return f"**📖 Reading Group:**\n{response}"

    def _check_deadlines(self, cfg: dict, today: str) -> str | None:
        """Check configured deadlines."""
        entries = cfg.get("entries", [])
        if not entries:
            return None

        warn_days = cfg.get("warn_days_before", [7, 3, 1, 0])
        today_dt = datetime.now()
        warnings = []

        for entry in entries:
            try:
                deadline_dt = datetime.strptime(entry["date"], "%Y-%m-%d")
                days_left = (deadline_dt - today_dt).days
                if days_left < 0:
                    warnings.append(f"🔴 **OVERDUE**: {entry['name']} (was {entry['date']})")
                elif days_left in warn_days or days_left <= max(warn_days):
                    emoji = "🔴" if days_left <= 1 else "🟡" if days_left <= 3 else "🟢"
                    warnings.append(f"{emoji} {entry['name']} — {days_left} days left ({entry['date']})")
            except (KeyError, ValueError):
                continue

        if not warnings:
            return None
        return "**⏰ Deadlines:**\n" + "\n".join(f"  - {w}" for w in warnings)

    def _get_tasks(self) -> str | None:
        """Load tasks from local JSON file."""
        tasks_path = Path(self.data_dir) / "tasks.json"
        tasks = load_json(tasks_path, default=[])

        active = [t for t in tasks if t.get("status") != "done"]
        if not active:
            return None

        lines = []
        # Overdue / urgent first
        for t in sorted(active, key=lambda x: x.get("priority", 99)):
            status = "⬜" if t.get("status") == "todo" else "🔄"
            priority = t.get("priority", "")
            pri_str = f" [P{priority}]" if priority else ""
            due = f" (due: {t['due']})" if t.get("due") else ""
            lines.append(f"  - {status}{pri_str} {t['title']}{due}")

        return "**✅ Tasks:**\n" + "\n".join(lines)

