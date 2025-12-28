from __future__ import annotations

import re
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tree_sitter import Node


class DocstringExtractor:
    """Extract documentation comments for symbols."""

    # Comment patterns per language
    DOC_PATTERNS = {
        "python": {
            "docstring_types": ("expression_statement",),
            "check_child": "string",
        },
        "javascript": {
            "comment_prefix": "/**",
            "comment_types": ("comment",),
        },
        "typescript": {
            "comment_prefix": "/**",
            "comment_types": ("comment",),
        },
        "go": {
            "comment_prefix": "//",
            "comment_types": ("comment",),
        },
        "rust": {
            "comment_prefix": "///",
            "comment_types": ("line_comment",),
            "block_comment_prefix": "/**",
            "block_comment_types": ("block_comment",),
        },
        "java": {
            "comment_prefix": "/**",
            "comment_types": ("block_comment",),
        },
        "kotlin": {
            "comment_prefix": "/**",
            "comment_types": ("multiline_comment",),
        },
        "csharp": {
            "comment_prefix": "///",
            "comment_types": ("comment",),
        },
        "php": {
            "comment_prefix": "/**",
            "comment_types": ("comment",),
        },
        "ruby": {
            "comment_prefix": "#",
            "comment_types": ("comment",),
        },
        "c": {
            "comment_prefix": "/**",
            "comment_types": ("comment",),
        },
        "cpp": {
            "comment_prefix": "/**",
            "comment_types": ("comment",),
            "alt_prefix": "///",
        },
    }

    def __init__(self, language: str):
        self.language = language
        self.patterns = self.DOC_PATTERNS.get(language, {})

    def extract_docstring(self, node: Node, source: bytes) -> str | None:
        """Extract docstring/doc comment for a definition node.

        Args:
            node: AST node of the definition
            source: Source code bytes

        Returns:
            Docstring text, or None if not found
        """
        if self.language == "python":
            return self._extract_python_docstring(node, source)
        else:
            return self._extract_comment_docstring(node, source)

    def _extract_python_docstring(self, node: Node, source: bytes) -> str | None:
        """Extract Python docstring from function/class body."""
        # Find the body
        body = node.child_by_field_name("body")
        if not body:
            return None

        # First child of body should be expression_statement with string
        if body.children:
            first_stmt = body.children[0]
            if first_stmt.type == "expression_statement":
                for child in first_stmt.children:
                    if child.type == "string":
                        docstring = source[child.start_byte : child.end_byte].decode(
                            "utf-8", errors="replace"
                        )
                        return self._clean_docstring(docstring)

        return None

    def _extract_comment_docstring(self, node: Node, source: bytes) -> str | None:
        """Extract doc comment preceding a definition."""
        # Look for comments immediately before the node
        prev_sibling = node.prev_sibling
        comments = deque()

        # Scan backwards for doc comments
        while prev_sibling:
            # Check for line comments
            if prev_sibling.type in self.patterns.get("comment_types", ()):
                text = source[prev_sibling.start_byte : prev_sibling.end_byte].decode(
                    "utf-8", errors="replace"
                )

                prefix = self.patterns.get("comment_prefix", "")
                alt_prefix = self.patterns.get("alt_prefix", "")

                # Check if it's a doc comment
                stripped = text.strip()
                is_doc_comment = False

                if prefix and stripped.startswith(prefix):
                    is_doc_comment = True
                elif alt_prefix and stripped.startswith(alt_prefix):
                    is_doc_comment = True

                if is_doc_comment:
                    comments.appendleft(text)
                    prev_sibling = prev_sibling.prev_sibling
                    continue

            # Check for block comments
            if prev_sibling.type in self.patterns.get("block_comment_types", ()):
                text = source[prev_sibling.start_byte : prev_sibling.end_byte].decode(
                    "utf-8", errors="replace"
                )
                block_prefix = self.patterns.get("block_comment_prefix", "/**")
                if text.strip().startswith(block_prefix):
                    return self._clean_block_comment(text)

            # Stop if we encounter a non-comment node (but skip whitespace)
            if prev_sibling.type not in ("comment", "line_comment", "block_comment"):
                break

            prev_sibling = prev_sibling.prev_sibling

        if comments:
            return self._clean_line_comments(list(comments))

        return None

    def _clean_docstring(self, docstring: str) -> str:
        """Clean Python docstring."""
        # Remove quotes
        docstring = docstring.strip()
        if docstring.startswith('"""') or docstring.startswith("'''"):
            docstring = docstring[3:-3]
        elif docstring.startswith('"') or docstring.startswith("'"):
            docstring = docstring[1:-1]

        # Dedent
        lines = docstring.split("\n")
        if len(lines) > 1:
            # Find minimum indentation (skip first line)
            min_indent = float("inf")
            for line in lines[1:]:
                stripped = line.lstrip()
                if stripped:
                    indent = len(line) - len(stripped)
                    min_indent = min(min_indent, indent)

            if min_indent < float("inf"):
                dedented = [lines[0]]
                for line in lines[1:]:
                    if len(line) > min_indent:
                        dedented.append(line[min_indent:])
                    else:
                        dedented.append(line)
                lines = dedented

        return "\n".join(lines).strip()

    def _clean_block_comment(self, comment: str) -> str:
        """Clean JSDoc/JavaDoc style block comment."""
        # Remove /** and */
        comment = comment.strip()
        if comment.startswith("/**"):
            comment = comment[3:]
        elif comment.startswith("/*"):
            comment = comment[2:]

        if comment.endswith("*/"):
            comment = comment[:-2]

        # Remove leading * from each line
        lines = []
        for line in comment.split("\n"):
            stripped = line.strip()
            if stripped.startswith("*"):
                stripped = stripped[1:].lstrip()
            lines.append(stripped)

        return "\n".join(lines).strip()

    def _clean_line_comments(self, comments: list[str]) -> str:
        """Clean consecutive line comments."""
        lines = []
        for comment in comments:
            comment = comment.strip()

            # Remove comment prefix
            prefix = self.patterns.get("comment_prefix", "")
            alt_prefix = self.patterns.get("alt_prefix", "")

            if prefix and comment.startswith(prefix):
                # For /// or //, remove and strip
                if prefix in ("///", "//"):
                    comment = comment[len(prefix) :].strip()
                else:
                    comment = comment[len(prefix) :].lstrip()
            elif alt_prefix and comment.startswith(alt_prefix):
                comment = comment[len(alt_prefix) :].strip()

            lines.append(comment)

        return "\n".join(lines).strip()

    def parse_jsdoc_tags(self, docstring: str) -> dict[str, list[str]]:
        """Parse JSDoc-style tags from a docstring.

        Args:
            docstring: The docstring text

        Returns:
            Dictionary mapping tag names to lists of their values
        """
        tags: dict[str, list[str]] = {}
        current_tag = None
        current_content: list[str] = []

        for line in docstring.split("\n"):
            # Check for @tag
            match = re.match(r"@(\w+)\s*(.*)", line.strip())
            if match:
                # Save previous tag
                if current_tag:
                    tags.setdefault(current_tag, []).append(
                        "\n".join(current_content).strip()
                    )

                current_tag = match.group(1)
                current_content = [match.group(2)]
            elif current_tag:
                current_content.append(line.strip())

        # Save last tag
        if current_tag:
            tags.setdefault(current_tag, []).append(
                "\n".join(current_content).strip()
            )

        return tags


def extract_docstring(node: Node, language: str, source: bytes) -> str | None:
    """Convenience function to extract docstring for a node.

    Args:
        node: AST node of the definition
        language: Language name
        source: Source code bytes

    Returns:
        Docstring text, or None if not found
    """
    extractor = DocstringExtractor(language)
    return extractor.extract_docstring(node, source)
