# Agent Architecture Skill

Knowledge for working with Mistral Vibe's core agent system (`vibe/core/`).

## Core Components

### Agent (`vibe/core/agent.py`)
Main agent class that orchestrates LLM calls and tool execution.

Key attributes:
- `config: VibeConfig` - Configuration
- `tool_manager: ToolManager` - Tool discovery and execution
- `stats: AgentStats` - Token usage and statistics
- `approval_callback: ApprovalCallback` - Tool approval handler

Key methods:
- `async act(prompt: str) -> AsyncIterator[BaseEvent]` - Main execution loop
- `reset()` - Reset agent state

### Events (`vibe/core/types.py`)

All events inherit from `BaseEvent`:
- `AssistantEvent(content, stopped_by_middleware)` - LLM text output
- `ReasoningEvent(content)` - Chain-of-thought reasoning
- `ToolCallEvent(tool_name, tool_class, args, tool_call_id)` - Tool invocation
- `ToolResultEvent(tool_name, result, error, skipped, duration, tool_call_id)` - Tool result
- `CompactStartEvent(current_context_tokens, threshold)` - Context compaction starting
- `CompactEndEvent(old_context_tokens, new_context_tokens, summary_length)` - Compaction done

### Messages (`vibe/core/types.py`)

```python
class LLMMessage(BaseModel):
    role: Role  # system, user, assistant, tool
    content: Content | None
    reasoning_content: Content | None
    tool_calls: list[ToolCall] | None
    name: str | None
    tool_call_id: str | None
```

### Tool Approval Flow

```python
class ApprovalResponse(StrEnum):
    YES = "y"
    NO = "n"
    PREVIEW = "p"

# Callback signature
type AsyncApprovalCallback = Callable[
    [str, BaseModel, str],  # tool_name, args, tool_call_id
    Awaitable[tuple[ApprovalResponse, str | None]]  # response, reason
]
```

## Tool System

### Base Tool (`vibe/core/tools/base.py`)

```python
class BaseTool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]

    @abstractmethod
    async def execute(self, args: ArgsModel) -> ResultModel:
        ...

    @classmethod
    def get_name(cls) -> str: ...

    @classmethod
    def get_parameters(cls) -> dict: ...
```

### Tool Manager (`vibe/core/tools/manager.py`)

- Discovers tools from `vibe/core/tools/` and plugins
- `available_tools() -> dict[str, type[BaseTool]]`
- `get_all_tools() -> list[type[BaseTool]]`

### Tool Permissions

```python
class ToolPermission(StrEnum):
    ALWAYS = "always"  # Auto-approve
    ASK = "ask"        # Ask user (default)
    NEVER = "never"    # Always deny
```

Configured in `~/.config/vibe/config.yaml`:
```yaml
tools:
  shell:
    permission: ask
  read_file:
    permission: always
```

## Configuration (`vibe/core/config.py`)

### VibeConfig
```python
class VibeConfig(BaseModel):
    active_model: str
    models: list[ModelConfig]
    providers: list[ProviderConfig]
    tools: dict[str, BaseToolConfig]
    enabled_tools: list[str] | None  # Whitelist
    disabled_tools: list[str] | None  # Blacklist
```

### Loading and Saving
```python
# Load config
config = VibeConfig.load()

# Update and persist specific fields
VibeConfig.save_updates({"tools": {"shell": {"permission": "always"}}})

# Load API keys from environment
load_api_keys_from_env()
```

## LLM Integration

### Format Handler (`vibe/core/llm/format.py`)

```python
class APIToolFormatHandler:
    def get_available_tools(tool_manager, config) -> list[AvailableTool]
    def parse_message(message) -> ParsedMessage
    def resolve_tool_calls(parsed, tool_manager, config) -> ResolvedMessage
    def create_tool_response_message(tool_call, result) -> LLMMessage
```

### Tool Filtering

Tools can be filtered by name patterns:
- Exact match: `"shell"`
- Glob: `"serena_*"`
- Regex: `"re:^mcp_.*$"` or auto-detected `"serena.*"`

## Common Patterns

### Creating a New Tool
```python
from vibe.core.tools.base import BaseTool
from pydantic import BaseModel

class MyToolArgs(BaseModel):
    param: str

class MyToolResult(BaseModel):
    output: str

class MyTool(BaseTool):
    name = "my_tool"
    description = "Does something useful"

    async def execute(self, args: MyToolArgs) -> MyToolResult:
        # Implementation
        return MyToolResult(output="result")
```

### Streaming Events
```python
async for event in agent.act(prompt):
    match event:
        case AssistantEvent(content=text):
            print(text, end="", flush=True)
        case ToolCallEvent(tool_name=name, args=args):
            print(f"Calling {name}...")
        case ToolResultEvent(result=result):
            print(f"Result: {result}")
```

### Custom Approval Callback
```python
async def my_approval(
    tool_name: str,
    args: BaseModel,
    tool_call_id: str,
) -> tuple[ApprovalResponse, str | None]:
    if tool_name == "safe_tool":
        return ApprovalResponse.YES, None
    # Ask user...
    return ApprovalResponse.NO, "User denied"

agent.approval_callback = my_approval
```

## Stats Tracking

```python
class AgentStats(BaseModel):
    steps: int
    session_prompt_tokens: int
    session_completion_tokens: int
    tool_calls_agreed: int
    tool_calls_rejected: int
    tool_calls_failed: int
    tool_calls_succeeded: int
    context_tokens: int

    @computed_field
    def session_cost(self) -> float: ...
```
