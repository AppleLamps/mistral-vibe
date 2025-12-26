from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import TYPE_CHECKING

from vibe.core.tools.builtins.code_intel.languages import (
    LANGUAGE_CONFIG,
    get_language_for_file,
)

if TYPE_CHECKING:
    from tree_sitter import Language, Node, Parser, Tree


class TreeSitterNotAvailable(Exception):
    """Raised when tree-sitter is not available."""


class CodeParser:
    """Manages tree-sitter parsers with caching for performance."""

    def __init__(self) -> None:
        self._parsers: dict[str, Parser] = {}
        self._languages: dict[str, Language] = {}
        self._ast_cache: dict[str, tuple[float, Tree]] = {}
        self._tree_sitter_available: bool | None = None

    def is_available(self) -> bool:
        """Check if tree-sitter is available."""
        if self._tree_sitter_available is None:
            try:
                import tree_sitter  # noqa: F401

                self._tree_sitter_available = True
            except ImportError:
                self._tree_sitter_available = False
        return self._tree_sitter_available

    def _get_language(self, lang_name: str) -> Language:
        """Get or load a tree-sitter language."""
        if lang_name in self._languages:
            return self._languages[lang_name]

        if lang_name not in LANGUAGE_CONFIG:
            raise ValueError(f"Unsupported language: {lang_name}")

        config = LANGUAGE_CONFIG[lang_name]

        try:
            # Import the language module dynamically
            module = importlib.import_module(config.ts_module)

            # Handle languages with special module structures
            if lang_name == "typescript":
                # TypeScript has language_typescript() function
                lang = module.language_typescript()
            elif lang_name == "php":
                # PHP module has language_php() function
                lang = module.language_php()
            elif lang_name == "csharp":
                # C# module may have language() or language_c_sharp()
                if hasattr(module, "language_c_sharp"):
                    lang = module.language_c_sharp()
                else:
                    lang = module.language()
            else:
                # Most modules have a language() function
                lang = module.language()

            self._languages[lang_name] = lang
            return lang

        except ImportError as e:
            raise TreeSitterNotAvailable(
                f"tree-sitter language module not available for {lang_name}: {e}"
            ) from e
        except AttributeError as e:
            raise TreeSitterNotAvailable(
                f"Failed to get language from {config.ts_module}: {e}"
            ) from e

    def _get_parser(self, lang_name: str) -> Parser:
        """Get or create a parser for the given language."""
        if lang_name in self._parsers:
            return self._parsers[lang_name]

        if not self.is_available():
            raise TreeSitterNotAvailable("tree-sitter is not installed")

        from tree_sitter import Parser

        language = self._get_language(lang_name)
        parser = Parser(language)
        self._parsers[lang_name] = parser
        return parser

    def parse_file(self, file_path: str | Path) -> Tree | None:
        """Parse a file and return its AST.

        Uses caching based on file modification time.

        Args:
            file_path: Path to the file to parse

        Returns:
            Tree-sitter Tree object, or None if parsing fails
        """
        path = Path(file_path).resolve()
        path_str = str(path)

        # Detect language
        lang_name = get_language_for_file(path)
        if lang_name is None:
            return None

        # Check cache
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None

        if path_str in self._ast_cache:
            cached_mtime, cached_tree = self._ast_cache[path_str]
            if cached_mtime == mtime:
                return cached_tree

        # Parse file
        try:
            parser = self._get_parser(lang_name)
            content = path.read_bytes()
            tree = parser.parse(content)

            # Cache result
            self._ast_cache[path_str] = (mtime, tree)
            return tree

        except (OSError, TreeSitterNotAvailable):
            return None

    def parse_string(self, content: str, language: str) -> Tree | None:
        """Parse a string of code.

        Args:
            content: Source code string
            language: Language name

        Returns:
            Tree-sitter Tree object, or None if parsing fails
        """
        try:
            parser = self._get_parser(language)
            return parser.parse(content.encode("utf-8"))
        except (TreeSitterNotAvailable, ValueError):
            return None

    def clear_cache(self) -> None:
        """Clear the AST cache."""
        self._ast_cache.clear()

    def get_node_text(self, node: Node, source: bytes) -> str:
        """Extract the text of a node from source bytes."""
        return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


# Global parser instance for shared use
_global_parser: CodeParser | None = None


def get_parser() -> CodeParser:
    """Get the global parser instance."""
    global _global_parser
    if _global_parser is None:
        _global_parser = CodeParser()
    return _global_parser
