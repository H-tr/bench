"""Claude Code CLI wrapper — all LLM calls go through here."""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger("bench.claude")


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

    Returns the response text. Raises RuntimeError on failure.
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
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed (rc={result.returncode}): {result.stderr.strip()}")

    return result.stdout.strip()
