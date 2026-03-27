"""Base module interface. All Bench modules inherit from this."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModuleResult:
    """Output from a single module run."""

    module_name: str
    section_title: str
    items: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors and not self.skipped


class BaseModule(ABC):
    """Every Bench module implements this interface."""

    name: str = "base"
    section_title: str = "BASE"

    def __init__(self, config: dict, data_dir: str) -> None:
        self.config = config
        self.data_dir = data_dir
        self.log = logging.getLogger(f"bench.{self.name}")

    @abstractmethod
    def run(self) -> ModuleResult:
        """Execute the module and return results for the digest."""
        ...

    def _result(self, **kwargs) -> ModuleResult:
        return ModuleResult(module_name=self.name, section_title=self.section_title, **kwargs)

    def _skip(self, reason: str) -> ModuleResult:
        return ModuleResult(
            module_name=self.name,
            section_title=self.section_title,
            skipped=True,
            skip_reason=reason,
        )

    def _error(self, msg: str) -> ModuleResult:
        self.log.error(msg)
        return ModuleResult(
            module_name=self.name,
            section_title=self.section_title,
            errors=[msg],
        )
