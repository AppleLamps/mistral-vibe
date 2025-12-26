from __future__ import annotations

import fnmatch
import os
import re
from enum import StrEnum, auto
from pathlib import Path
from typing import ClassVar, final

from pydantic import BaseModel, Field

from vibe.core.tools.base import BaseTool, BaseToolConfig, BaseToolState, ToolError
from vibe.core.tools.builtins.code_intel import get_language_for_file, get_parser
from vibe.core.tools.builtins.code_intel.ast_utils import (
    find_definitions,
    find_references,
    get_context_lines,
)
from vibe.core.tools.builtins.code_intel.languages import is_supported_file
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolCallEvent, ToolResultEvent


class SymbolOp(StrEnum):
    """Symbol search operations."""

    DEFINITION = auto()
    REFERENCES = auto()
    ALL = auto()


class SymbolSearchArgs(BaseModel):
    """Arguments for symbol search."""

    symbol: str = Field(description="Symbol name to search for")
    operation: SymbolOp = Field(
        default=SymbolOp.ALL,
        description="Search operation: 'definition', 'references', or 'all'",
    )
    scope: str = Field(
        default="project",
        description="Search scope: 'project', 'file:<path>', or 'directory:<path>'",
    )
    language: str | None = Field(
        default=None, description="Language filter (auto-detected if not specified)"
    )
    max_results: int = Field(
        default=100, description="Maximum number of results to return"
    )


class SymbolMatch(BaseModel):
    """A single symbol match."""

    file: str
    line: int
    column: int
    kind: str = Field(description="Symbol kind: function, class, variable, etc.")
    context: str = Field(description="Surrounding code context")
    is_definition: bool


class SymbolSearchResult(BaseModel):
    """Result of symbol search."""

    symbol: str
    matches: list[SymbolMatch]
    total_count: int
    truncated: bool = False


class SymbolSearchConfig(BaseToolConfig):
    """Configuration for symbol search tool."""

    max_files_to_scan: int = Field(
        default=5000, description="Maximum files to scan in a search"
    )
    context_lines: int = Field(
        default=2, description="Lines of context to include around matches"
    )
    exclude_patterns: list[str] = Field(
        default_factory=lambda: [
            "**/node_modules/**",
            "**/.git/**",
            "**/venv/**",
            "**/.venv/**",
            "**/__pycache__/**",
            "**/dist/**",
            "**/build/**",
        ],
        description="Glob patterns to exclude from search",
    )


class SymbolSearchState(BaseToolState):
    """State for symbol search tool."""

    recent_searches: list[str] = Field(default_factory=list)


class SymbolSearch(
    BaseTool[SymbolSearchArgs, SymbolSearchResult, SymbolSearchConfig, SymbolSearchState],
    ToolUIData[SymbolSearchArgs, SymbolSearchResult],
):
    """Search for symbol definitions and references across the codebase."""

    description: ClassVar[str] = (
        "Find symbol definitions and references using AST analysis. "
        "Supports Python, JavaScript, and TypeScript. "
        "Use operation='definition' to find where a symbol is defined, "
        "'references' to find all usages, or 'all' for both."
    )

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, SymbolSearchArgs):
            return ToolCallDisplay(summary="symbol_search")

        args = event.args
        op_str = args.operation.value if args.operation else "all"
        return ToolCallDisplay(
            summary=f"Searching for '{args.symbol}' ({op_str})",
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, SymbolSearchResult):
            return ToolResultDisplay(
                success=False, message=event.error or "Search failed"
            )

        result = event.result
        msg = f"Found {result.total_count} match(es) for '{result.symbol}'"
        if result.truncated:
            msg += " (truncated)"

        return ToolResultDisplay(success=True, message=msg)

    @classmethod
    def get_status_text(cls) -> str:
        return "Searching symbols"

    @final
    async def run(self, args: SymbolSearchArgs) -> SymbolSearchResult:
        """Execute symbol search."""
        parser = get_parser()

        if not parser.is_available():
            raise ToolError(
                "tree-sitter is not available. "
                "Install tree-sitter and language modules to use symbol search."
            )

        # Parse scope
        files_to_search = self._get_files_to_search(args.scope, args.language)

        if not files_to_search:
            return SymbolSearchResult(
                symbol=args.symbol, matches=[], total_count=0, truncated=False
            )

        # Limit files to scan
        truncated_files = len(files_to_search) > self.config.max_files_to_scan
        if truncated_files:
            files_to_search = files_to_search[: self.config.max_files_to_scan]

        matches: list[SymbolMatch] = []
        total_found = 0

        for file_path in files_to_search:
            if len(matches) >= args.max_results:
                break

            file_matches = self._search_file(
                file_path, args.symbol, args.operation, parser
            )

            for match in file_matches:
                total_found += 1
                if len(matches) < args.max_results:
                    matches.append(match)

        # Update state
        self.state.recent_searches.append(args.symbol)
        if len(self.state.recent_searches) > 10:
            self.state.recent_searches.pop(0)

        return SymbolSearchResult(
            symbol=args.symbol,
            matches=matches,
            total_count=total_found,
            truncated=total_found > len(matches),
        )

    def _get_files_to_search(
        self, scope: str, language_filter: str | None
    ) -> list[Path]:
        """Get list of files to search based on scope."""
        project_root = self.config.effective_workdir

        if scope.startswith("file:"):
            # Single file
            file_path = Path(scope[5:])
            if not file_path.is_absolute():
                file_path = project_root / file_path

            if file_path.exists() and is_supported_file(file_path):
                return [file_path]
            return []

        elif scope.startswith("directory:"):
            # Single directory
            dir_path = Path(scope[10:])
            if not dir_path.is_absolute():
                dir_path = project_root / dir_path
            search_root = dir_path

        else:
            # Entire project
            search_root = project_root

        if not search_root.exists():
            return []

        return self._collect_files(search_root, language_filter)

    def _collect_files(
        self, root: Path, language_filter: str | None
    ) -> list[Path]:
        """Collect all supported files under a directory.

        Uses pre-compiled regex patterns for faster exclusion matching.
        This avoids O(n×m) fnmatch calls where n=files and m=patterns.
        """
        # Pre-compile exclude patterns to regex for faster matching
        # fnmatch.translate converts glob patterns to regex
        exclude_regexes = [
            re.compile(fnmatch.translate(pat)) for pat in self.config.exclude_patterns
        ]

        def is_excluded(path_str: str) -> bool:
            """Check if path matches any exclusion pattern using pre-compiled regex."""
            return any(regex.match(path_str) for regex in exclude_regexes)

        files = []

        for dirpath, dirnames, filenames in os.walk(root):
            # Filter out excluded directories using pre-compiled patterns
            dirnames[:] = [
                d
                for d in dirnames
                if not is_excluded(os.path.join(dirpath, d))
            ]

            for filename in filenames:
                file_path = Path(dirpath) / filename

                # Check if supported
                if not is_supported_file(file_path):
                    continue

                # Apply language filter
                if language_filter:
                    file_lang = get_language_for_file(file_path)
                    if file_lang != language_filter:
                        continue

                # Check exclude patterns using pre-compiled regex
                full_path = str(file_path)
                if is_excluded(full_path):
                    continue

                files.append(file_path)

        return files

    def _search_file(
        self,
        file_path: Path,
        symbol: str,
        operation: SymbolOp,
        parser: object,  # CodeParser
    ) -> list[SymbolMatch]:
        """Search for symbol in a single file.

        Optimized to read the file only once - the source bytes are used for
        both parsing (via parse_bytes) and subsequent analysis.
        """
        from vibe.core.tools.builtins.code_intel.parser import CodeParser

        if not isinstance(parser, CodeParser):
            return []

        language = get_language_for_file(file_path)
        if language is None:
            return []

        # Read file content once - used for both parsing and analysis
        try:
            source = file_path.read_bytes()
        except OSError:
            return []

        # Parse using the already-read bytes (avoids duplicate file read)
        tree = parser.parse_bytes(source, language)
        if tree is None:
            return []

        matches: list[SymbolMatch] = []
        rel_path = str(file_path.relative_to(self.config.effective_workdir))

        # Find definitions
        if operation in (SymbolOp.DEFINITION, SymbolOp.ALL):
            definitions = find_definitions(tree, language, source, symbol)
            for defn in definitions:
                context = get_context_lines(
                    file_path, defn["line"], self.config.context_lines
                )
                matches.append(
                    SymbolMatch(
                        file=rel_path,
                        line=defn["line"],
                        column=defn["column"],
                        kind=defn["kind"],
                        context=context,
                        is_definition=True,
                    )
                )

        # Find references
        if operation in (SymbolOp.REFERENCES, SymbolOp.ALL):
            references = find_references(tree, language, source, symbol)
            for ref in references:
                # Skip if we already added this as a definition
                if operation == SymbolOp.ALL and ref["is_definition"]:
                    continue

                context = get_context_lines(
                    file_path, ref["line"], self.config.context_lines
                )
                matches.append(
                    SymbolMatch(
                        file=rel_path,
                        line=ref["line"],
                        column=ref["column"],
                        kind="reference",
                        context=context,
                        is_definition=False,
                    )
                )

        return matches
