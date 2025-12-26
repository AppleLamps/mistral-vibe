from __future__ import annotations

from pathlib import Path

import pytest

from vibe.core.tools.base import ToolError
from vibe.core.tools.builtins.read_file import (
    ReadFile,
    ReadFileArgs,
    ReadFileState,
    ReadFileToolConfig,
)


@pytest.mark.asyncio
async def test_read_file_blocks_outside_workdir(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("secret")

    tool = ReadFile(config=ReadFileToolConfig(workdir=workdir), state=ReadFileState())

    with pytest.raises(ToolError) as exc_info:
        await tool.run(ReadFileArgs(path=str(outside_file)))

    assert "Cannot read outside project directory" in str(exc_info.value)
