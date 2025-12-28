---
name: pydantic-models
description: |
  Pydantic v2 model patterns for validation and serialization. Use when creating data models,
  parsing external data, working with configs, or when user mentions "Pydantic", "validation",
  "model_validate", "BaseModel", or "Field".
allowed-tools: Read, Grep, Glob
---

# Pydantic v2 Model Patterns

Apply Pydantic v2 idioms for robust data validation in this codebase.

## Instructions

1. **Use model_validate for parsing**, not manual constructors:
   ```python
   from pydantic import BaseModel, Field

   class User(BaseModel):
       name: str
       email: str
       age: int = Field(ge=0)

   # Correct
   user = User.model_validate(raw_dict)
   user = User.model_validate(sdk_object, from_attributes=True)

   # Avoid - no custom from_sdk() methods
   ```

2. **Use field validators for normalization**:
   ```python
   from pydantic import BaseModel, field_validator

   class Config(BaseModel):
       path: Path

       @field_validator("path", mode="before")
       @classmethod
       def expand_path(cls, v: str | Path) -> Path:
           if isinstance(v, str):
               return Path(v).expanduser().resolve()
           return v.expanduser().resolve()
   ```

3. **Discriminated unions with Field(discriminator=...)**:
   ```python
   from typing import Annotated, Literal
   from pydantic import BaseModel, Field

   class HttpTransport(BaseModel):
       transport: Literal["http"] = "http"
       url: str

   class StdioTransport(BaseModel):
       transport: Literal["stdio"] = "stdio"
       command: list[str]

   Transport = Annotated[
       HttpTransport | StdioTransport,
       Field(discriminator="transport")
   ]
   ```

4. **Use ConfigDict for model configuration**:
   ```python
   from pydantic import BaseModel, ConfigDict

   class Response(BaseModel):
       model_config = ConfigDict(
           extra="forbid",           # No unknown fields
           from_attributes=True,     # Parse from objects
           populate_by_name=True,    # Allow field aliases
       )
   ```

5. **Use validation_alias for external data**:
   ```python
   class Tool(BaseModel):
       input_schema: dict = Field(
           default_factory=dict,
           validation_alias="inputSchema"  # camelCase from API
       )
   ```

6. **Prefer Field() over default_factory for defaults**:
   ```python
   class Result(BaseModel):
       errors: list[str] = Field(default_factory=list)
       metadata: dict[str, str] = Field(default_factory=dict)
   ```

## Reference Files

- `vibe/core/config.py` - Complex config models with providers, MCP
- `vibe/core/tools/base.py` - BaseToolConfig, ToolPermission
- `vibe/core/skills/models.py` - SkillMetadata, SkillInfo

## Examples

- "Create a config model" → Use ConfigDict, field validators
- "Parse API response" → model_validate with from_attributes
- "Handle multiple formats" → Discriminated union

## Guardrails

- Read-only analysis unless user confirms writes
- Keep validation logic inside validators, not call sites
- No inline type ignores - fix types properly
