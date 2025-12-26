from __future__ import annotations

"""Code intelligence infrastructure for AST-based code analysis."""

from vibe.core.tools.builtins.code_intel.docstrings import (
    DocstringExtractor,
    extract_docstring,
)
from vibe.core.tools.builtins.code_intel.import_resolver import (
    ImportResolver,
    resolve_import,
)
from vibe.core.tools.builtins.code_intel.languages import (
    LANGUAGE_CONFIG,
    LanguageConfig,
    get_language_for_file,
)
from vibe.core.tools.builtins.code_intel.parser import CodeParser, get_parser
from vibe.core.tools.builtins.code_intel.scope import (
    Scope,
    ScopeAnalyzer,
    ScopeType,
    Symbol,
    SymbolKind,
    get_scope_info,
)

__all__ = [
    # Languages
    "LANGUAGE_CONFIG",
    "LanguageConfig",
    "get_language_for_file",
    # Parser
    "CodeParser",
    "get_parser",
    # Scope tracking
    "Scope",
    "ScopeAnalyzer",
    "ScopeType",
    "Symbol",
    "SymbolKind",
    "get_scope_info",
    # Import resolution
    "ImportResolver",
    "resolve_import",
    # Docstrings
    "DocstringExtractor",
    "extract_docstring",
]
