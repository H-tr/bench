"""Claude Code CLI wrapper — all LLM calls go through here."""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger("bench.claude")


def ask_claude(prompt: str, max_tokens: int | None = None) -> str:
    """Send a prompt to Claude via the local Claude Code CLI.

    Returns the response text. Raises RuntimeError on failure.
    """
    cmd = ["claude", "-p", prompt]
    if max_tokens:
        cmd.extend(["--max-tokens", str(max_tokens)])

    log.debug("Calling Claude CLI (%d char prompt)", len(prompt))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed (rc={result.returncode}): {result.stderr.strip()}")

    return result.stdout.strip()
