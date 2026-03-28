"""Claude Code CLI wrapper — all LLM calls go through here."""

from __future__ import annotations

import logging
import subprocess
import time

log = logging.getLogger("bench.claude")

MAX_RETRIES = 5
RETRY_WAIT = 60  # 1 minute

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
    model_override: str | None = None,
    timeout: int = 300,
    allowed_tools: list[str] | None = None,
) -> str:
    """Send a prompt to Claude via the local Claude Code CLI.

    Args:
        model_override: Use a specific model instead of the config default.
        timeout: Subprocess timeout in seconds (default 300).
        allowed_tools: List of tools to allow (e.g. ["WebFetch", "Read"]).

    Retries up to 5 times with 1-minute waits on failure.
    """
    cmd = ["claude", "-p", prompt]
    model = model_override or _get_model()
    if model:
        cmd.extend(["--model", model])
    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])
    if max_tokens:
        cmd.extend(["--max-tokens", str(max_tokens)])
    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])

    log.debug("Calling Claude CLI (%d char prompt, model=%s)", len(prompt), model or "default")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            log.warning("Claude CLI timed out (attempt %d/%d, %ds)", attempt, MAX_RETRIES, timeout)
            if attempt < MAX_RETRIES:
                log.info("Waiting %d minutes before retry...", RETRY_WAIT // 60)
                time.sleep(RETRY_WAIT)
            continue

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
        f"Claude CLI failed after {MAX_RETRIES} attempts"
    )
