"""OpenAI Codex CLI wrapper — alternative LLM backend for survey generation."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from tempfile import NamedTemporaryFile

log = logging.getLogger("bench.codex")

MAX_RETRIES = 5
RETRY_WAIT = 60  # 1 minute

_model: str | None = None


def _get_model() -> str | None:
    """Load codex model from config (cached after first call)."""
    global _model
    if _model is None:
        try:
            from src.utils.config import load_config
            _model = load_config().get("codex", {}).get("model", "")
        except Exception:
            _model = ""
    return _model or None


def ask_codex_sync(
    prompt: str,
    system_prompt: str | None = None,
    model_override: str | None = None,
    timeout: int = 300,
) -> str:
    """Send a prompt to OpenAI Codex via the local Codex CLI.

    The codex CLI (npm install -g @openai/codex) is invoked via `codex exec`
    in full-auto mode so it runs non-interactively and returns the final text.

    Args:
        system_prompt: Prepended to the prompt as context (codex has no
                       dedicated --system-prompt flag).
        model_override: Use a specific model (e.g. "o4-mini", "o3") instead
                        of the config default.
        timeout: Subprocess timeout in seconds (default 300).

    Retries up to 5 times with 1-minute waits on failure.
    """
    model = model_override or _get_model()

    # Merge system prompt into the user prompt if provided
    full_prompt = prompt
    if system_prompt:
        full_prompt = f"{system_prompt}\n\n{prompt}"

    cmd = ["codex", "exec", "--full-auto", "--color", "never"]
    if model:
        cmd.extend(["--model", model])

    log.debug("Calling Codex CLI (%d char prompt, model=%s)", len(full_prompt), model or "default")

    for attempt in range(1, MAX_RETRIES + 1):
        output_path: Path | None = None
        try:
            with NamedTemporaryFile(mode="r+", suffix=".txt") as output_file:
                output_path = Path(output_file.name)
                run_cmd = [*cmd, "--output-last-message", output_file.name, full_prompt]
                result = subprocess.run(
                    run_cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )

                if result.returncode == 0:
                    output_file.seek(0)
                    final_output = output_file.read().strip()
                    if final_output:
                        return final_output
                    return result.stdout.strip()
        except subprocess.TimeoutExpired:
            log.warning("Codex CLI timed out (attempt %d/%d, %ds)", attempt, MAX_RETRIES, timeout)
            if attempt < MAX_RETRIES:
                log.info("Waiting %d minutes before retry...", RETRY_WAIT // 60)
                time.sleep(RETRY_WAIT)
            continue

        stderr = result.stderr.strip()
        if output_path is not None and output_path.exists():
            partial_output = output_path.read_text().strip()
            if partial_output:
                stderr = f"{stderr}\nPartial output:\n{partial_output}".strip()
        log.warning(
            "Codex CLI failed (attempt %d/%d, rc=%d): %s",
            attempt, MAX_RETRIES, result.returncode, stderr[:200],
        )

        if attempt < MAX_RETRIES:
            log.info("Waiting %d minutes before retry...", RETRY_WAIT // 60)
            time.sleep(RETRY_WAIT)

    raise RuntimeError(
        f"Codex CLI failed after {MAX_RETRIES} attempts"
    )
