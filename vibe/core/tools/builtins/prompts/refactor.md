# Refactor Tool

Safely rename symbols across multiple files using AST-based analysis.

## When to Use

- Renaming functions, classes, or variables across the codebase
- Updating naming conventions consistently
- Refactoring without missing any references

## Operations

- `preview`: See what changes would be made (default, recommended first)
- `rename`: Actually apply the changes

## Workflow

1. Always use `preview` first to see the diff
2. Review the changes carefully
3. Use `rename` to apply if satisfied

## Examples

```python
# Step 1: Preview the rename
refactor(operation="preview", old_name="get_user", new_name="fetch_user")

# Step 2: If happy with preview, apply
refactor(operation="rename", old_name="get_user", new_name="fetch_user")

# Rename only in specific directory
refactor(
    operation="rename",
    old_name="helper",
    new_name="utility",
    scope="directory:src/utils"
)
```

## Understanding Results

The result includes:
- `files_modified`: Number of files that will be/were changed
- `total_changes`: Total number of replacements
- `file_changes`: Detailed changes per file with diffs
- `applied`: Whether changes were actually written

## Safety Features

- Preview mode shows exact diff before any changes
- AST-based matching (not just text replace)
- Only matches actual symbol references, not strings or comments
- Requires confirmation before applying

## Tips

- Always preview first to avoid surprises
- Use with `symbol_search` first to understand what will be changed
- The tool won't rename partial matches or strings containing the name
