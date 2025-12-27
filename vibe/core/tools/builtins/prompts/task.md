Use the `task` tool to spawn isolated sub-agents for specific tasks. Sub-agents have their own conversation history, so only results return to you - dramatically reducing token usage.

## When to Use This Tool

**Use for:**
- Exploring unfamiliar parts of the codebase
- Researching how something is implemented
- Planning complex implementations
- Multi-step operations that would bloat your context
- Parallel exploration of different code areas

**Don't use for:**
- Simple single-file reads (use `read_file` directly)
- Quick grep searches (use `grep` directly)
- Tasks requiring your ongoing conversation context

## Sub-Agent Types

### `explore` - Codebase Exploration
- **Tools:** grep, read_file, list_dir, symbol_search
- **Auto-approve:** Yes
- **Best for:** Finding code, understanding implementations, researching patterns
- Example: "Find all usages of the UserAuth class and explain how authentication works"

### `plan` - Implementation Planning
- **Tools:** grep, read_file, list_dir, todo, symbol_search
- **Auto-approve:** Yes
- **Best for:** Designing approaches, identifying files to modify, creating plans
- Example: "Plan how to add a caching layer to the API client"

### `task` - General Execution
- **Tools:** All tools (except task - no recursion)
- **Auto-approve:** No (inherits your approval settings)
- **Best for:** Complex multi-step work that should be isolated
- Example: "Refactor the logging module to use structured logs"

## Arguments

```json
{
  "description": "Clear task description for the sub-agent",
  "type": "explore",  // or "plan" or "task"
  "tools": ["grep", "read_file"]  // optional: override default tools
}
```

## Examples

**Example 1: Exploring how a feature works**
```json
{
  "description": "Find where user sessions are managed and explain the session lifecycle",
  "type": "explore"
}
```

**Example 2: Planning an implementation**
```json
{
  "description": "Plan how to add rate limiting to the API. Identify files to modify and suggest an approach.",
  "type": "plan"
}
```

**Example 3: Parallel exploration**
Call the task tool multiple times in parallel:
```json
{"description": "Find all database models and their relationships", "type": "explore"}
{"description": "Find all API endpoints and their handlers", "type": "explore"}
{"description": "Find the test infrastructure and how tests are organized", "type": "explore"}
```

**Example 4: Delegating complex work**
```json
{
  "description": "Add input validation to all form components. Use consistent error message patterns.",
  "type": "task"
}
```

## How Results Work

The sub-agent runs independently and returns:
- `result`: The sub-agent's final response (what you see)
- `summary`: Brief description of actions taken
- `files_read`: List of files the sub-agent read
- `files_modified`: List of files the sub-agent changed
- `tokens_used`: Tokens consumed by the sub-agent

## Tips

1. **Be specific:** Give clear, focused tasks. Vague descriptions lead to poor results.

2. **Use explore for research:** Before implementing, spawn an explore agent to understand the code.

3. **Parallelize when possible:** Multiple explore tasks can run simultaneously.

4. **Check files_modified:** After a task agent runs, verify what it changed.

5. **Don't over-delegate:** Simple operations are faster done directly.

## Token Savings

Without sub-agents, a 10-step exploration adds ~50k tokens to your context.
With sub-agents, you get a single result message (~500 tokens).
**Savings: 90%+**
