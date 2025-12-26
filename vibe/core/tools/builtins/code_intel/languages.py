from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


@dataclass
class LanguageConfig:
    """Configuration for a programming language's AST analysis."""

    name: str
    extensions: list[str]
    # Node types that define symbols (functions, classes, variables)
    definition_types: list[str]
    # Node types that reference symbols
    reference_types: list[str]
    # Node types for import statements
    import_types: list[str]
    # Tree-sitter language module name
    ts_module: str
    # Field names used to extract symbol names from definition nodes
    name_fields: list[str] = field(default_factory=lambda: ["name"])
    # Node types that contain function/method bodies
    body_types: list[str] = field(default_factory=list)


LANGUAGE_CONFIG: dict[str, LanguageConfig] = {
    "python": LanguageConfig(
        name="python",
        extensions=[".py", ".pyi"],
        definition_types=[
            "function_definition",
            "class_definition",
            "assignment",
            "augmented_assignment",
            "global_statement",
            "decorated_definition",
        ],
        reference_types=[
            "identifier",
            "attribute",
            "call",
        ],
        import_types=[
            "import_statement",
            "import_from_statement",
        ],
        ts_module="tree_sitter_python",
        name_fields=["name", "left"],
        body_types=["block", "module"],
    ),
    "javascript": LanguageConfig(
        name="javascript",
        extensions=[".js", ".jsx", ".mjs", ".cjs"],
        definition_types=[
            "function_declaration",
            "class_declaration",
            "variable_declarator",
            "method_definition",
            "arrow_function",
            "function_expression",
        ],
        reference_types=[
            "identifier",
            "member_expression",
            "call_expression",
        ],
        import_types=[
            "import_statement",
            "import_clause",
            "call_expression",  # for require()
        ],
        ts_module="tree_sitter_javascript",
        name_fields=["name", "id"],
        body_types=["statement_block", "program"],
    ),
    "typescript": LanguageConfig(
        name="typescript",
        extensions=[".ts", ".tsx", ".mts", ".cts"],
        definition_types=[
            "function_declaration",
            "class_declaration",
            "variable_declarator",
            "method_definition",
            "arrow_function",
            "function_expression",
            "interface_declaration",
            "type_alias_declaration",
            "enum_declaration",
        ],
        reference_types=[
            "identifier",
            "member_expression",
            "call_expression",
            "type_identifier",
        ],
        import_types=[
            "import_statement",
            "import_clause",
        ],
        ts_module="tree_sitter_typescript",
        name_fields=["name", "id"],
        body_types=["statement_block", "program"],
    ),
    "go": LanguageConfig(
        name="go",
        extensions=[".go"],
        definition_types=[
            "function_declaration",
            "method_declaration",
            "type_declaration",
            "type_spec",
            "var_declaration",
            "const_declaration",
            "short_var_declaration",
        ],
        reference_types=[
            "identifier",
            "selector_expression",
            "call_expression",
            "type_identifier",
        ],
        import_types=[
            "import_declaration",
            "import_spec",
        ],
        ts_module="tree_sitter_go",
        name_fields=["name"],
        body_types=["block", "source_file"],
    ),
    "rust": LanguageConfig(
        name="rust",
        extensions=[".rs"],
        definition_types=[
            "function_item",
            "struct_item",
            "enum_item",
            "trait_item",
            "impl_item",
            "type_item",
            "const_item",
            "static_item",
            "let_declaration",
            "mod_item",
            "macro_definition",
        ],
        reference_types=[
            "identifier",
            "field_expression",
            "call_expression",
            "type_identifier",
            "scoped_identifier",
        ],
        import_types=[
            "use_declaration",
            "extern_crate_declaration",
        ],
        ts_module="tree_sitter_rust",
        name_fields=["name"],
        body_types=["block", "source_file"],
    ),
    "java": LanguageConfig(
        name="java",
        extensions=[".java"],
        definition_types=[
            "class_declaration",
            "interface_declaration",
            "method_declaration",
            "field_declaration",
            "enum_declaration",
            "annotation_type_declaration",
            "constructor_declaration",
        ],
        reference_types=[
            "identifier",
            "method_invocation",
            "field_access",
            "type_identifier",
        ],
        import_types=[
            "import_declaration",
        ],
        ts_module="tree_sitter_java",
        name_fields=["name"],
        body_types=["block", "class_body", "program"],
    ),
    "c": LanguageConfig(
        name="c",
        extensions=[".c", ".h"],
        definition_types=[
            "function_definition",
            "declaration",
            "struct_specifier",
            "enum_specifier",
            "union_specifier",
            "type_definition",
        ],
        reference_types=[
            "identifier",
            "field_expression",
            "call_expression",
            "type_identifier",
        ],
        import_types=[
            "preproc_include",
        ],
        ts_module="tree_sitter_c",
        name_fields=["name", "declarator"],
        body_types=["compound_statement", "translation_unit"],
    ),
    "cpp": LanguageConfig(
        name="cpp",
        extensions=[".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".h++"],
        definition_types=[
            "function_definition",
            "class_specifier",
            "struct_specifier",
            "declaration",
            "template_declaration",
            "namespace_definition",
            "enum_specifier",
            "using_declaration",
        ],
        reference_types=[
            "identifier",
            "field_expression",
            "call_expression",
            "type_identifier",
            "qualified_identifier",
        ],
        import_types=[
            "preproc_include",
            "using_declaration",
        ],
        ts_module="tree_sitter_cpp",
        name_fields=["name", "declarator"],
        body_types=["compound_statement", "translation_unit", "declaration_list"],
    ),
    "ruby": LanguageConfig(
        name="ruby",
        extensions=[".rb", ".rake", ".gemspec"],
        definition_types=[
            "method",
            "singleton_method",
            "class",
            "module",
            "assignment",
        ],
        reference_types=[
            "identifier",
            "call",
            "method_call",
            "constant",
        ],
        import_types=[
            "call",  # require, require_relative are method calls
        ],
        ts_module="tree_sitter_ruby",
        name_fields=["name"],
        body_types=["body_statement", "program"],
    ),
    "php": LanguageConfig(
        name="php",
        extensions=[".php", ".phtml"],
        definition_types=[
            "function_definition",
            "class_declaration",
            "method_declaration",
            "interface_declaration",
            "trait_declaration",
            "enum_declaration",
            "property_declaration",
        ],
        reference_types=[
            "name",
            "member_access_expression",
            "function_call_expression",
            "class_constant_access_expression",
        ],
        import_types=[
            "namespace_use_declaration",
            "require_expression",
            "require_once_expression",
            "include_expression",
            "include_once_expression",
        ],
        ts_module="tree_sitter_php",
        name_fields=["name"],
        body_types=["compound_statement", "program"],
    ),
    "csharp": LanguageConfig(
        name="csharp",
        extensions=[".cs"],
        definition_types=[
            "class_declaration",
            "interface_declaration",
            "struct_declaration",
            "method_declaration",
            "field_declaration",
            "property_declaration",
            "enum_declaration",
            "delegate_declaration",
            "constructor_declaration",
            "record_declaration",
        ],
        reference_types=[
            "identifier",
            "member_access_expression",
            "invocation_expression",
            "generic_name",
        ],
        import_types=[
            "using_directive",
        ],
        ts_module="tree_sitter_c_sharp",
        name_fields=["name"],
        body_types=["block", "compilation_unit"],
    ),
    "kotlin": LanguageConfig(
        name="kotlin",
        extensions=[".kt", ".kts"],
        definition_types=[
            "class_declaration",
            "function_declaration",
            "property_declaration",
            "object_declaration",
            "type_alias",
            "companion_object",
        ],
        reference_types=[
            "simple_identifier",
            "call_expression",
            "navigation_expression",
            "type_identifier",
        ],
        import_types=[
            "import_header",
        ],
        ts_module="tree_sitter_kotlin",
        name_fields=["name"],
        body_types=["function_body", "class_body", "source_file"],
    ),
}

# Extension to language mapping for quick lookup
EXTENSION_TO_LANGUAGE: dict[str, str] = {}
for lang_name, config in LANGUAGE_CONFIG.items():
    for ext in config.extensions:
        EXTENSION_TO_LANGUAGE[ext] = lang_name


@lru_cache(maxsize=1000)
def _get_language_for_suffix(suffix: str) -> str | None:
    """Cached language lookup by file suffix."""
    return EXTENSION_TO_LANGUAGE.get(suffix.lower())


def get_language_for_file(file_path: str | Path) -> str | None:
    """Detect language from file extension.

    Args:
        file_path: Path to the file

    Returns:
        Language name if recognized, None otherwise

    Note:
        Uses LRU cache internally to avoid repeated Path/suffix operations
        for files with the same extension.
    """
    path = Path(file_path) if isinstance(file_path, str) else file_path
    return _get_language_for_suffix(path.suffix)


def get_supported_extensions() -> list[str]:
    """Get list of all supported file extensions."""
    return list(EXTENSION_TO_LANGUAGE.keys())


def is_supported_file(file_path: str | Path) -> bool:
    """Check if a file is supported for code analysis."""
    return get_language_for_file(file_path) is not None
