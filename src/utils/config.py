"""Config loader — reads config.yaml and .env."""

from __future__ import annotations

from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def load_config(config_path: Path | None = None) -> dict:
    """Load config.yaml and .env, return merged config dict."""
    path = config_path or CONFIG_PATH

    # Load .env if present
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    with open(path) as f:
        config = yaml.safe_load(f)

    return config
