from __future__ import annotations

import os
from collections import defaultdict, deque
from enum import StrEnum, auto
from pathlib import Path
from typing import ClassVar, final

from pydantic import BaseModel, Field

from vibe.core.tools.base import BaseTool, BaseToolConfig, BaseToolState, ToolError
from vibe.core.tools.builtins.code_intel import get_language_for_file, get_parser
from vibe.core.tools.builtins.code_intel.ast_utils import find_imports
from vibe.core.tools.builtins.code_intel.languages import is_supported_file
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolCallEvent, ToolResultEvent


class DepOp(StrEnum):
    """Dependency analysis operations."""

    IMPORTS = auto()  # What does this file import?
    DEPENDENTS = auto()  # What files import this?
    GRAPH = auto()  # Full dependency graph


class DependencyArgs(BaseModel):
    """Arguments for dependency analysis."""

    operation: DepOp = Field(
        default=DepOp.IMPORTS,
        description="Operation: 'imports', 'dependents', or 'graph'",
    )
    target: str = Field(
        description="File path or module name to analyze"
    )
    depth: int = Field(
        default=1,
        description="How many levels deep to analyze (for graph operation)",
    )


class ImportInfo(BaseModel):
    """Information about a single import."""

    source_file: str
    imported_module: str
    imported_names: list[str] = Field(default_factory=list)
    line: int
    is_relative: bool


class DependencyResult(BaseModel):
    """Result of dependency analysis."""

    target: str
    operation: str
    imports: list[ImportInfo] = Field(
        default_factory=list, description="What the target imports"
    )
    dependents: list[str] = Field(
        default_factory=list, description="Files that import the target"
    )
    graph: dict[str, list[str]] = Field(
        default_factory=dict, description="Full dependency graph"
    )


class DependencyConfig(BaseToolConfig):
    """Configuration for dependency analyzer tool."""

    max_files_to_scan: int = Field(
        default=5000, description="Maximum files to scan"
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
        description="Glob patterns to exclude",
    )


class DependencyState(BaseToolState):
    """State for dependency analyzer tool."""

    pass


class DependencyAnalyzer(
    BaseTool[DependencyArgs, DependencyResult, DependencyConfig, DependencyState],
    ToolUIData[DependencyArgs, DependencyResult],
):
    """Analyze import/dependency relationships between files."""

    description: ClassVar[str] = (
        "Analyze dependencies between source files. "
        "Use operation='imports' to see what a file imports, "
        "'dependents' to see what imports a file, or "
        "'graph' for a full dependency graph."
    )

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, DependencyArgs):
            return ToolCallDisplay(summary="dependency_analyzer")

        args = event.args
        return ToolCallDisplay(
            summary=f"Analyzing {args.operation.value} for '{args.target}'",
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, DependencyResult):
            return ToolResultDisplay(
                success=False, message=event.error or "Analysis failed"
            )

        result = event.result
        if result.operation == "imports":
            msg = f"Found {len(result.imports)} import(s)"
        elif result.operation == "dependents":
            msg = f"Found {len(result.dependents)} dependent(s)"
        else:
            msg = f"Built graph with {len(result.graph)} node(s)"

        return ToolResultDisplay(success=True, message=msg)

    @classmethod
    def get_status_text(cls) -> str:
        return "Analyzing dependencies"

    @final
    async def run(self, args: DependencyArgs) -> DependencyResult:
        """Execute dependency analysis."""
        parser = get_parser()

        if not parser.is_available():
            raise ToolError(
                "tree-sitter is not available. "
                "Install tree-sitter and language modules to use dependency analysis."
            )

        project_root = self.config.effective_workdir

        # Resolve target path
        target_path = Path(args.target)
        if not target_path.is_absolute():
            target_path = project_root / target_path

        if args.operation == DepOp.IMPORTS:
            return self._analyze_imports(target_path, parser)

        elif args.operation == DepOp.DEPENDENTS:
            return self._find_dependents(target_path, project_root, parser)

        elif args.operation == DepOp.GRAPH:
            return self._build_graph(target_path, project_root, parser, args.depth)

        raise ToolError(f"Unknown operation: {args.operation}")

    def _analyze_imports(
        self, target_path: Path, parser: object
    ) -> DependencyResult:
        """Analyze what a file imports."""
        from vibe.core.tools.builtins.code_intel.parser import CodeParser

        if not isinstance(parser, CodeParser):
            raise ToolError("Invalid parser")

        if not target_path.exists():
            raise ToolError(f"File not found: {target_path}")

        tree = parser.parse_file(target_path)
        if tree is None:
            raise ToolError(f"Failed to parse: {target_path}")

        language = get_language_for_file(target_path)
        if language is None:
            raise ToolError(f"Unsupported language for: {target_path}")

        try:
            source = target_path.read_bytes()
        except OSError as e:
            raise ToolError(f"Failed to read file: {e}") from e

        imports_data = find_imports(tree, language, source)

        imports = [
            ImportInfo(
                source_file=str(target_path.relative_to(self.config.effective_workdir)),
                imported_module=imp["module"],
                imported_names=imp["names"],
                line=imp["line"],
                is_relative=imp["is_relative"],
            )
            for imp in imports_data
        ]

        return DependencyResult(
            target=str(target_path.relative_to(self.config.effective_workdir)),
            operation="imports",
            imports=imports,
        )

    def _find_dependents(
        self, target_path: Path, project_root: Path, parser: object
    ) -> DependencyResult:
        """Find files that import the target."""
        from vibe.core.tools.builtins.code_intel.parser import CodeParser

        if not isinstance(parser, CodeParser):
            raise ToolError("Invalid parser")

        # Normalize target for matching
        target_rel = str(target_path.relative_to(project_root))
        target_module = self._path_to_module(target_rel)

        files = self._collect_files(project_root)
        dependents = []

        for file_path in files:
            tree = parser.parse_file(file_path)
            if tree is None:
                continue

            language = get_language_for_file(file_path)
            if language is None:
                continue

            try:
                source = file_path.read_bytes()
            except OSError:
                continue

            imports_data = find_imports(tree, language, source)

            for imp in imports_data:
                if self._import_matches_target(
                    imp["module"], imp["is_relative"], file_path, target_path, target_module
                ):
                    dependents.append(
                        str(file_path.relative_to(self.config.effective_workdir))
                    )
                    break

        return DependencyResult(
            target=target_rel,
            operation="dependents",
            dependents=dependents,
        )

    def _build_graph(
        self, start_path: Path, project_root: Path, parser: object, depth: int
    ) -> DependencyResult:
        """Build a dependency graph starting from a file."""
        from vibe.core.tools.builtins.code_intel.parser import CodeParser

        if not isinstance(parser, CodeParser):
            raise ToolError("Invalid parser")

        graph: dict[str, list[str]] = defaultdict(list)
        visited: set[str] = set()
        queue: deque[tuple[Path, int]] = deque([(start_path, 0)])

        while queue:
            current_path, current_depth = queue.popleft()

            if current_depth > depth:
                continue

            try:
                rel_path = str(current_path.relative_to(project_root))
            except ValueError:
                continue

            if rel_path in visited:
                continue

            visited.add(rel_path)

            tree = parser.parse_file(current_path)
            if tree is None:
                continue

            language = get_language_for_file(current_path)
            if language is None:
                continue

            try:
                source = current_path.read_bytes()
            except OSError:
                continue

            imports_data = find_imports(tree, language, source)

            for imp in imports_data:
                resolved = self._resolve_import(
                    imp["module"], imp["is_relative"], current_path, project_root
                )
                if resolved:
                    graph[rel_path].append(resolved)
                    resolved_path = project_root / resolved
                    if resolved_path.exists() and resolved not in visited:
                        queue.append((resolved_path, current_depth + 1))

        return DependencyResult(
            target=str(start_path.relative_to(project_root)),
            operation="graph",
            graph=dict(graph),
        )

    def _collect_files(self, root: Path) -> list[Path]:
        """Collect all supported files under a directory."""
        import fnmatch
        import re

        # Precompile exclude patterns for efficiency
        compiled_patterns = [
            re.compile(fnmatch.translate(pat))
            for pat in self.config.exclude_patterns
        ]

        def is_excluded(path_str: str) -> bool:
            return any(p.match(path_str) for p in compiled_patterns)

        files = []

        for dirpath, dirnames, filenames in os.walk(root):
            # Filter out excluded directories
            dirnames[:] = [
                d
                for d in dirnames
                if not is_excluded(os.path.join(dirpath, d))
            ]

            for filename in filenames:
                file_path = Path(dirpath) / filename

                if not is_supported_file(file_path):
                    continue

                if is_excluded(str(file_path)):
                    continue

                files.append(file_path)

                if len(files) >= self.config.max_files_to_scan:
                    return files

        return files

    def _path_to_module(self, path: str) -> str:
        """Convert a file path to a module name."""
        # Remove extension
        if path.endswith(".py"):
            path = path[:-3]
        elif path.endswith(".ts") or path.endswith(".js"):
            path = path[:-3]
        elif path.endswith(".tsx") or path.endswith(".jsx"):
            path = path[:-4]

        # Convert path separators to dots
        return path.replace("/", ".").replace("\\", ".")

    def _import_matches_target(
        self,
        import_module: str,
        is_relative: bool,
        source_file: Path,
        target_path: Path,
        target_module: str,
    ) -> bool:
        """Check if an import matches the target file."""
        # Direct module match
        if import_module == target_module:
            return True

        # Check if import is a prefix of target (package import)
        if target_module.startswith(import_module + "."):
            return True

        # For relative imports, resolve and compare
        if is_relative:
            resolved = self._resolve_import(
                import_module, is_relative, source_file, self.config.effective_workdir
            )
            if resolved:
                try:
                    target_rel = str(target_path.relative_to(self.config.effective_workdir))
                    return resolved == target_rel
                except ValueError:
                    pass

        return False

    def _resolve_import(
        self, module: str, is_relative: bool, source_file: Path, project_root: Path
    ) -> str | None:
        """Resolve an import to a file path."""
        if is_relative:
            # Relative import - resolve relative to source file
            source_dir = source_file.parent
            module_path = module.replace(".", "/")

            candidates = [
                source_dir / f"{module_path}.py",
                source_dir / module_path / "__init__.py",
                source_dir / f"{module_path}.ts",
                source_dir / f"{module_path}.js",
            ]
        else:
            # Absolute import - resolve from project root
            module_path = module.replace(".", "/")

            candidates = [
                project_root / f"{module_path}.py",
                project_root / module_path / "__init__.py",
                project_root / f"{module_path}.ts",
                project_root / f"{module_path}.js",
                project_root / f"{module_path}.tsx",
                project_root / f"{module_path}.jsx",
            ]

        for candidate in candidates:
            if candidate.exists():
                try:
                    return str(candidate.relative_to(project_root))
                except ValueError:
                    pass

        return None
