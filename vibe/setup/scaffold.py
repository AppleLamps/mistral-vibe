from __future__ import annotations

import datetime as _dt
from pathlib import Path
from textwrap import dedent


class ScaffoldError(RuntimeError):
    pass


def _unique_slug(kind: str) -> str:
    timestamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{kind}_{timestamp}"


def scaffold_tool(base_dir: Path, name: str | None = None) -> tuple[Path, Path]:
    base_dir = base_dir.expanduser().resolve()
    tools_dir = base_dir / ".vibe" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)

    slug = name or _unique_slug("tool")
    module_name = slug.lower().replace("-", "_")
    class_name = "".join(part.capitalize() for part in module_name.split("_")) or "Tool"

    tool_path = tools_dir / f"{module_name}.py"
    prompt_path = tools_dir / "prompts" / f"{module_name}.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)

    if tool_path.exists():
        raise ScaffoldError(f"Tool file already exists: {tool_path}")

    tool_template = dedent(
        f"""
        from __future__ import annotations

        from pydantic import BaseModel, Field

        from vibe.core.tools.base import BaseTool


        class Args(BaseModel):
            example: str = Field(description="Example argument")


        class Result(BaseModel):
            echo: str


        class Config(BaseModel):
            pass


        class {class_name}(BaseTool[Args, Result, Config, BaseModel]):
            description = "TODO: describe your tool"

            async def run(self, args: Args) -> Result:
                return Result(echo=args.example)
        """
    ).strip()

    prompt_template = dedent(
        f"""
        You can use the tool `{module_name}` when you need to echo the provided text.
        """
    ).strip()

    tool_path.write_text(tool_template + "\n", encoding="utf-8")
    prompt_path.write_text(prompt_template + "\n", encoding="utf-8")
    return tool_path, prompt_path


def scaffold_skill(base_dir: Path, name: str | None = None) -> Path:
    base_dir = base_dir.expanduser().resolve()
    skills_dir = base_dir / ".vibe" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    slug = name or _unique_slug("skill")
    skill_dir = skills_dir / slug
    skill_dir.mkdir(parents=False, exist_ok=True)

    skill_file = skill_dir / "SKILL.md"
    if skill_file.exists():
        raise ScaffoldError(f"Skill file already exists: {skill_file}")

    skill_template = dedent(
        f"""
        ---
        name: {slug}
        description: Briefly describe what this skill does.
        triggers:
          - keywords: []
        ---

        # {slug}

        Describe the skill behavior here.
        """
    ).strip()

    skill_file.write_text(skill_template + "\n", encoding="utf-8")
    return skill_file
