"""Claude Code CLI wrapper — all LLM calls go through here."""

from __future__ import annotations

import logging
import subprocess
import time

log = logging.getLogger("bench.claude")

MAX_RETRIES = 5
MAX_TIMEOUT_RETRIES = 2  # Fewer retries for timeouts (retrying the same heavy call rarely helps)
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
    cmd = ["claude", "-p", "-"]
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

    timeout_count = 0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            timeout_count += 1
            log.warning("Claude CLI timed out (attempt %d/%d, %ds)", attempt, MAX_RETRIES, timeout)
            if timeout_count >= MAX_TIMEOUT_RETRIES:
                raise RuntimeError(
                    f"Claude CLI timed out {timeout_count} times ({timeout}s each) — aborting"
                )
            log.info("Waiting %d minutes before retry...", RETRY_WAIT // 60)
            time.sleep(RETRY_WAIT)
            continue

        if result.returncode == 0:
            if result.stderr.strip():
                log.debug("Claude CLI stderr (rc=0): %s", result.stderr.strip()[:300])
            output = result.stdout.strip()
            if not output:
                log.warning("Claude CLI returned success but empty stdout (attempt %d/%d)", attempt, MAX_RETRIES)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_WAIT)
                    continue
            return output

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
