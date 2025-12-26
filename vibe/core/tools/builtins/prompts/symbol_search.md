# Symbol Search Tool

Find symbol definitions and references across the codebase using AST-based analysis.

## When to Use

- Finding where a function, class, or variable is defined
- Finding all places where a symbol is used/referenced
- Understanding the scope and usage of a symbol before refactoring

## Operations

- `definition`: Find where a symbol is defined
- `references`: Find all usages of a symbol
- `all`: Find both definitions and references (default)

## Scope Options

- `project`: Search entire project (default)
- `file:<path>`: Search a specific file
- `directory:<path>`: Search a specific directory

## Examples

```python
# Find where a function is defined
symbol_search(symbol="process_request", operation="definition")

# Find all usages of a class
symbol_search(symbol="UserModel", operation="references")

# Search in a specific directory
symbol_search(symbol="helper", scope="directory:src/utils")
```

## Supported Languages

- Python (.py, .pyi)
- JavaScript (.js, .jsx, .mjs)
- TypeScript (.ts, .tsx)

## Tips

- Use `definition` when you need to understand what a symbol does
- Use `references` before renaming to see the impact
- Results include surrounding context for quick understanding
