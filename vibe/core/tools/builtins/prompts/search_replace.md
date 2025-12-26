Use `search_replace` to make targeted changes to files using SEARCH/REPLACE blocks.

## Required Format

Every block MUST have these exact markers:
```
<<<<<<< SEARCH
exact text to find
=======
text to replace with
>>>>>>> REPLACE
```

## Example Tool Call

```python
search_replace(
    file_path="src/utils.py",
    content="""<<<<<<< SEARCH
def old_function():
    return "old"
=======
def new_function():
    return "new"
>>>>>>> REPLACE"""
)
```

## Common Mistakes (will cause "No valid blocks found" error)

❌ Missing `<<<<<<< SEARCH` marker
❌ Missing `=======` separator
❌ Missing `>>>>>>> REPLACE` marker
❌ Using wrong markers like `SEARCH:` or `--- SEARCH ---`
❌ Empty content with no blocks

## Rules

- SEARCH text must match EXACTLY (whitespace, indentation, line endings)
- SEARCH text must appear exactly once in the file
- Use at least 5 equals signs (=====) as separator
- Multiple blocks are applied in order
