from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from vibe.core.tools.builtins.code_intel.languages import (
    LANGUAGE_CONFIG,
    get_language_for_file,
)
from vibe.core.tools.builtins.code_intel.parser import CodeParser, get_parser

if TYPE_CHECKING:
    from tree_sitter import Node, Tree


def walk_tree(node: Node) -> Generator[Node, None, None]:
    """Walk all nodes in a tree depth-first.

    Uses an iterative approach with a stack to avoid the overhead
    of creating a new generator frame for every node.

    Args:
        node: Starting node

    Yields:
        Each node in depth-first order
    """
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        # Add children in reverse order so leftmost child is processed first
        stack.extend(reversed(current.children))


def find_nodes_by_type(
    tree: Tree, node_types: list[str]
) -> Generator[Node, None, None]:
    """Find all nodes of specified types in a tree.

    Args:
        tree: Tree-sitter Tree
        node_types: List of node type strings to match

    Yields:
        Matching nodes
    """
    type_set = set(node_types)
    for node in walk_tree(tree.root_node):
        if node.type in type_set:
            yield node


def get_node_name(node: Node, language: str, source: bytes) -> str | None:
    """Extract the name of a definition node.

    Args:
        node: AST node representing a definition
        language: Language name
        source: Source code bytes

    Returns:
        The symbol name, or None if not found
    """
    config = LANGUAGE_CONFIG.get(language)
    if not config:
        return None

    # Try each name field
    for field_name in config.name_fields:
        name_node = node.child_by_field_name(field_name)
        if name_node:
            return source[name_node.start_byte : name_node.end_byte].decode(
                "utf-8", errors="replace"
            )

    # For some node types, the first identifier child is the name
    if node.type in ["function_definition", "class_definition"]:
        for child in node.children:
            if child.type == "identifier":
                return source[child.start_byte : child.end_byte].decode(
                    "utf-8", errors="replace"
                )

    return None


def find_definitions(
    tree: Tree, language: str, source: bytes, symbol_name: str | None = None
) -> list[dict]:
    """Find symbol definitions in a tree.

    Args:
        tree: Tree-sitter Tree
        language: Language name
        source: Source code bytes
        symbol_name: Optional symbol name to filter by

    Returns:
        List of definition info dicts with keys:
        - name: Symbol name
        - kind: Definition type (function, class, etc.)
        - line: Line number (1-indexed)
        - column: Column number (0-indexed)
        - node: The AST node
    """
    config = LANGUAGE_CONFIG.get(language)
    if not config:
        return []

    results = []
    for node in find_nodes_by_type(tree, config.definition_types):
        name = get_node_name(node, language, source)
        if name is None:
            continue

        if symbol_name is not None and name != symbol_name:
            continue

        # Map node type to human-readable kind
        kind = _node_type_to_kind(node.type)

        results.append({
            "name": name,
            "kind": kind,
            "line": node.start_point[0] + 1,
            "column": node.start_point[1],
            "end_line": node.end_point[0] + 1,
            "end_column": node.end_point[1],
            "node": node,
        })

    return results


def find_references(
    tree: Tree, language: str, source: bytes, symbol_name: str
) -> list[dict]:
    """Find references to a symbol in a tree.

    Args:
        tree: Tree-sitter Tree
        language: Language name
        source: Source code bytes
        symbol_name: Symbol name to search for

    Returns:
        List of reference info dicts with keys:
        - name: Symbol name
        - line: Line number (1-indexed)
        - column: Column number (0-indexed)
        - node: The AST node
        - is_definition: Whether this is a definition site
    """
    config = LANGUAGE_CONFIG.get(language)
    if not config:
        return []

    # Get all definitions first to mark definition sites
    definitions = find_definitions(tree, language, source, symbol_name)
    def_locations = {(d["line"], d["column"]) for d in definitions}

    results = []

    # Search for all identifiers matching the symbol name
    for node in walk_tree(tree.root_node):
        if node.type not in ("identifier", "type_identifier"):
            continue

        node_text = source[node.start_byte : node.end_byte].decode(
            "utf-8", errors="replace"
        )
        if node_text != symbol_name:
            continue

        line = node.start_point[0] + 1
        column = node.start_point[1]
        is_def = (line, column) in def_locations

        results.append({
            "name": symbol_name,
            "line": line,
            "column": column,
            "node": node,
            "is_definition": is_def,
        })

    return results


def find_imports(tree: Tree, language: str, source: bytes) -> list[dict]:
    """Find all import statements in a tree.

    Args:
        tree: Tree-sitter Tree
        language: Language name
        source: Source code bytes

    Returns:
        List of import info dicts with keys:
        - module: Imported module name
        - names: List of imported names (for 'from X import a, b')
        - line: Line number (1-indexed)
        - is_relative: Whether this is a relative import
        - node: The AST node
    """
    config = LANGUAGE_CONFIG.get(language)
    if not config:
        return []

    results = []
    for node in find_nodes_by_type(tree, config.import_types):
        import_info = _parse_import_node(node, language, source)
        if import_info:
            results.append(import_info)

    return results


def _parse_import_node(node: Node, language: str, source: bytes) -> dict | None:
    """Parse an import node into structured data."""
    parsers = {
        "python": _parse_python_import,
        "javascript": _parse_js_import,
        "typescript": _parse_js_import,
        "go": _parse_go_import,
        "rust": _parse_rust_import,
        "java": _parse_java_import,
        "c": _parse_c_import,
        "cpp": _parse_cpp_import,
        "ruby": _parse_ruby_import,
        "php": _parse_php_import,
        "csharp": _parse_csharp_import,
        "kotlin": _parse_kotlin_import,
    }
    parser_func = parsers.get(language)
    if parser_func:
        return parser_func(node, source)
    return None


def _parse_python_import(node: Node, source: bytes) -> dict | None:
    """Parse a Python import statement."""
    if node.type == "import_statement":
        # import foo, bar
        modules = []
        for child in node.children:
            if child.type in ("dotted_name", "aliased_import"):
                module_node = (
                    child.child_by_field_name("name") or child
                    if child.type == "aliased_import"
                    else child
                )
                modules.append(
                    source[module_node.start_byte : module_node.end_byte].decode(
                        "utf-8", errors="replace"
                    )
                )

        return {
            "module": modules[0] if modules else "",
            "names": [],
            "line": node.start_point[0] + 1,
            "is_relative": False,
            "node": node,
        }

    elif node.type == "import_from_statement":
        # from foo import bar, baz
        module_node = node.child_by_field_name("module_name")
        module = ""
        is_relative = False

        if module_node:
            module = source[module_node.start_byte : module_node.end_byte].decode(
                "utf-8", errors="replace"
            )

        # Check for relative import (leading dots)
        for child in node.children:
            if child.type == "relative_import":
                is_relative = True
                module_child = child.child_by_field_name("module_name")
                if module_child:
                    module = source[
                        module_child.start_byte : module_child.end_byte
                    ].decode("utf-8", errors="replace")
                break

        # Get imported names
        names = []
        for child in node.children:
            if child.type == "import_prefix":
                is_relative = True
            elif child.type in ("dotted_name", "aliased_import"):
                if child.type == "aliased_import":
                    name_node = child.child_by_field_name("name")
                    if name_node:
                        names.append(
                            source[name_node.start_byte : name_node.end_byte].decode(
                                "utf-8", errors="replace"
                            )
                        )
                else:
                    names.append(
                        source[child.start_byte : child.end_byte].decode(
                            "utf-8", errors="replace"
                        )
                    )

        return {
            "module": module,
            "names": names,
            "line": node.start_point[0] + 1,
            "is_relative": is_relative,
            "node": node,
        }

    return None


def _parse_js_import(node: Node, source: bytes) -> dict | None:
    """Parse a JavaScript/TypeScript import statement."""
    if node.type != "import_statement":
        return None

    # Find the source string
    source_node = node.child_by_field_name("source")
    if not source_node:
        return None

    module = source[source_node.start_byte : source_node.end_byte].decode(
        "utf-8", errors="replace"
    )
    # Remove quotes
    module = module.strip("'\"")

    # Get imported names
    names = []
    for child in node.children:
        if child.type == "import_clause":
            for clause_child in walk_tree(child):
                if clause_child.type == "identifier":
                    names.append(
                        source[clause_child.start_byte : clause_child.end_byte].decode(
                            "utf-8", errors="replace"
                        )
                    )

    is_relative = module.startswith(".") or module.startswith("/")

    return {
        "module": module,
        "names": names,
        "line": node.start_point[0] + 1,
        "is_relative": is_relative,
        "node": node,
    }


def _parse_go_import(node: Node, source: bytes) -> dict | None:
    """Parse Go import declaration."""
    if node.type == "import_declaration":
        # Handle both single imports and import blocks
        imports = []
        for child in walk_tree(node):
            if child.type == "import_spec":
                result = _parse_go_import(child, source)
                if result:
                    imports.append(result)
        # Return the first import for consistency, or None if block is empty
        return imports[0] if imports else None

    elif node.type == "import_spec":
        # Single import spec: "package" or alias "package"
        path_node = node.child_by_field_name("path")
        if path_node:
            module = source[path_node.start_byte:path_node.end_byte].decode(
                "utf-8", errors="replace"
            )
            module = module.strip('"')

            # Get alias if present
            alias_node = node.child_by_field_name("name")
            alias = None
            if alias_node:
                alias = source[alias_node.start_byte:alias_node.end_byte].decode(
                    "utf-8", errors="replace"
                )

            return {
                "module": module,
                "names": [alias] if alias else [],
                "line": node.start_point[0] + 1,
                "is_relative": module.startswith("."),
                "node": node,
            }
    return None


def _parse_rust_import(node: Node, source: bytes) -> dict | None:
    """Parse Rust use declaration."""
    if node.type not in ("use_declaration", "extern_crate_declaration"):
        return None

    if node.type == "extern_crate_declaration":
        # extern crate foo;
        for child in node.children:
            if child.type == "identifier":
                module = source[child.start_byte:child.end_byte].decode(
                    "utf-8", errors="replace"
                )
                return {
                    "module": module,
                    "names": [],
                    "line": node.start_point[0] + 1,
                    "is_relative": False,
                    "node": node,
                }
        return None

    # use declaration: use crate::module::Item;
    for child in walk_tree(node):
        if child.type in ("scoped_identifier", "identifier", "use_wildcard"):
            module = source[child.start_byte:child.end_byte].decode(
                "utf-8", errors="replace"
            )
            # Convert :: to . for consistency
            module = module.replace("::", ".")
            is_relative = module.startswith("crate.") or module.startswith("super.") or module.startswith("self.")
            return {
                "module": module,
                "names": [],
                "line": node.start_point[0] + 1,
                "is_relative": is_relative,
                "node": node,
            }
    return None


def _parse_java_import(node: Node, source: bytes) -> dict | None:
    """Parse Java import declaration."""
    if node.type != "import_declaration":
        return None

    # Find the scoped identifier
    for child in node.children:
        if child.type == "scoped_identifier":
            module = source[child.start_byte:child.end_byte].decode(
                "utf-8", errors="replace"
            )
            # Check for wildcard imports
            is_wildcard = any(c.type == "asterisk" for c in node.children)
            return {
                "module": module,
                "names": ["*"] if is_wildcard else [module.split(".")[-1]],
                "line": node.start_point[0] + 1,
                "is_relative": False,
                "node": node,
            }
    return None


def _parse_c_import(node: Node, source: bytes) -> dict | None:
    """Parse C #include directive."""
    if node.type != "preproc_include":
        return None

    path_node = node.child_by_field_name("path")
    if path_node:
        path = source[path_node.start_byte:path_node.end_byte].decode(
            "utf-8", errors="replace"
        )
        is_system = path.startswith("<")
        path = path.strip('<>"')
        return {
            "module": path,
            "names": [],
            "line": node.start_point[0] + 1,
            "is_relative": not is_system,
            "is_system": is_system,
            "node": node,
        }
    return None


def _parse_cpp_import(node: Node, source: bytes) -> dict | None:
    """Parse C++ #include or using declaration."""
    if node.type == "preproc_include":
        return _parse_c_import(node, source)
    elif node.type == "using_declaration":
        # Handle using namespace std; or using std::cout;
        for child in walk_tree(node):
            if child.type in ("qualified_identifier", "identifier", "namespace_identifier"):
                name = source[child.start_byte:child.end_byte].decode(
                    "utf-8", errors="replace"
                )
                return {
                    "module": name.replace("::", "."),
                    "names": [name.split("::")[-1]],
                    "line": node.start_point[0] + 1,
                    "is_relative": False,
                    "node": node,
                }
    return None


def _parse_ruby_import(node: Node, source: bytes) -> dict | None:
    """Parse Ruby require/require_relative."""
    if node.type != "call":
        return None

    # Check if method is require or require_relative
    method_node = node.child_by_field_name("method")
    if not method_node:
        return None

    method_name = source[method_node.start_byte:method_node.end_byte].decode(
        "utf-8", errors="replace"
    )
    if method_name not in ("require", "require_relative", "load"):
        return None

    # Get the argument
    arguments = node.child_by_field_name("arguments")
    if arguments:
        for arg in arguments.children:
            if arg.type == "string":
                path = source[arg.start_byte:arg.end_byte].decode(
                    "utf-8", errors="replace"
                )
                # Remove quotes
                path = path.strip("'\"")
                return {
                    "module": path,
                    "names": [],
                    "line": node.start_point[0] + 1,
                    "is_relative": method_name == "require_relative",
                    "node": node,
                }
    return None


def _parse_php_import(node: Node, source: bytes) -> dict | None:
    """Parse PHP use/require statements."""
    if node.type == "namespace_use_declaration":
        for child in walk_tree(node):
            if child.type in ("qualified_name", "name"):
                name = source[child.start_byte:child.end_byte].decode(
                    "utf-8", errors="replace"
                )
                return {
                    "module": name.strip("\\"),
                    "names": [name.split("\\")[-1]],
                    "line": node.start_point[0] + 1,
                    "is_relative": False,
                    "node": node,
                }
    elif node.type in ("require_expression", "require_once_expression",
                       "include_expression", "include_once_expression"):
        for child in node.children:
            if child.type in ("string", "encapsed_string"):
                path = source[child.start_byte:child.end_byte].decode(
                    "utf-8", errors="replace"
                )
                path = path.strip("'\"")
                return {
                    "module": path,
                    "names": [],
                    "line": node.start_point[0] + 1,
                    "is_relative": path.startswith(".") or path.startswith("/"),
                    "node": node,
                }
    return None


def _parse_csharp_import(node: Node, source: bytes) -> dict | None:
    """Parse C# using directive."""
    if node.type != "using_directive":
        return None

    for child in walk_tree(node):
        if child.type in ("qualified_name", "identifier_name", "identifier"):
            name = source[child.start_byte:child.end_byte].decode(
                "utf-8", errors="replace"
            )
            return {
                "module": name,
                "names": [],
                "line": node.start_point[0] + 1,
                "is_relative": False,
                "node": node,
            }
    return None


def _parse_kotlin_import(node: Node, source: bytes) -> dict | None:
    """Parse Kotlin import header."""
    if node.type != "import_header":
        return None

    # Collect the full import path from identifier nodes
    identifiers = []
    for child in walk_tree(node):
        if child.type in ("identifier", "simple_identifier"):
            identifiers.append(
                source[child.start_byte:child.end_byte].decode(
                    "utf-8", errors="replace"
                )
            )

    if identifiers:
        module = ".".join(identifiers)
        return {
            "module": module,
            "names": [identifiers[-1]] if identifiers else [],
            "line": node.start_point[0] + 1,
            "is_relative": False,
            "node": node,
        }
    return None


def _node_type_to_kind(node_type: str) -> str:
    """Convert AST node type to human-readable kind."""
    mapping = {
        # Python
        "function_definition": "function",
        "class_definition": "class",
        "assignment": "variable",
        "augmented_assignment": "variable",
        "global_statement": "variable",
        "decorated_definition": "decorated",
        # JavaScript/TypeScript
        "function_declaration": "function",
        "async_function_declaration": "function",
        "arrow_function": "function",
        "function_expression": "function",
        "method_definition": "method",
        "class_declaration": "class",
        "variable_declarator": "variable",
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
        "enum_declaration": "enum",
        # Go
        "method_declaration": "method",
        "type_declaration": "type",
        "type_spec": "type",
        "var_declaration": "variable",
        "const_declaration": "constant",
        "short_var_declaration": "variable",
        # Rust
        "function_item": "function",
        "struct_item": "struct",
        "enum_item": "enum",
        "trait_item": "trait",
        "impl_item": "impl",
        "type_item": "type",
        "const_item": "constant",
        "static_item": "static",
        "let_declaration": "variable",
        "mod_item": "module",
        "macro_definition": "macro",
        # Java
        "field_declaration": "field",
        "annotation_type_declaration": "annotation",
        "constructor_declaration": "constructor",
        # C/C++
        "struct_specifier": "struct",
        "enum_specifier": "enum",
        "union_specifier": "union",
        "type_definition": "type",
        "declaration": "declaration",
        "class_specifier": "class",
        "template_declaration": "template",
        "namespace_definition": "namespace",
        "using_declaration": "using",
        # Ruby
        "method": "method",
        "singleton_method": "method",
        "class": "class",
        "module": "module",
        # PHP
        "method_declaration": "method",
        "interface_declaration": "interface",
        "trait_declaration": "trait",
        "property_declaration": "property",
        # C#
        "struct_declaration": "struct",
        "delegate_declaration": "delegate",
        "record_declaration": "record",
        # Kotlin
        "property_declaration": "property",
        "object_declaration": "object",
        "type_alias": "type",
        "companion_object": "companion",
    }
    return mapping.get(node_type, node_type)


@lru_cache(maxsize=100)
def _read_file_lines_cached(file_path: str) -> tuple[str, ...]:
    """Cache file contents to avoid redundant reads.

    Uses string path as key since Path objects are not hashable for lru_cache.
    Returns a tuple (immutable) for cache safety.

    Args:
        file_path: String path to the file

    Returns:
        Tuple of file lines, or empty tuple on error
    """
    try:
        return tuple(Path(file_path).read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return ()


def clear_file_cache() -> None:
    """Clear the file content cache. Useful after file modifications."""
    _read_file_lines_cached.cache_clear()


def get_context_lines(
    file_path: Path, line: int, context_before: int = 2, context_after: int = 2
) -> str:
    """Get lines of context around a given line.

    Uses caching to avoid redundant file reads when the same file is accessed
    multiple times (e.g., multiple symbol matches in the same file).

    Args:
        file_path: Path to the file
        line: Target line number (1-indexed)
        context_before: Lines to include before
        context_after: Lines to include after

    Returns:
        Context string with line numbers
    """
    # Use cached file reading - convert Path to str for hashability
    lines = _read_file_lines_cached(str(file_path.resolve()))
    if not lines:
        return ""

    start = max(0, line - 1 - context_before)
    end = min(len(lines), line + context_after)

    result = []
    for i in range(start, end):
        marker = ">" if i == line - 1 else " "
        result.append(f"{marker} {i + 1:4d} | {lines[i]}")

    return "\n".join(result)
