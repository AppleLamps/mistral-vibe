Use `grep` to recursively search for a regular expression pattern in files.

## Key Features

- Very fast recursive search across the codebase
- Automatically ignores irrelevant files (.pyc, .venv, node_modules, etc.)
- Supports regular expressions for flexible pattern matching

## Common Use Cases

- Find function/class definitions: `grep(pattern="def process_data", path="src/")`
- Find variable usage: `grep(pattern="user_config", path=".")`
- Find imports: `grep(pattern="from utils import", path=".")`
- Find TODO comments: `grep(pattern="TODO|FIXME", path=".")`
- Find error messages: `grep(pattern="Error:.*failed", path=".")`

## Pattern Syntax Tips

- Literal text: `grep(pattern="exact match")`
- Case insensitive: Use `(?i)` prefix, e.g., `(?i)error`
- Word boundaries: `\bword\b` matches "word" but not "keyword"
- Any character: `.` matches any single character
- Alternatives: `pattern1|pattern2` matches either
- Optional: `colou?r` matches "color" or "colour"

## Arguments

- `pattern`: The regex pattern to search for (required)
- `path`: Directory or file to search in (default: current directory)
- `include`: Glob pattern to filter files, e.g., `*.py` for Python files only
