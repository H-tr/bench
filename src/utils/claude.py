"""Claude Code CLI wrapper — all LLM calls go through here."""

from __future__ import annotations

import logging
import subprocess
import time

log = logging.getLogger("bench.claude")

MAX_RETRIES = 5
RETRY_WAIT = 600  # 10 minutes

_model: str | None = None


def _get_model() -> str | None:
    """Load model from config (cached after first call)."""
    global _model
    if _model is None:
        try:
            from src.utils.config import load_config
            _model = load_config().get("claude", {}).get("model", "")
        except Exception:
            _model = ""
    return _model or None


def ask_claude_sync(
    prompt: str,
    system_prompt: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """Send a prompt to Claude via the local Claude Code CLI.

    Retries up to 5 times with 10-minute waits on failure.
    Returns the response text. Raises RuntimeError after all retries exhausted.
    """
    cmd = ["claude", "-p", prompt]
    model = _get_model()
    if model:
        cmd.extend(["--model", model])
    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])
    if max_tokens:
        cmd.extend(["--max-tokens", str(max_tokens)])

    log.debug("Calling Claude CLI (%d char prompt)", len(prompt))

    for attempt in range(1, MAX_RETRIES + 1):
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode == 0:
            return result.stdout.strip()

        stderr = result.stderr.strip()
        log.warning(
            "Claude CLI failed (attempt %d/%d, rc=%d): %s",
            attempt, MAX_RETRIES, result.returncode, stderr[:200],
        )

        if attempt < MAX_RETRIES:
            log.info("Waiting %d minutes before retry...", RETRY_WAIT // 60)
            time.sleep(RETRY_WAIT)

    raise RuntimeError(
        f"Claude CLI failed after {MAX_RETRIES} attempts (rc={result.returncode}): {stderr[:200]}"
    )
