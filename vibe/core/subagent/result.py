"""Sub-agent result models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SubAgentResult(BaseModel):
    """Result returned from a sub-agent execution."""

    success: bool = Field(description="Whether the sub-agent completed successfully")
    result: str = Field(description="The final result or answer from the sub-agent")
    summary: str = Field(description="Brief summary of actions taken")
    files_read: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    tokens_used: int = Field(default=0, description="Total tokens consumed")
    steps_taken: int = Field(default=0, description="Number of steps/turns taken")
    errors: list[str] = Field(default_factory=list)

    def to_display_string(self) -> str:
        """Format result for display to parent agent."""
        parts = [self.result]

        if self.files_modified:
            parts.append(f"\nFiles modified: {', '.join(self.files_modified)}")

        if self.errors:
            parts.append(f"\nErrors encountered: {'; '.join(self.errors)}")

        return "\n".join(parts)
