"""Typed failures of the read-only tools. They replace raw driver errors, and `reason` is a code
for logs and fallbacks, never shown to Luis."""

from typing import Literal

type ToolErrorReason = Literal["not_found", "database", "timeout"]


class ToolError(Exception):
    def __init__(self, reason: ToolErrorReason) -> None:
        super().__init__(reason)
        self.reason: ToolErrorReason = reason


class ToolTimeout(ToolError):
    """The query did not finish in time (it becomes `data_timeout` in the agent)."""

    def __init__(self) -> None:
        super().__init__("timeout")
