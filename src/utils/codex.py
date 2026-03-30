"""OpenAI Codex CLI wrapper — alternative LLM backend for survey generation."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from tempfile import NamedTemporaryFile

log = logging.getLogger("bench.codex")

MAX_RETRIES = 5
MAX_TIMEOUT_RETRIES = 2
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

    The prompt is written to a temporary file and piped via stdin to avoid
    OS E2BIG errors when the prompt exceeds the argument list size limit.

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

    timeout_count = 0
    for attempt in range(1, MAX_RETRIES + 1):
        output_path: Path | None = None
        try:
            # Write prompt to a temp file to avoid E2BIG on large prompts
            with NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as prompt_file:
                prompt_file.write(full_prompt)
                prompt_path = Path(prompt_file.name)

            with NamedTemporaryFile(mode="r+", suffix=".txt") as output_file:
                output_path = Path(output_file.name)
                run_cmd = [*cmd, "--output-last-message", output_file.name]
                result = subprocess.run(
                    run_cmd,
                    input=full_prompt,
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
            timeout_count += 1
            log.warning("Codex CLI timed out (attempt %d/%d, %ds)", attempt, MAX_RETRIES, timeout)
            if timeout_count >= MAX_TIMEOUT_RETRIES:
                raise RuntimeError(
                    f"Codex CLI timed out {timeout_count} times ({timeout}s each) — aborting"
                )
            log.info("Waiting %d minutes before retry...", RETRY_WAIT // 60)
            time.sleep(RETRY_WAIT)
            continue
        finally:
            # Clean up prompt temp file
            try:
                prompt_path.unlink(missing_ok=True)
            except NameError:
                pass

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
