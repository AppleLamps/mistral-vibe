# Dependency Analyzer Tool

Analyze import/dependency relationships between source files.

## When to Use

- Understanding what a file depends on
- Finding what files would be affected by changes
- Mapping out module architecture
- Identifying circular dependencies

## Operations

- `imports`: What does this file import?
- `dependents`: What files import this file?
- `graph`: Build a full dependency graph

## Examples

```python
# See what a file imports
dependency_analyzer(operation="imports", target="src/api/handler.py")

# Find files that depend on a module
dependency_analyzer(operation="dependents", target="src/utils/helpers.py")

# Build a dependency graph (2 levels deep)
dependency_analyzer(operation="graph", target="src/main.py", depth=2)
```

## Understanding Results

### imports
Returns a list of ImportInfo objects with:
- `imported_module`: The module being imported
- `imported_names`: Specific names imported (for `from X import a, b`)
- `line`: Line number of the import
- `is_relative`: Whether it's a relative import

### dependents
Returns a list of file paths that import the target.

### graph
Returns a dictionary where:
- Keys are file paths
- Values are lists of files that key imports

## Tips

- Use `dependents` before modifying a module to see impact
- Use `graph` to understand the architecture of a feature
- The `depth` parameter controls how far to follow imports
