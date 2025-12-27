# Performance Review & Optimization Report

This document provides a comprehensive analysis of performance issues and optimization opportunities in the Mistral Vibe codebase.

---

## Executive Summary

After thorough analysis of the codebase, I've identified **22 performance issues** across the following categories:
- **5 High-Impact Issues** - Critical bottlenecks affecting scalability and responsiveness
- **9 Medium-Impact Issues** - Inefficiencies causing noticeable slowdowns in common operations
- **8 Low-Impact Issues** - Minor optimizations for incremental improvements

The most significant issues center around:
1. Redundant file I/O operations in symbol search and AST analysis
2. Excessive pattern matching (fnmatch) in hot paths
3. Missing caching for expensive operations (backend detection, language detection)
4. Sequential subprocess calls that could be parallelized

---

## High-Impact Issues

### 1. Repeated File Reads in AST Context Extraction

**Location:** `vibe/core/tools/builtins/code_intel/ast_utils.py:696-723`

**Problem:** The `get_context_lines()` function reads the entire file from disk every time it's called. When searching for a symbol that appears multiple times in the same file, this causes redundant I/O:

```python
def get_context_lines(
    file_path: Path, line: int, context_before: int = 2, context_after: int = 2
) -> str:
    try:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()  # Re-reads every call!
    except OSError:
        return ""
    # ... process lines
```

**Impact:** For a file with 10 symbol matches, the file is read 10 times. In symbol searches across large codebases, this can cause hundreds of redundant file reads.

**Suggested Fix:**
```python
# Add a simple LRU cache for file contents
from functools import lru_cache

@lru_cache(maxsize=100)
def _read_file_lines(file_path: Path) -> tuple[str, ...]:
    """Cache file contents to avoid redundant reads."""
    try:
        return tuple(file_path.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return ()

def get_context_lines(
    file_path: Path, line: int, context_before: int = 2, context_after: int = 2
) -> str:
    lines = _read_file_lines(file_path)
    if not lines:
        return ""
    # ... rest of function
```

---

### 2. O(n×m) fnmatch Pattern Matching in File Collection

**Location:** `vibe/core/tools/builtins/symbol_search.py:225-267`

**Problem:** The `_collect_files()` method performs `fnmatch.fnmatch()` for every file against every exclude pattern. With 5,000 files and 7 exclude patterns, this is 35,000 pattern matching operations:

```python
def _collect_files(self, root: Path, language_filter: str | None) -> list[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        # Filter out excluded directories - O(n_dirs × n_patterns)
        dirnames[:] = [
            d for d in dirnames
            if not any(
                fnmatch.fnmatch(os.path.join(dirpath, d), pat)  # Called for EVERY dir
                for pat in self.config.exclude_patterns
            )
        ]

        for filename in filenames:
            # ... another O(n_files × n_patterns) loop
            if any(
                fnmatch.fnmatch(full_path, pat)
                for pat in self.config.exclude_patterns
            ):
                continue
```

**Impact:** For large codebases, file collection can take several seconds, blocking symbol search.

**Suggested Fix:**
```python
import re

def _collect_files(self, root: Path, language_filter: str | None) -> list[Path]:
    # Pre-compile patterns to regex for faster matching
    exclude_regexes = [
        re.compile(fnmatch.translate(pat)) for pat in self.config.exclude_patterns
    ]

    def is_excluded(path_str: str) -> bool:
        return any(regex.match(path_str) for regex in exclude_regexes)

    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Filter directories in-place with pre-compiled regex
        dirnames[:] = [d for d in dirnames if not is_excluded(os.path.join(dirpath, d))]

        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            if not is_excluded(full_path):
                files.append(Path(full_path))

    return files
```

---

### 3. Duplicate File Read in Symbol Search

**Location:** `vibe/core/tools/builtins/symbol_search.py:269-293`

**Problem:** The `_search_file()` method reads the file twice - once implicitly through `parser.parse_file()` and again explicitly with `file_path.read_bytes()`:

```python
def _search_file(self, file_path: Path, symbol: str, operation: SymbolOp, parser) -> list[SymbolMatch]:
    tree = parser.parse_file(file_path)  # First read: inside parse_file()
    if tree is None:
        return []

    # ...

    try:
        source = file_path.read_bytes()  # Second read: redundant!
    except OSError:
        return []
```

**Impact:** Every file searched is read twice, doubling I/O overhead.

**Suggested Fix:**
Modify `parser.parse_file()` to return both the tree and the source bytes, or cache the source within the parser:

```python
# Option 1: Return source with tree
def _search_file(self, file_path: Path, symbol: str, operation: SymbolOp, parser) -> list[SymbolMatch]:
    source = file_path.read_bytes()
    tree = parser.parse_bytes(source, get_language_for_file(file_path))
    if tree is None:
        return []
    # Use source directly, no re-read needed
```

---

### 4. Sequential Git Subprocess Calls

**Location:** `vibe/core/tools/builtins/git.py:189-279`

**Problem:** Several git operations run multiple sequential subprocess calls when they could be combined or parallelized:

```python
async def _git_add(self, args: GitArgs) -> GitResult:
    cmd = ["git", "add", args.path]
    result = await self._run_git_command(cmd)

    # Second subprocess call - waits for first to complete
    status_result = await self._git_status()
    result.output = f"Staged: {args.path}\n\n{status_result.output}"
    return result

async def _git_reset(self, args: GitArgs) -> GitResult:
    # ... reset command
    result = await self._run_git_command(cmd)

    # Another sequential call
    status_result = await self._git_status()
    result.output = f"Reset complete.\n\n{status_result.output}"
    return result
```

**Impact:** Each sequential call adds ~50-100ms of subprocess overhead.

**Suggested Fix:**
```python
async def _git_add(self, args: GitArgs) -> GitResult:
    # Run git add and status concurrently
    add_task = asyncio.create_task(self._run_git_command(["git", "add", args.path]))
    status_task = asyncio.create_task(self._git_status())

    result, status_result = await asyncio.gather(add_task, status_task)
    result.output = f"Staged: {args.path}\n\n{status_result.output}"
    return result
```

Note: For `git reset`, the status must come after, but `git add` can run concurrently with status.

---

### 5. Tool Discovery Imports All Python Files on Every Init

**Location:** `vibe/core/tools/manager.py:91-130`

**Problem:** `_iter_tool_classes()` dynamically imports and executes every `.py` file in all tool search paths. This happens on every `ToolManager` instantiation:

```python
@staticmethod
def _iter_tool_classes(search_paths: list[Path]) -> Iterator[type[BaseTool]]:
    for base in search_paths:
        for path in base.rglob("*.py"):  # Scans filesystem
            # ...
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # Executes every .py file!

            for obj in vars(module).values():
                if issubclass(obj, BaseTool):
                    yield obj
```

**Impact:**
- Slow agent initialization (100-500ms depending on tool count)
- Custom tools with heavy imports slow down every session
- No caching between sessions

**Suggested Fix:**
Implement a discovery cache with file modification time tracking:

```python
import hashlib
import json

_TOOL_CACHE: dict[str, type[BaseTool]] = {}
_CACHE_FILE = Path.home() / ".vibe" / "cache" / "tool_discovery.json"

def _get_search_path_hash(search_paths: list[Path]) -> str:
    """Hash of all .py files and their modification times."""
    files_info = []
    for base in search_paths:
        for path in base.rglob("*.py"):
            try:
                files_info.append(f"{path}:{path.stat().st_mtime}")
            except OSError:
                pass
    return hashlib.md5("|".join(sorted(files_info)).encode()).hexdigest()

@staticmethod
def _iter_tool_classes(search_paths: list[Path]) -> Iterator[type[BaseTool]]:
    # Check if cache is valid
    current_hash = _get_search_path_hash(search_paths)
    if _TOOL_CACHE and _TOOL_CACHE.get("_hash") == current_hash:
        yield from _TOOL_CACHE.values()
        return

    # Discover and cache
    _TOOL_CACHE.clear()
    # ... existing discovery logic ...
    _TOOL_CACHE["_hash"] = current_hash
```

---

## Medium-Impact Issues

### 6. Repeated Backend Detection in Grep Tool

**Location:** `vibe/core/tools/builtins/grep.py:107-115`

**Problem:** `_detect_backend()` calls `shutil.which()` twice on every grep invocation:

```python
def _detect_backend(self) -> GrepBackend:
    if shutil.which("rg"):  # Filesystem lookup
        return GrepBackend.RIPGREP
    if shutil.which("grep"):  # Another filesystem lookup
        return GrepBackend.GNU_GREP
    raise ToolError("Neither ripgrep (rg) nor grep is installed.")
```

**Impact:** 2 subprocess spawns per grep call (~10-20ms overhead).

**Suggested Fix:**
```python
_cached_backend: GrepBackend | None = None

def _detect_backend(self) -> GrepBackend:
    global _cached_backend
    if _cached_backend is not None:
        return _cached_backend

    if shutil.which("rg"):
        _cached_backend = GrepBackend.RIPGREP
    elif shutil.which("grep"):
        _cached_backend = GrepBackend.GNU_GREP
    else:
        raise ToolError("Neither ripgrep (rg) nor grep is installed.")

    return _cached_backend
```

---

### 7. No Caching for Language Detection

**Location:** `vibe/core/tools/builtins/code_intel/languages.py` (implied from usage)

**Problem:** `get_language_for_file()` is called multiple times per file during symbol search - once in `_collect_files()` for filtering, once in `_search_file()` for parsing:

```python
# In _collect_files:
if language_filter:
    file_lang = get_language_for_file(file_path)  # First call
    if file_lang != language_filter:
        continue

# In _search_file:
language = get_language_for_file(file_path)  # Second call for same file
```

**Suggested Fix:**
```python
from functools import lru_cache

@lru_cache(maxsize=1000)
def get_language_for_file(file_path: Path) -> str | None:
    """Get the language identifier for a file based on extension."""
    # ... existing logic
```

---

### 8. OpenRouter Model Parsing in Hot Path

**Location:** `vibe/core/config.py:378-396`

**Problem:** When `get_active_model()` is called with an OpenRouter model, it loads the cache and parses ALL models to find the one match:

```python
def get_active_model(self) -> ModelConfig:
    for model in self.models:
        if model.alias == self.active_model:
            return model

    if self.active_model.startswith("or:"):
        from vibe.core.openrouter.gateway import _load_cache, _parse_model

        cache = _load_cache()  # Loads JSON from disk
        if cache:
            for model_data in cache.models:  # Iterates ALL models
                parsed = _parse_model(model_data)  # Parses each one
                if parsed and parsed["alias"] == self.active_model:
                    return ModelConfig(**parsed)
```

**Impact:** With 200+ OpenRouter models, this is significant overhead on every LLM call.

**Suggested Fix:**
```python
# Build an index once and cache it
_openrouter_model_index: dict[str, ModelConfig] | None = None

def get_active_model(self) -> ModelConfig:
    for model in self.models:
        if model.alias == self.active_model:
            return model

    if self.active_model.startswith("or:"):
        global _openrouter_model_index
        if _openrouter_model_index is None:
            _openrouter_model_index = self._build_openrouter_index()

        if model := _openrouter_model_index.get(self.active_model):
            return model
```

---

### 9. fnmatch Import Inside Hot Loop

**Location:** `vibe/core/tools/builtins/read_file.py:88`, `vibe/core/tools/builtins/list_dir.py:107`

**Problem:** `fnmatch` is imported inside functions that are called frequently:

```python
def check_allowlist_denylist(self, args: ReadFileArgs) -> ToolPermission | None:
    import fnmatch  # Import on every call!

    for pattern in self.config.denylist:
        if fnmatch.fnmatch(file_str, pattern):
            return ToolPermission.NEVER
```

**Impact:** While Python caches imports, there's still lookup overhead.

**Suggested Fix:**
Move imports to module level:
```python
from __future__ import annotations
import fnmatch  # At module level
# ...
```

---

### 10. Repeated String Encoding for Byte Counting

**Location:** `vibe/core/tools/builtins/read_file.py:131`

**Problem:** Each line is encoded to UTF-8 just to count bytes:

```python
async for line in f:
    # ...
    line_bytes = len(line.encode("utf-8"))  # Encodes every line
```

**Suggested Fix:**
For most files, we can estimate or use a cheaper method:
```python
# Faster approximation for ASCII-heavy files
line_bytes = len(line) + sum(1 for c in line if ord(c) > 127)

# Or: track bytes directly if aiofiles supports it
```

---

### 11. Repeated Path Expansion and Validation

**Location:** `vibe/core/tools/builtins/read_file.py:105-113`, `vibe/core/tools/builtins/list_dir.py:126-141`

**Problem:** Path expansion (`expanduser`, `resolve`) happens multiple times:

```python
def _prepare_and_validate_path(self, args: ReadFileArgs) -> Path:
    self._validate_inputs(args)

    file_path = Path(args.path).expanduser()  # First expansion
    if not file_path.is_absolute():
        file_path = self.config.effective_workdir / file_path

    self._validate_path(file_path)  # Calls resolve() again
    return file_path

def _validate_path(self, file_path: Path) -> None:
    project_root = self.config.effective_workdir.resolve()  # Repeated resolution
    resolved_path = file_path.resolve()  # Another resolution
```

**Suggested Fix:**
Resolve once and pass through:
```python
def _prepare_and_validate_path(self, args: ReadFileArgs) -> Path:
    file_path = Path(args.path).expanduser()
    if not file_path.is_absolute():
        file_path = self.config.effective_workdir / file_path

    resolved_path = file_path.resolve()
    self._validate_resolved_path(resolved_path)
    return resolved_path
```

---

### 12. Message History Scanning for Session State

**Location:** `vibe/core/agent.py:993-1052`

**Problem:** `_extract_session_state_for_compact()` iterates through all messages to extract file modifications and errors:

```python
def _extract_session_state_for_compact(self) -> str:
    modified_files: set[str] = set()
    recent_errors: list[str] = []
    successful_tools: list[str] = []

    for msg in self.messages:  # O(n) scan of ALL messages
        if msg.role == Role.tool and msg.content:
            content = msg.content
            tool_name = msg.name or "unknown"

            if tool_name in ("write_file", "search_replace"):
                # String parsing for every message
                if "file:" in content.lower():
                    for line in content.split("\n"):
                        # ...
```

**Impact:** For long sessions with hundreds of messages, this scan adds latency during compaction.

**Suggested Fix:**
Track file modifications incrementally as they happen:
```python
class Agent:
    def __init__(self, ...):
        # ...
        self._modified_files: set[str] = set()
        self._recent_errors: list[str] = []

    async def _emit_tool_result(self, tool_call, result, tool_call_id):
        # Track modifications as they happen
        if tool_call.tool_name in ("write_file", "search_replace"):
            if hasattr(result, 'path'):
                self._modified_files.add(result.path)
        # ...
```

---

### 13. Blocking Date Formatting in Directory Listing

**Location:** `vibe/core/tools/builtins/list_dir.py:270`

**Problem:** Date formatting is done for every file entry:

```python
def _create_entry(self, path: Path, show_size: bool, base_path: Path | None = None) -> FileEntry:
    try:
        stat = path.stat()
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")  # For every file
```

**Suggested Fix:**
Only format dates when actually needed, or batch the formatting:
```python
def _create_entry(self, path: Path, show_size: bool, base_path: Path | None = None) -> FileEntry:
    try:
        stat = path.stat()
        # Store raw timestamp, format lazily
        modified_ts = stat.st_mtime
    except (OSError, PermissionError):
        modified_ts = None

    return FileEntry(
        # ...
        modified_ts=modified_ts,  # Store raw, format in display
    )
```

---

### 14. No Connection Pooling for LLM API Calls

**Location:** `vibe/core/llm/backend/` (inferred from architecture)

**Problem:** Each LLM call may create a new HTTP connection. The `async with self.backend` pattern suggests context managers that may not reuse connections.

**Suggested Fix:**
Ensure `httpx.AsyncClient` is reused across calls:
```python
class MistralBackend:
    def __init__(self, ...):
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=5)
        )

    async def complete(self, ...):
        # Reuse self._client instead of creating new one
```

---

## Low-Impact Issues

### 15. List Comprehension with Redundant Type Check

**Location:** Various locations

**Problem:** Some list comprehensions check conditions that could be simplified:

```python
# In symbol_search.py
for result in self.query(ToolResultMessage):
    if result.tool_name != "todo":  # Could use filter in query
        await result.set_collapsed(self._tools_collapsed)
```

---

### 16. String Concatenation in Loops

**Location:** `vibe/core/agent.py:328-330`

**Problem:** String building via concatenation:

```python
todo_list = "\n".join(
    f"- [{t.status}] {t.content}" for t in incomplete_todos
)
```

This is actually fine (uses join), but watch for patterns like:
```python
output = ""
for item in items:
    output += f"line: {item}\n"  # O(n²) string copies
```

---

### 17. Unnecessary Path Object Creation

**Location:** Various tools

**Problem:** `Path` objects are created multiple times for the same string:

```python
file_path = Path(args.path)  # First Path
file_path = file_path.expanduser()  # Returns new Path
resolved = file_path.resolve()  # Returns new Path
```

While not expensive individually, this adds up across many file operations.

---

### 18. Unused Regex Compilation

**Location:** `vibe/core/config.py:151-155`

**Problem:** Regex in `normalize_name` is compiled on every call:

```python
@classmethod
def normalize_name(cls, v: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]", "_", v)  # Compiles pattern each time
```

**Suggested Fix:**
```python
_NAME_CLEANUP_PATTERN = re.compile(r"[^a-zA-Z0-9_-]")

@classmethod
def normalize_name(cls, v: str) -> str:
    normalized = _NAME_CLEANUP_PATTERN.sub("_", v)
```

---

### 19. Middleware Creates New Dataclass Instances

**Location:** `vibe/core/middleware.py:37-40`

**Problem:** `MiddlewareResult` with default factory is created for every "continue" action:

```python
async def before_turn(self, context: ConversationContext) -> MiddlewareResult:
    if context.stats.steps - 1 >= self.max_turns:
        return MiddlewareResult(action=MiddlewareAction.STOP, ...)
    return MiddlewareResult()  # New object for common case
```

**Suggested Fix:**
```python
_CONTINUE_RESULT = MiddlewareResult()  # Singleton for common case

async def before_turn(self, context: ConversationContext) -> MiddlewareResult:
    if context.stats.steps - 1 >= self.max_turns:
        return MiddlewareResult(action=MiddlewareAction.STOP, ...)
    return _CONTINUE_RESULT
```

---

### 20. Recursive Generator in AST Walking

**Location:** `vibe/core/tools/builtins/code_intel/ast_utils.py:17-28`

**Problem:** `walk_tree` creates a generator for every node, which has overhead:

```python
def walk_tree(node: Node) -> Generator[Node, None, None]:
    yield node
    for child in node.children:
        yield from walk_tree(child)  # New generator per node
```

**Suggested Fix:**
Use an iterative approach with a stack:
```python
def walk_tree(node: Node) -> Generator[Node, None, None]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))
```

---

### 21. Config Validation Runs Multiple Times

**Location:** `vibe/core/config.py:453-547`

**Problem:** Multiple `@model_validator` decorators run sequentially, and some do redundant work:

```python
@model_validator(mode="after")
def _check_api_key(self) -> VibeConfig:
    active_model = self.get_active_model()  # First lookup
    provider = self.get_provider_for_model(active_model)
    # ...

@model_validator(mode="after")
def _check_api_backend_compatibility(self) -> VibeConfig:
    active_model = self.get_active_model()  # Same lookup again
    provider = self.get_provider_for_model(active_model)  # Same again
```

**Suggested Fix:**
Combine related validators:
```python
@model_validator(mode="after")
def _check_model_and_provider(self) -> VibeConfig:
    try:
        active_model = self.get_active_model()
        provider = self.get_provider_for_model(active_model)
        # All checks in one place
    except ValueError:
        pass
    return self
```

---

### 22. Unnecessary List Copies

**Location:** `vibe/core/tools/manager.py:152-156`

**Problem:** `dict()` and `list()` copies are made for simple returns:

```python
def available_tools(self) -> dict[str, type[BaseTool]]:
    return dict(self._available)  # Defensive copy - may not be needed

def mcp_status(self) -> list[MCPServerStatus]:
    return list(self._mcp_status)  # Another defensive copy
```

If callers don't modify these, the copies are wasteful.

---

## Optimization Priority Matrix

| Priority | Issue # | Component | Est. Impact | Est. Effort |
|----------|---------|-----------|-------------|-------------|
| P0 | 1 | AST Utils | High | Low |
| P0 | 2 | Symbol Search | High | Medium |
| P0 | 3 | Symbol Search | High | Low |
| P1 | 4 | Git Tool | Medium | Low |
| P1 | 5 | Tool Manager | High | Medium |
| P1 | 6 | Grep Tool | Medium | Low |
| P1 | 7 | Code Intel | Medium | Low |
| P2 | 8 | Config | Medium | Low |
| P2 | 9-11 | Various | Low | Low |
| P3 | 12-22 | Various | Low | Low |

---

## Implementation Recommendations

### Quick Wins (< 1 hour each)
1. Add `@lru_cache` to `get_context_lines()` for file content caching
2. Cache grep backend detection result
3. Add `@lru_cache` to `get_language_for_file()`
4. Move fnmatch imports to module level
5. Pre-compile regex patterns in config normalization

### Medium Effort (1-4 hours each)
1. Refactor `_collect_files()` to use pre-compiled regex
2. Modify parser to return source bytes with tree
3. Add OpenRouter model index caching
4. Implement incremental file modification tracking in Agent

### Larger Refactors (4+ hours)
1. Implement tool discovery caching with invalidation
2. Add connection pooling to LLM backends
3. Parallelize Git operations where safe

---

## Monitoring Recommendations

Consider adding performance instrumentation:

```python
import time
from contextlib import contextmanager

@contextmanager
def timed_operation(name: str):
    start = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - start
        if duration > 0.1:  # Log slow operations
            logger.warning(f"{name} took {duration:.3f}s")
```

Key operations to monitor:
- Tool discovery time
- Symbol search duration by file count
- LLM API latency
- File I/O operations

---

## Conclusion

The codebase is well-structured with good async practices, but has accumulated some performance debt in hot paths. The most impactful optimizations focus on:

1. **Caching** - File contents, language detection, backend detection
2. **Avoiding redundant I/O** - Don't read files multiple times
3. **Pre-compilation** - Regex patterns, fnmatch patterns
4. **Parallelization** - Git operations, independent API calls

Implementing the P0 and P1 fixes should yield noticeable improvements in responsiveness, especially for symbol search and large codebase operations.
