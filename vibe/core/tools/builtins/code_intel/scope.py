from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tree_sitter import Node, Tree


class ScopeType(StrEnum):
    """Types of scopes in code."""

    GLOBAL = auto()  # Module/file level
    CLASS = auto()  # Class body
    FUNCTION = auto()  # Function body
    BLOCK = auto()  # Block scope (if/for/while)
    NAMESPACE = auto()  # Namespace/package scope


class SymbolKind(StrEnum):
    """Kinds of symbols."""

    FUNCTION = auto()
    METHOD = auto()
    CLASS = auto()
    VARIABLE = auto()
    CONSTANT = auto()
    PARAMETER = auto()
    PROPERTY = auto()
    FIELD = auto()
    TYPE = auto()
    INTERFACE = auto()
    ENUM = auto()
    MODULE = auto()
    NAMESPACE = auto()
    STRUCT = auto()
    TRAIT = auto()


@dataclass
class Scope:
    """Represents a scope in code."""

    type: ScopeType
    name: str | None  # Name of the scope (function/class name)
    start_line: int
    end_line: int
    parent: Scope | None = None
    children: list[Scope] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    node: Node | None = field(default=None, repr=False)


@dataclass
class Symbol:
    """Enhanced symbol with scope information."""

    name: str
    kind: SymbolKind
    line: int
    column: int
    end_line: int
    end_column: int
    scope: Scope | None = None
    is_local: bool = False
    is_parameter: bool = False
    is_class_member: bool = False
    is_instance_variable: bool = False
    is_exported: bool = False
    docstring: str | None = None
    node: Node | None = field(default=None, repr=False)

    @property
    def is_global(self) -> bool:
        """Check if symbol is at global/module scope."""
        return self.scope is not None and self.scope.type == ScopeType.GLOBAL

    @property
    def qualified_name(self) -> str:
        """Get fully qualified name including scope."""
        parts = []
        current_scope = self.scope
        while current_scope:
            if current_scope.name:
                parts.append(current_scope.name)
            current_scope = current_scope.parent
        parts.reverse()
        parts.append(self.name)
        return ".".join(parts)


# Node types that create new scopes, per language
SCOPE_CREATORS: dict[str, dict[str, ScopeType]] = {
    "python": {
        "module": ScopeType.GLOBAL,
        "class_definition": ScopeType.CLASS,
        "function_definition": ScopeType.FUNCTION,
    },
    "javascript": {
        "program": ScopeType.GLOBAL,
        "class_declaration": ScopeType.CLASS,
        "class_body": ScopeType.CLASS,
        "function_declaration": ScopeType.FUNCTION,
        "arrow_function": ScopeType.FUNCTION,
        "method_definition": ScopeType.FUNCTION,
        "statement_block": ScopeType.BLOCK,
    },
    "typescript": {
        "program": ScopeType.GLOBAL,
        "class_declaration": ScopeType.CLASS,
        "function_declaration": ScopeType.FUNCTION,
        "arrow_function": ScopeType.FUNCTION,
        "method_definition": ScopeType.FUNCTION,
        "statement_block": ScopeType.BLOCK,
        "module": ScopeType.NAMESPACE,
    },
    "go": {
        "source_file": ScopeType.GLOBAL,
        "function_declaration": ScopeType.FUNCTION,
        "method_declaration": ScopeType.FUNCTION,
        "block": ScopeType.BLOCK,
    },
    "rust": {
        "source_file": ScopeType.GLOBAL,
        "function_item": ScopeType.FUNCTION,
        "impl_item": ScopeType.CLASS,
        "struct_item": ScopeType.CLASS,
        "mod_item": ScopeType.NAMESPACE,
        "block": ScopeType.BLOCK,
    },
    "java": {
        "program": ScopeType.GLOBAL,
        "class_declaration": ScopeType.CLASS,
        "interface_declaration": ScopeType.CLASS,
        "method_declaration": ScopeType.FUNCTION,
        "constructor_declaration": ScopeType.FUNCTION,
        "block": ScopeType.BLOCK,
    },
    "c": {
        "translation_unit": ScopeType.GLOBAL,
        "function_definition": ScopeType.FUNCTION,
        "compound_statement": ScopeType.BLOCK,
    },
    "cpp": {
        "translation_unit": ScopeType.GLOBAL,
        "function_definition": ScopeType.FUNCTION,
        "class_specifier": ScopeType.CLASS,
        "struct_specifier": ScopeType.CLASS,
        "namespace_definition": ScopeType.NAMESPACE,
        "compound_statement": ScopeType.BLOCK,
    },
    "ruby": {
        "program": ScopeType.GLOBAL,
        "class": ScopeType.CLASS,
        "module": ScopeType.NAMESPACE,
        "method": ScopeType.FUNCTION,
        "singleton_method": ScopeType.FUNCTION,
    },
    "php": {
        "program": ScopeType.GLOBAL,
        "class_declaration": ScopeType.CLASS,
        "interface_declaration": ScopeType.CLASS,
        "trait_declaration": ScopeType.CLASS,
        "function_definition": ScopeType.FUNCTION,
        "method_declaration": ScopeType.FUNCTION,
        "compound_statement": ScopeType.BLOCK,
    },
    "csharp": {
        "compilation_unit": ScopeType.GLOBAL,
        "class_declaration": ScopeType.CLASS,
        "interface_declaration": ScopeType.CLASS,
        "struct_declaration": ScopeType.CLASS,
        "method_declaration": ScopeType.FUNCTION,
        "constructor_declaration": ScopeType.FUNCTION,
        "namespace_declaration": ScopeType.NAMESPACE,
        "block": ScopeType.BLOCK,
    },
    "kotlin": {
        "source_file": ScopeType.GLOBAL,
        "class_declaration": ScopeType.CLASS,
        "object_declaration": ScopeType.CLASS,
        "function_declaration": ScopeType.FUNCTION,
        "function_body": ScopeType.BLOCK,
    },
}


class ScopeAnalyzer:
    """Analyzes scope hierarchy in code."""

    def __init__(self, language: str):
        self.language = language
        self.scope_creators = SCOPE_CREATORS.get(language, {})

    def build_scope_tree(self, tree: Tree, source: bytes) -> Scope:
        """Build a scope tree from an AST.

        Args:
            tree: Tree-sitter Tree
            source: Source code bytes

        Returns:
            Root scope containing the full scope hierarchy
        """
        root = Scope(
            type=ScopeType.GLOBAL,
            name=None,
            start_line=1,
            end_line=tree.root_node.end_point[0] + 1,
            node=tree.root_node,
        )

        self._build_scopes(tree.root_node, root, source)
        return root

    def _build_scopes(self, node: Node, current_scope: Scope, source: bytes) -> None:
        """Recursively build scopes."""
        for child in node.children:
            scope_type = self.scope_creators.get(child.type)

            if scope_type:
                # Create new scope
                name = self._get_scope_name(child, source)
                new_scope = Scope(
                    type=scope_type,
                    name=name,
                    start_line=child.start_point[0] + 1,
                    end_line=child.end_point[0] + 1,
                    parent=current_scope,
                    node=child,
                )
                current_scope.children.append(new_scope)
                self._build_scopes(child, new_scope, source)
            else:
                self._build_scopes(child, current_scope, source)

    def _get_scope_name(self, node: Node, source: bytes) -> str | None:
        """Extract name from a scope-creating node."""
        name_node = node.child_by_field_name("name")
        if name_node:
            return source[name_node.start_byte : name_node.end_byte].decode(
                "utf-8", errors="replace"
            )

        # For some languages, try the first identifier child
        for child in node.children:
            if child.type == "identifier":
                return source[child.start_byte : child.end_byte].decode(
                    "utf-8", errors="replace"
                )

        return None

    def find_scope_at(self, root: Scope, line: int, column: int = 0) -> Scope:
        """Find the innermost scope containing a position.

        Args:
            root: Root scope to search from
            line: Line number (1-indexed)
            column: Column number (0-indexed)

        Returns:
            The innermost scope containing the position
        """
        best_scope = root

        def search(scope: Scope) -> None:
            nonlocal best_scope
            if scope.start_line <= line <= scope.end_line:
                best_scope = scope
                for child in scope.children:
                    search(child)

        search(root)
        return best_scope

    def classify_symbol(
        self, node: Node, scope: Scope, source: bytes
    ) -> tuple[bool, bool, bool, bool]:
        """Classify a symbol as local/parameter/class_member/instance_var.

        Args:
            node: AST node of the symbol
            scope: Scope containing the symbol
            source: Source code bytes

        Returns:
            Tuple of (is_local, is_parameter, is_class_member, is_instance_variable)
        """
        is_local = scope.type in (ScopeType.FUNCTION, ScopeType.BLOCK)
        is_parameter = self._is_parameter(node, source)
        is_class_member = scope.type == ScopeType.CLASS
        is_instance_var = self._is_instance_variable(node, source)

        return is_local, is_parameter, is_class_member, is_instance_var

    def _is_parameter(self, node: Node, source: bytes) -> bool:
        """Check if node is a function parameter."""
        parent = node.parent
        while parent:
            if parent.type in (
                "parameters",
                "formal_parameters",
                "parameter_list",
                "function_parameters",
            ):
                return True
            if parent.type in (
                "function_definition",
                "function_declaration",
                "method_declaration",
                "function_item",
            ):
                break
            parent = parent.parent
        return False

    def _is_instance_variable(self, node: Node, source: bytes) -> bool:
        """Check if node is an instance variable (self.x, this.x)."""
        if self.language == "python":
            parent = node.parent
            if parent and parent.type == "attribute":
                obj = parent.child_by_field_name("object")
                if obj:
                    obj_text = source[obj.start_byte : obj.end_byte].decode(
                        "utf-8", errors="replace"
                    )
                    return obj_text == "self"
        elif self.language in ("javascript", "typescript", "java", "csharp", "kotlin"):
            parent = node.parent
            if parent and parent.type in ("member_expression", "field_access", "member_access_expression"):
                obj = parent.child_by_field_name("object")
                if obj:
                    obj_text = source[obj.start_byte : obj.end_byte].decode(
                        "utf-8", errors="replace"
                    )
                    return obj_text == "this"
        elif self.language == "php":
            parent = node.parent
            if parent and parent.type == "member_access_expression":
                obj = parent.child_by_field_name("object")
                if obj:
                    obj_text = source[obj.start_byte : obj.end_byte].decode(
                        "utf-8", errors="replace"
                    )
                    return obj_text in ("$this", "self")
        elif self.language == "ruby":
            # Ruby instance variables start with @
            if node.type == "instance_variable":
                return True
            node_text = source[node.start_byte : node.end_byte].decode(
                "utf-8", errors="replace"
            )
            return node_text.startswith("@") and not node_text.startswith("@@")
        return False


def get_scope_info(
    tree: Tree, language: str, source: bytes, line: int, column: int = 0
) -> dict:
    """Get scope information for a position in code.

    Args:
        tree: Tree-sitter Tree
        language: Language name
        source: Source code bytes
        line: Line number (1-indexed)
        column: Column number (0-indexed)

    Returns:
        Dictionary with scope information
    """
    analyzer = ScopeAnalyzer(language)
    root = analyzer.build_scope_tree(tree, source)
    scope = analyzer.find_scope_at(root, line, column)

    # Build scope chain
    chain = []
    current = scope
    while current:
        chain.append({
            "type": current.type.value,
            "name": current.name,
            "start_line": current.start_line,
            "end_line": current.end_line,
        })
        current = current.parent

    return {
        "current_scope": scope.type.value,
        "scope_name": scope.name,
        "is_global": scope.type == ScopeType.GLOBAL,
        "is_class": scope.type == ScopeType.CLASS,
        "is_function": scope.type == ScopeType.FUNCTION,
        "scope_chain": list(reversed(chain)),
    }
