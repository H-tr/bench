"""Claude Code SDK wrapper — all LLM calls go through here."""

from __future__ import annotations

import logging

import anyio
from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock

log = logging.getLogger("bench.claude")


async def ask_claude_async(
    prompt: str,
    system_prompt: str | None = None,
    max_turns: int = 1,
) -> str:
    """Send a prompt to Claude via the Claude Agent SDK.

    Returns the full response text. Raises RuntimeError on failure.
    """
    options = ClaudeAgentOptions(max_turns=max_turns)
    if system_prompt:
        options.system_prompt = system_prompt

    log.debug("Calling Claude SDK (%d char prompt)", len(prompt))

    parts: list[str] = []
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    parts.append(block.text)

    result = "\n".join(parts).strip()
    if not result:
        raise RuntimeError("Claude returned empty response")
    return result


def ask_claude(
    prompt: str,
    system_prompt: str | None = None,
    max_turns: int = 1,
) -> str:
    """Synchronous wrapper around ask_claude_async."""
    return anyio.from_thread.run(
        lambda: ask_claude_async(prompt, system_prompt, max_turns)
    ) if anyio.get_current_task() else anyio.run(
        lambda: ask_claude_async(prompt, system_prompt, max_turns)
    )


def ask_claude_sync(
    prompt: str,
    system_prompt: str | None = None,
    max_turns: int = 1,
) -> str:
    """Always-synchronous version — safe to call from non-async code."""
    return anyio.run(ask_claude_async, prompt, system_prompt, max_turns)
