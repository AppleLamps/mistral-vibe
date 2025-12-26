from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ResolverConfig:
    """Configuration for import resolution."""

    project_root: Path
    base_url: Path | None = None
    tsconfig_paths: dict[str, list[str]] = field(default_factory=dict)
    webpack_aliases: dict[str, str] = field(default_factory=dict)
    package_exports: dict[str, dict[str, str]] = field(default_factory=dict)
    workspaces: list[Path] = field(default_factory=list)


class ImportResolver:
    """Enhanced import resolution for JS/TS ecosystem and other languages."""

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.config = self._load_config()

    def _load_config(self) -> ResolverConfig:
        """Load configuration from tsconfig.json, package.json, etc."""
        config = ResolverConfig(project_root=self.project_root)

        # Load tsconfig.json paths
        tsconfig_path = self.project_root / "tsconfig.json"
        if tsconfig_path.exists():
            try:
                tsconfig = self._load_json_with_comments(tsconfig_path)
                compiler_options = tsconfig.get("compilerOptions", {})
                config.tsconfig_paths = compiler_options.get("paths", {})

                # Handle baseUrl
                base_url = compiler_options.get("baseUrl", ".")
                config.base_url = (self.project_root / base_url).resolve()
            except (json.JSONDecodeError, OSError):
                pass

        # Load package.json for workspaces and exports
        package_json_path = self.project_root / "package.json"
        if package_json_path.exists():
            try:
                package_json = json.loads(package_json_path.read_text())

                # Load workspaces
                workspaces = package_json.get("workspaces", [])
                if isinstance(workspaces, dict):
                    workspaces = workspaces.get("packages", [])
                for ws in workspaces:
                    # Expand globs
                    if "*" in ws:
                        for path in self.project_root.glob(ws):
                            if path.is_dir():
                                config.workspaces.append(path)
                    else:
                        ws_path = self.project_root / ws
                        if ws_path.is_dir():
                            config.workspaces.append(ws_path)

                # Load exports
                exports = package_json.get("exports", {})
                if exports:
                    config.package_exports[""] = self._parse_exports(exports)

            except (json.JSONDecodeError, OSError):
                pass

        return config

    def _load_json_with_comments(self, path: Path) -> dict[str, Any]:
        """Load JSON file, stripping comments (for tsconfig.json)."""
        content = path.read_text()
        # Remove single-line comments
        lines = []
        for line in content.split("\n"):
            stripped = line.lstrip()
            if not stripped.startswith("//"):
                # Remove inline comments (simple approach)
                # Be careful not to remove // inside strings
                comment_idx = self._find_comment_start(line)
                if comment_idx > -1:
                    line = line[:comment_idx]
                lines.append(line)

        # Remove trailing commas (common in tsconfig)
        cleaned = "\n".join(lines)
        cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)

        return json.loads(cleaned)

    def _find_comment_start(self, line: str) -> int:
        """Find the start of a // comment outside of strings."""
        in_string = False
        string_char = None
        i = 0
        while i < len(line) - 1:
            char = line[i]
            if in_string:
                if char == "\\" and i + 1 < len(line):
                    i += 2  # Skip escaped char
                    continue
                if char == string_char:
                    in_string = False
            else:
                if char in ('"', "'"):
                    in_string = True
                    string_char = char
                elif char == "/" and line[i + 1] == "/":
                    return i
            i += 1
        return -1

    def _parse_exports(self, exports: dict | str) -> dict[str, str]:
        """Parse package.json exports field."""
        result: dict[str, str] = {}

        if isinstance(exports, str):
            result["."] = exports
        elif isinstance(exports, dict):
            for key, value in exports.items():
                if isinstance(value, str):
                    result[key] = value
                elif isinstance(value, dict):
                    # Handle conditional exports
                    for condition in ("import", "require", "default", "types"):
                        if condition in value:
                            cond_value = value[condition]
                            if isinstance(cond_value, str):
                                result[key] = cond_value
                                break
                            elif isinstance(cond_value, dict):
                                # Nested conditional
                                for nested_cond in ("default", "import", "require"):
                                    if nested_cond in cond_value:
                                        result[key] = cond_value[nested_cond]
                                        break

        return result

    def resolve(self, import_path: str, from_file: Path) -> Path | None:
        """Resolve an import path to a file path.

        Args:
            import_path: The import path (e.g., './utils', '@/components/Button')
            from_file: The file containing the import

        Returns:
            Resolved file path, or None if not found
        """
        # 1. Check if it's a relative import
        if import_path.startswith("."):
            return self._resolve_relative(import_path, from_file)

        # 2. Check tsconfig paths
        resolved = self._resolve_tsconfig_path(import_path)
        if resolved:
            return resolved

        # 3. Check package exports (for monorepo internal packages)
        resolved = self._resolve_package_exports(import_path)
        if resolved:
            return resolved

        # 4. Check workspaces
        resolved = self._resolve_workspace(import_path)
        if resolved:
            return resolved

        # 5. Check node_modules
        resolved = self._resolve_node_modules(import_path, from_file)
        if resolved:
            return resolved

        # 6. Try as absolute path from project root
        resolved = self._try_resolve_path(self.project_root / import_path)
        if resolved:
            return resolved

        return None

    def _resolve_relative(self, import_path: str, from_file: Path) -> Path | None:
        """Resolve a relative import."""
        base_dir = from_file.parent if from_file.is_file() else from_file
        target = (base_dir / import_path).resolve()
        return self._try_resolve_path(target)

    def _resolve_tsconfig_path(self, import_path: str) -> Path | None:
        """Resolve using tsconfig.json paths."""
        base_url = self.config.base_url or self.project_root

        for pattern, targets in self.config.tsconfig_paths.items():
            # Check if pattern matches (simple wildcard support)
            if pattern.endswith("/*"):
                prefix = pattern[:-2]
                if import_path.startswith(prefix + "/"):
                    remainder = import_path[len(prefix) + 1 :]
                    for target in targets:
                        if target.endswith("/*"):
                            target_base = target[:-2]
                            resolved = self._try_resolve_path(
                                base_url / target_base / remainder
                            )
                            if resolved:
                                return resolved
            elif pattern == import_path:
                for target in targets:
                    resolved = self._try_resolve_path(base_url / target)
                    if resolved:
                        return resolved

        return None

    def _resolve_package_exports(self, import_path: str) -> Path | None:
        """Resolve using package.json exports."""
        for pkg_name, exports in self.config.package_exports.items():
            if import_path.startswith(pkg_name) if pkg_name else True:
                subpath = import_path[len(pkg_name) :] if pkg_name else import_path
                if subpath.startswith("/"):
                    subpath = "." + subpath
                elif not subpath:
                    subpath = "."

                if subpath in exports:
                    target = exports[subpath]
                    resolved = self._try_resolve_path(self.project_root / target)
                    if resolved:
                        return resolved

        return None

    def _resolve_node_modules(
        self, import_path: str, from_file: Path
    ) -> Path | None:
        """Resolve from node_modules."""
        current = from_file.parent if from_file.is_file() else from_file

        while current != current.parent:
            node_modules = current / "node_modules"
            if node_modules.is_dir():
                resolved = self._try_resolve_path(node_modules / import_path)
                if resolved:
                    return resolved

                # Check package.json main/module/types
                parts = import_path.split("/")
                if parts[0].startswith("@") and len(parts) > 1:
                    pkg_name = "/".join(parts[:2])
                    subpath = "/".join(parts[2:])
                else:
                    pkg_name = parts[0]
                    subpath = "/".join(parts[1:])

                pkg_path = node_modules / pkg_name / "package.json"
                if pkg_path.exists():
                    try:
                        pkg = json.loads(pkg_path.read_text())
                        entry = (
                            pkg.get("module") or pkg.get("main") or "index.js"
                        )
                        if subpath:
                            resolved = self._try_resolve_path(
                                node_modules / pkg_name / subpath
                            )
                        else:
                            resolved = self._try_resolve_path(
                                node_modules / pkg_name / entry
                            )
                        if resolved:
                            return resolved
                    except (json.JSONDecodeError, OSError):
                        pass

            current = current.parent

        return None

    def _resolve_workspace(self, import_path: str) -> Path | None:
        """Resolve from workspace packages."""
        for workspace in self.config.workspaces:
            pkg_json = workspace / "package.json"
            if pkg_json.exists():
                try:
                    pkg = json.loads(pkg_json.read_text())
                    pkg_name = pkg.get("name", "")

                    # Check if import matches package name
                    if import_path == pkg_name:
                        entry = pkg.get("module") or pkg.get("main") or "index.js"
                        resolved = self._try_resolve_path(workspace / entry)
                        if resolved:
                            return resolved
                    elif import_path.startswith(pkg_name + "/"):
                        subpath = import_path[len(pkg_name) + 1 :]
                        resolved = self._try_resolve_path(workspace / subpath)
                        if resolved:
                            return resolved

                except (json.JSONDecodeError, OSError):
                    pass

        return None

    def _try_resolve_path(self, path: Path) -> Path | None:
        """Try to resolve a path with various extensions."""
        # Common extensions to try
        extensions = [
            "",  # Exact match
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".mjs",
            ".cjs",
            ".json",
        ]
        index_files = [
            "index.ts",
            "index.tsx",
            "index.js",
            "index.jsx",
            "index.mjs",
        ]

        # Try direct path with extensions
        for ext in extensions:
            candidate = path if not ext else path.with_suffix(ext)
            if candidate.is_file():
                return candidate

        # Try as directory with index file
        if path.is_dir():
            for index_file in index_files:
                candidate = path / index_file
                if candidate.is_file():
                    return candidate

        # Try adding extensions to the path
        for ext in extensions[1:]:  # Skip empty extension
            candidate = Path(str(path) + ext)
            if candidate.is_file():
                return candidate

        return None


def resolve_import(
    import_path: str, from_file: Path, project_root: Path | None = None
) -> Path | None:
    """Convenience function to resolve an import.

    Args:
        import_path: The import path to resolve
        from_file: The file containing the import
        project_root: Project root (defaults to from_file's directory)

    Returns:
        Resolved file path, or None if not found
    """
    if project_root is None:
        # Try to find project root by looking for package.json or tsconfig.json
        current = from_file.parent if from_file.is_file() else from_file
        while current != current.parent:
            if (current / "package.json").exists() or (
                current / "tsconfig.json"
            ).exists():
                project_root = current
                break
            current = current.parent

        if project_root is None:
            project_root = from_file.parent if from_file.is_file() else from_file

    resolver = ImportResolver(project_root)
    return resolver.resolve(import_path, from_file)
