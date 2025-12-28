---
name: mcp-integration
description: |
  MCP (Model Context Protocol) integration patterns. Use when working with MCP servers,
  adding external tool integrations, or when user mentions "MCP", "stdio transport",
  "http transport", "external tools", or "tool proxy".
allowed-tools: Read, Grep, Glob
---

# MCP Integration Patterns

Guide for integrating MCP (Model Context Protocol) servers with vibe.

## Instructions

1. **MCP configuration in config.toml**:
   ```toml
   [[mcp_servers]]
   name = "my-server"
   transport = "stdio"        # or "http", "streamable-http"
   command = "npx"
   args = ["-y", "@my/mcp-server"]
   prompt = "Server for doing X"  # Hint for LLM

   [[mcp_servers]]
   name = "api-server"
   transport = "http"
   url = "https://mcp.example.com"
   headers = { Authorization = "Bearer ${API_KEY}" }
   ```

2. **Transport types**:
   - `stdio`: Subprocess with stdin/stdout communication
   - `http`: HTTP POST to `/mcp/v1/tools/call`
   - `streamable-http`: SSE-based streaming HTTP

3. **MCP server config models** (from config.py):
   ```python
   class MCPStdio(BaseModel):
       name: str
       transport: Literal["stdio"] = "stdio"
       command: str
       args: list[str] = Field(default_factory=list)
       prompt: str | None = None

       def argv(self) -> list[str]:
           return [self.command, *self.args]

   class MCPHttp(BaseModel):
       name: str
       transport: Literal["http"] = "http"
       url: str
       headers: dict[str, str] = Field(default_factory=dict)
       prompt: str | None = None
   ```

4. **Tool proxy pattern** (from mcp.py):
   ```python
   class RemoteTool(BaseModel):
       model_config = ConfigDict(from_attributes=True)

       name: str
       description: str | None = None
       input_schema: dict = Field(
           default_factory=lambda: {"type": "object", "properties": {}},
           validation_alias="inputSchema"
       )
   ```

5. **Retry configuration for connections**:
   ```python
   MCP_MAX_RETRIES = 3
   MCP_INITIAL_DELAY = 0.5
   MCP_BACKOFF_FACTOR = 2.0
   ```

6. **Tool name aliasing**:
   MCP tools are prefixed with server name: `mcp_{server}_{tool}`
   Example: `mcp_github_create_issue`

## Reference Files

- `vibe/core/config.py` - MCPStdio, MCPHttp, MCPStreamableHttp models
- `vibe/core/tools/mcp.py` - MCP proxy tool implementation
- `vibe/core/tools/manager.py` - MCP integration in ToolManager

## Configuration Example

```toml
# ~/.vibe/config.toml or .vibe/config.toml

[[mcp_servers]]
name = "filesystem"
transport = "stdio"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]
prompt = "Filesystem operations for project directories"

[[mcp_servers]]
name = "github"
transport = "http"
url = "https://mcp.github.example.com"
headers = { Authorization = "Bearer ${GITHUB_TOKEN}" }
prompt = "GitHub API operations"
```

## Debugging MCP

```bash
# Check MCP server status
uv run vibe  # Then use /status or check startup logs

# Test stdio server manually
npx -y @my/mcp-server --help
```

## Examples

- "Add a filesystem MCP server" → stdio transport config
- "Integrate external API" → http transport with auth
- "Tool not loading" → Check server status, command path

## Guardrails

- Read-only analysis unless user confirms writes
- Never hardcode API keys - use env vars like `${VAR}`
- Test MCP servers manually before adding to config
- Use descriptive `prompt` fields for LLM guidance
