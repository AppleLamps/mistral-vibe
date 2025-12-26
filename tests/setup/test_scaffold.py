from __future__ import annotations

from pathlib import Path

from vibe.setup.scaffold import ScaffoldError, scaffold_skill, scaffold_tool


def test_scaffold_tool_creates_files(tmp_path: Path) -> None:
    tool_path, prompt_path = scaffold_tool(tmp_path, name="demo_tool")

    assert tool_path.exists()
    assert prompt_path.exists()
    content = tool_path.read_text(encoding="utf-8")
    assert "class DemoTool" in content
    prompt = prompt_path.read_text(encoding="utf-8")
    assert "demo_tool" in prompt


def test_scaffold_skill_creates_file(tmp_path: Path) -> None:
    skill_file = scaffold_skill(tmp_path, name="demo-skill")

    assert skill_file.exists()
    text = skill_file.read_text(encoding="utf-8")
    assert "name: demo-skill" in text


def test_scaffold_tool_duplicate_fails(tmp_path: Path) -> None:
    scaffold_tool(tmp_path, name="dup")
    try:
        scaffold_tool(tmp_path, name="dup")
    except ScaffoldError:
        return
    assert False, "Expected ScaffoldError for duplicate tool"
