from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import Any


class ModeSafety(StrEnum):
    SAFE = auto()
    NEUTRAL = auto()
    DESTRUCTIVE = auto()
    YOLO = auto()


class AgentMode(StrEnum):
    DEFAULT = auto()
    AUTO_APPROVE = auto()
    PLAN = auto()
    ACCEPT_EDITS = auto()

    @property
    def display_name(self) -> str:
        return MODE_CONFIGS[self].display_name

    @property
    def description(self) -> str:
        return MODE_CONFIGS[self].description

    @property
    def config_overrides(self) -> dict[str, Any]:
        return MODE_CONFIGS[self].config_overrides

    @property
    def auto_approve(self) -> bool:
        return MODE_CONFIGS[self].auto_approve

    @property
    def safety(self) -> ModeSafety:
        return MODE_CONFIGS[self].safety

    @classmethod
    def from_string(cls, value: str) -> AgentMode | None:
        try:
            return cls(value.lower())
        except ValueError:
            return None


@dataclass(frozen=True)
class ModeConfig:
    display_name: str
    description: str
    safety: ModeSafety = ModeSafety.NEUTRAL
    auto_approve: bool = False
    config_overrides: dict[str, Any] = field(default_factory=dict)


PLAN_MODE_TOOLS = ["grep", "read_file", "todo"]
ACCEPT_EDITS_TOOLS = ["write_file", "search_replace"]

MODE_CONFIGS: dict[AgentMode, ModeConfig] = {
    AgentMode.DEFAULT: ModeConfig(
        display_name="Default",
        description="Requires approval for tool executions",
        safety=ModeSafety.NEUTRAL,
        auto_approve=False,
    ),
    AgentMode.PLAN: ModeConfig(
        display_name="Plan",
        description="Read-only mode for exploration and planning",
        safety=ModeSafety.SAFE,
        auto_approve=True,
        config_overrides={"enabled_tools": PLAN_MODE_TOOLS},
    ),
    AgentMode.ACCEPT_EDITS: ModeConfig(
        display_name="Accept Edits",
        description="Auto-approves file edits only",
        safety=ModeSafety.DESTRUCTIVE,
        auto_approve=False,
        config_overrides={
            "tools": {
                "write_file": {"permission": "always"},
                "search_replace": {"permission": "always"},
            }
        },
    ),
    AgentMode.AUTO_APPROVE: ModeConfig(
        display_name="Auto Approve",
        description="Auto-approves all tool executions",
        safety=ModeSafety.YOLO,
        auto_approve=True,
    ),
}

# Cached tuple for mode ordering - avoids creating new list on every call
_MODE_ORDER: tuple[AgentMode, ...] = (
    AgentMode.DEFAULT,
    AgentMode.PLAN,
    AgentMode.ACCEPT_EDITS,
    AgentMode.AUTO_APPROVE,
)

# O(1) index lookup for mode transitions
_MODE_INDEX: dict[AgentMode, int] = {mode: idx for idx, mode in enumerate(_MODE_ORDER)}


def get_mode_order() -> list[AgentMode]:
    """Returns the mode order. Note: Returns a list for backward compatibility."""
    return list(_MODE_ORDER)


def next_mode(current: AgentMode) -> AgentMode:
    """Get the next mode in the cycle using cached constants for performance."""
    idx = _MODE_INDEX[current]
    return _MODE_ORDER[(idx + 1) % len(_MODE_ORDER)]
