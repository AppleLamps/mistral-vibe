from __future__ import annotations

from pathlib import Path

import pytest

from vibe.core.tools.base import ToolError
from vibe.core.tools.builtins.search_replace import (
    SearchReplace,
    SearchReplaceArgs,
    SearchReplaceConfig,
    SearchReplaceState,
)


@pytest.mark.asyncio
async def test_search_replace_blocks_outside_workdir(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("old")

    tool = SearchReplace(
        config=SearchReplaceConfig(workdir=workdir), state=SearchReplaceState()
    )

    content = "\n".join(
        [
            "<<<<<<< SEARCH",
            "old",
            "=======",
            "new",
            ">>>>>>> REPLACE",
        ]
    )

    with pytest.raises(ToolError) as exc_info:
        await tool.run(SearchReplaceArgs(file_path=str(outside_file), content=content))

    assert "Cannot edit outside project directory" in str(exc_info.value)
