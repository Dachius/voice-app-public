# Claude Agent SDK Python: Precise API Cheat Sheet

**For long-lived chat backends. Exact names, signatures, types. No prose.**

**Doc URLs:** https://code.claude.com/docs/en/agent-sdk/python (Python reference), https://code.claude.com/docs/en/agent-sdk/streaming-output.md (streaming), https://code.claude.com/docs/en/agent-sdk/sessions.md (sessions), https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts.md (system prompts), https://code.claude.com/docs/en/agent-sdk/mcp.md (MCP), https://code.claude.com/docs/en/agent-sdk/permissions.md (permissions), https://code.claude.com/docs/en/agent-sdk/custom-tools.md (custom tools)

---

## 1. Package, Installation, Authentication

**Package name:** `claude-agent-sdk`

**Install:** `pip install claude-agent-sdk` (or `uv add claude-agent-sdk`)

**Claude Code CLI required?** Bundled binaries included on most platforms (Linux x64, macOS arm64, macOS x64). No separate install needed unless:
- pip installs source distribution (ARM64 Windows): install Claude Code natively, SDK finds it on `$PATH`
- Custom `ANTHROPIC_BASE_URL` or gateways: no bundled binary, install natively

**Authentication:** 
- **Primary:** `ANTHROPIC_API_KEY` environment variable (API key from https://platform.claude.com/)
- **Also supports:**
  - `CLAUDE_CODE_USE_BEDROCK=1` + AWS credentials (Amazon Bedrock)
  - `CLAUDE_CODE_USE_ANTHROPIC_AWS=1` + `ANTHROPIC_AWS_WORKSPACE_ID` + AWS creds (Claude Platform on AWS)
  - `CLAUDE_CODE_USE_VERTEX=1` + Google Cloud creds (Google Cloud Agent Platform)
  - `CLAUDE_CODE_USE_FOUNDRY=1` + Azure creds (Microsoft Foundry)

**Note:** SDK does NOT load `.env` files automatically. Set env vars in shell or load explicitly before calling SDK.

**claude login / subscription OAuth:** The docs describe the API key as the canonical auth method, but with `cli_path` pointing at a CLI that is already logged in (`claude login`) the SDK inherits that session and no API key is needed. This app relies on that.

---

## 2. `ClaudeAgentOptions` (Dataclass)

**Import:** `from claude_agent_sdk import ClaudeAgentOptions`

**All fields and types:**

```python
@dataclass
class ClaudeAgentOptions:
    # Tool Configuration
    tools: list[str] | ToolsPreset | None = None
    allowed_tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    
    # System Prompt
    system_prompt: str | SystemPromptPreset | SystemPromptFile | None = None
    
    # MCP Servers
    mcp_servers: dict[str, McpServerConfig] | str | Path = field(default_factory=dict)
    strict_mcp_config: bool = False
    
    # Permissions & Control
    permission_mode: PermissionMode | None = None  # Literal["default", "acceptEdits", "plan", "dontAsk", "bypassPermissions", "auto"]
    can_use_tool: CanUseTool | None = None  # Callable callback
    
    # Session Management
    continue_conversation: bool = False
    resume: str | None = None
    session_id: str | None = None
    fork_session: bool = False
    resume_session_at: str | None = None
    resume_drops_turn: str | None = None
    
    # Limits & Budget
    max_turns: int | None = None
    max_budget_usd: float | None = None
    task_budget: TaskBudget | None = None
    
    # Model Configuration
    model: str | None = None
    fallback_model: str | None = None
    effort: EffortLevel | None = None  # Literal["low", "medium", "high", "xhigh", "max"]
    
    # Thinking
    thinking: ThinkingConfig | None = None
    max_thinking_tokens: int | None = None  # Deprecated
    
    # Output
    output_format: dict[str, Any] | None = None
    include_partial_messages: bool = False  # Enable StreamEvent yields for text deltas
    include_hook_events: bool = False
    forward_subagent_text: bool = False
    
    # File Operations
    enable_file_checkpointing: bool = False
    
    # Hooks & Custom Tools
    hooks: dict[HookEvent, list[HookMatcher]] | None = None
    
    # Subagents
    agents: dict[str, AgentDefinition] | None = None
    
    # Skills
    skills: list[str] | Literal["all"] | None = None
    
    # Environment
    cwd: str | Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    cli_path: str | Path | None = None
    
    # Settings
    settings: str | None = None
    setting_sources: list[SettingSource] | None = None  # ["project", "user"]
    add_dirs: list[str | Path] = field(default_factory=list)
    
    # Advanced
    betas: list[SdkBeta] = field(default_factory=list)
    plugins: list[SdkPluginConfig] = field(default_factory=list)
    sandbox: SandboxSettings | None = None
    session_store: SessionStore | None = None
    session_store_flush: SessionStoreFlushMode = "batched"
    load_timeout_ms: int = 60_000
    user: str | None = None
    extra_args: dict[str, str | None] = field(default_factory=dict)
    max_buffer_size: int | None = None
    stderr: Callable[[str], None] | None = None
    permission_prompt_tool_name: str | None = None
```

### System Prompt Options

**`system_prompt` field accepts three forms:**

1. **String (custom):** `system_prompt="You are a Python expert."`
   - Only what you provide; you lose Claude Code's tool guidance and safety instructions

2. **Preset dict:**
   ```python
   system_prompt={
       "type": "preset",
       "preset": "claude_code",  # Literal value
       "append": "Always add type hints.",  # Optional
       "exclude_dynamic_sections": True  # Optional (requires SDK v0.1.58+)
   }
   ```
   - `append` adds your text to the Claude Code prompt (lowers weight vs system prompt)
   - `exclude_dynamic_sections=True` moves per-session context (cwd, git status, etc.) to first user message for better prompt caching across runs

3. **File dict:**
   ```python
   system_prompt={
       "type": "file",
       "path": "/path/to/prompt.txt"
   }
   ```
   - Loads custom prompt from file (handles OS argument-length limits on Linux)

**`setting_sources`:** Controls what loads automatically
- `["project", "user"]` (default): loads `CLAUDE.md` or `.claude/CLAUDE.md` from working dir + `~/.claude/CLAUDE.md`
- `["project"]`: project only
- `[]`: nothing (disables CLAUDE.md injection)

**Built-in tools behavior:**
- With custom `system_prompt` string: built-in tools (`Read`, `Write`, `Bash`, etc.) ARE still available to Claude
- With `claude_code` preset: same as above
- Tools are injected regardless of system prompt choice

**Auto-memory:** Loads from `~/.claude/projects/` if setting sources include user/project. Separate from system prompt.

### Permission Mode Values

```python
PermissionMode = Literal[
    "default",          # No auto-approvals; falls through to can_use_tool callback
    "acceptEdits",      # Auto-approves file edits (Edit, Write, mkdir, rm, mv, cp, sed, touch)
    "plan",             # Read-only tools run; write ops go to callback (planning mode)
    "dontAsk",          # Pre-approved + deny rules run; everything else denied; callback never called
    "bypassPermissions", # Auto-approves except critical-path rm/rmdir and some always-prompt tools
    "auto"              # Model classifier votes on permission prompts
]
```

### can_use_tool Callback

**Type signature:**
```python
CanUseTool = Callable[
    [str, dict[str, Any], ToolPermissionContext], 
    Awaitable[PermissionResult]
]
```

**Callback receives:**
- `tool_name: str` — name of tool (e.g., "Bash", "mcp__github__list_issues")
- `input_data: dict[str, Any]` — tool arguments before execution
- `context: ToolPermissionContext` — metadata (see below)

**Returns:** `Awaitable[PermissionResult]` — coroutine yielding `PermissionResultAllow` or `PermissionResultDeny`

```python
@dataclass
class PermissionResultAllow:
    behavior: Literal["allow"] = "allow"
    updated_input: dict[str, Any] | None = None  # Modify input before execution
    updated_permissions: list[PermissionUpdate] | None = None

@dataclass
class PermissionResultDeny:
    behavior: Literal["deny"] = "deny"
    message: str = ""  # Reason shown to Claude
    interrupt: bool = False  # Whether to halt the session

@dataclass
class ToolPermissionContext:
    signal: Any | None = None
    suggestions: list[PermissionUpdate] = field(default_factory=list)
    tool_use_id: str | None = None
    agent_id: str | None = None
    blocked_path: str | None = None  # For file operations
    decision_reason: str | None = None
    title: str | None = None
    display_name: str | None = None
    description: str | None = None
```

---

## 3. `ClaudeSDKClient`: Persistent Sessions

**Import:** `from claude_agent_sdk import ClaudeSDKClient`

**Constructor:**
```python
client = ClaudeSDKClient(
    options: ClaudeAgentOptions | None = None,
    transport: Transport | None = None
)
```

**Methods:**
```python
async def connect(self, prompt: str | AsyncIterable[dict] | None = None) -> None
    # Establish connection; optionally send opening prompt

async def query(self, prompt: str | AsyncIterable[dict], session_id: str = "default") -> None
    # Send a turn; prompt is appended to session history
    # Multi-turn: each query() continues the same session if client is not recreated

async def receive_messages(self) -> AsyncIterator[Message]
    # Iterate over messages from the last query

async def receive_response(self) -> AsyncIterator[Message]
    # Alias for receive_messages

async def interrupt(self) -> None
    # Stop the running query

async def set_permission_mode(self, mode: str) -> None
    # Change permission mode mid-stream

async def set_model(self, model: str | None = None) -> None
    # Change model mid-stream

async def rewind_files(self, user_message_id: str) -> None
    # Revert file changes to a prior turn

async def get_mcp_status(self) -> McpStatusResponse
    # Get current MCP server connection statuses

async def reconnect_mcp_server(self, server_name: str) -> None
    # Retry a failed MCP server connection

async def toggle_mcp_server(self, server_name: str, enabled: bool) -> None
    # Enable/disable an MCP server

async def stop_task(self, task_id: str) -> None
    # Stop a specific background task

async def get_server_info(self) -> dict[str, Any] | None
    # Get server/build info

async def disconnect(self) -> None
    # Close connection
```

**Context manager:**
```python
async with ClaudeSDKClient(options=opts) as client:
    await client.query("First turn")
    async for message in client.receive_response():
        ...
    
    await client.query("Second turn - continues session")
    async for message in client.receive_response():
        ...
```

**Multi-turn within one client:**
- Each `client.query()` appends to the same session
- Same `client` instance = same session ID (internal)
- No explicit `resume`/session ID handling needed
- Connection managed by context manager or `connect()`/`disconnect()`

**How to get session_id for later resume in a new client:**
- Capture from `ResultMessage.session_id` after a query completes
- Use `resume=session_id` in `ClaudeAgentOptions` on a fresh `query()` call

---

## 4. Message Types and Content Blocks

**Import:** 
```python
from claude_agent_sdk import (
    AssistantMessage,
    UserMessage,
    SystemMessage,
    ResultMessage,
    ToolUseBlock,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ImageBlock
)
from claude_agent_sdk.types import StreamEvent
```

### Message Types

**`AssistantMessage`**
```python
@dataclass
class AssistantMessage:
    uuid: str
    message_id: str
    session_id: str
    content: list[TextBlock | ToolUseBlock | ThinkingBlock | ImageBlock]
    parent_tool_use_id: str | None = None
```

**`UserMessage`**
```python
@dataclass
class UserMessage:
    uuid: str
    message_id: str
    session_id: str
    content: list[...]  # Text, images, tool results
```

**`SystemMessage`**
```python
@dataclass
class SystemMessage:
    uuid: str
    session_id: str
    subtype: Literal["init", "compact_boundary"]  # "init" on session start
    data: dict[str, Any]  # Contains tools list, MCP servers, etc.
```

**`ResultMessage`** — Final outcome after all turns complete
```python
@dataclass
class ResultMessage:
    uuid: str
    session_id: str
    subtype: Literal["success", "error_max_turns", "error_max_budget_usd", "error_during_execution", "user_interrupted"]
    result: str | None  # Human-readable final output
    total_cost_usd: float | None  # Token cost
    total_input_tokens: int | None
    total_output_tokens: int | None
    cache_creation_input_tokens: int | None  # Prompt cache creation
    cache_read_input_tokens: int | None  # Prompt cache reads
```

### Content Block Types

**`TextBlock`**
```python
@dataclass
class TextBlock:
    type: Literal["text"]
    text: str
```

**`ThinkingBlock`**
```python
@dataclass
class ThinkingBlock:
    type: Literal["thinking"]
    thinking: str
```

**`ToolUseBlock`**
```python
@dataclass
class ToolUseBlock:
    type: Literal["tool_use"]
    id: str  # Unique ID for this tool call
    name: str  # Tool name
    input: dict[str, Any]  # Arguments (already validated JSON)
```

**`ToolResultBlock`**
```python
@dataclass
class ToolResultBlock:
    type: Literal["tool_result"]
    tool_use_id: str
    content: list[...]  # Text, images, resources
    is_error: bool = False
```

**`ImageBlock`**
```python
@dataclass
class ImageBlock:
    type: Literal["image"]
    source: dict[str, str]  # {"type": "base64", "media_type": "image/png", "data": "..."}
```

### StreamEvent (Partial Message Streaming)

**Import:** `from claude_agent_sdk.types import StreamEvent`

**Structure:**
```python
@dataclass
class StreamEvent:
    uuid: str  # Event unique ID
    session_id: str
    event: dict[str, Any]  # Raw Claude API streaming event
    parent_tool_use_id: str | None  # Always None in Python
```

**Accessing text deltas:**
```python
if isinstance(message, StreamEvent):
    event = message.event
    if event.get("type") == "content_block_delta":
        delta = event.get("delta", {})
        if delta.get("type") == "text_delta":
            text_chunk = delta.get("text", "")  # Incrementally stream this
```

**Event types available:**
- `message_start` — session starting
- `content_block_start` — text/tool block begins
- `content_block_delta` — incremental text or tool input JSON
- `content_block_stop` — block complete
- `message_delta` — message-level updates (stop reason, usage)
- `message_stop` — all blocks done

**Cost/usage/session_id retrieval:**
- `session_id`: present on every `StreamEvent` and `ResultMessage`
- `total_cost_usd`, `total_input_tokens`, etc.: only on `ResultMessage` (after all turns complete)
- `cache_creation_input_tokens`, `cache_read_input_tokens`: on `ResultMessage` when prompt caching is active

---

## 5. Custom System Prompt Behavior

When you set `system_prompt` to a custom string:

**What is loaded:**
- Only your custom prompt text (nothing else from `claude_code` preset)
- CLAUDE.md is still injected (controlled by `setting_sources`)
- Auto-memory is still loaded (if setting_sources includes user/project)
- Built-in tools ARE STILL AVAILABLE (Read, Write, Bash, Edit, etc.)

**What is NOT loaded:**
- Claude Code's tool usage guidance (you must replicate if needed)
- Claude Code's safety instructions (you must add your own)
- Claude Code's environment context (you must provide cwd, git status, etc. yourself)

**Trade-off:** Custom prompt = full control, but you're responsible for tool instructions and safety.

**Best practice for long-lived chat:** Use `system_prompt={"type": "preset", "preset": "claude_code", "append": "Your domain rules here"}` to keep tool guidance + safety, then layer your domain-specific instructions via `append`.

---

## 6. MCP Configuration

**Field in ClaudeAgentOptions:** `mcp_servers: dict[str, McpServerConfig] | str | Path`

### McpServerConfig Types (Union)

```python
# Stdio (local process)
@dataclass
class McpStdioServerConfig:
    command: str  # e.g., "npx"
    args: list[str]  # ["@modelcontextprotocol/server-filesystem", "/path"]
    env: dict[str, str] | None = None  # Pass env vars to server

# HTTP/SSE (remote)
@dataclass
class McpHttpServerConfig:
    type: Literal["http"]  # or "sse"
    url: str  # https://api.example.com/mcp
    headers: dict[str, str] | None = None  # Auth headers
    env: dict[str, str] | None = None

# In-process (SDK MCP server)
# Returned by create_sdk_mcp_server()
```

### Remote HTTP with Bearer Token

```python
options = ClaudeAgentOptions(
    mcp_servers={
        "api": {
            "type": "http",
            "url": "https://api.example.com/mcp",
            "headers": {
                "Authorization": f"Bearer {os.environ['API_TOKEN']}"
            }
        }
    },
    allowed_tools=["mcp__api__*"]
)
```

### claude.ai Connectors

Not documented as directly configurable via SDK. SDK MCP servers must be:
1. Stdio (command + args)
2. HTTP/SSE with headers
3. In-process SDK server

(Claude.ai connectors are a separate Anthropic-hosted feature, not exposed via SDK)

### Tool Naming

MCP tools: `mcp__{server_name}__{tool_name}`
- Example: `mcp__github__list_issues`
- Wildcard in `allowed_tools`: `mcp__github__*`

---

## 7. Gotchas and Advanced

### Concurrency

**One query at a time per client.** Do NOT:
```python
# WRONG
await client.query("first")
await client.query("second")  # Before receiving_response() from first
async for msg in client.receive_response():
    ...
```

**Correct:**
```python
await client.query("first")
async for msg in client.receive_response():
    pass  # Drain before next query

await client.query("second")
async for msg in client.receive_response():
    pass
```

### Async Loop Requirement

- Must run inside `async def` + `asyncio.run()` or equivalent
- Uses `anyio` internally (compatible with asyncio)
- No sync wrapper provided; don't try to call from sync code

### Large Output Truncation

- MCP tool results > 25,000 tokens: saved to file, tool result replaced with filename
- Raise limit: `MAX_MCP_OUTPUT_TOKENS` env var
- Not a hard error; agent can read file back

### stdin Transport (Undocumented)

- Exists but not the normal mode
- Default: spawns Claude Code subprocess
- No public API to override transport

### Environment Variables for Timeouts

Set in `options.env`:
```python
options = ClaudeAgentOptions(
    env={
        "API_TIMEOUT_MS": "120000",  # Default 600000
        "CLAUDE_CODE_MAX_RETRIES": "2",  # Default 10, max 15
        "CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS": "120000",
        "CLAUDE_ENABLE_STREAM_WATCHDOG": "1",  # Default 1
        "CLAUDE_STREAM_IDLE_TIMEOUT_MS": "300000",  # Min 300000
    }
)
```

### Session Resume Across Server Restart

To resume in a fresh Python process:
1. Capture `session_id` from `ResultMessage.session_id` after first run
2. On restart, pass `resume=session_id` in `ClaudeAgentOptions` to `query()`
3. Session file is at `~/.claude/projects/{encoded_cwd}/{session_id}.jsonl`
4. For cross-machine resumption: use `session_store` adapter (pass custom storage backend)

### File Checkpointing

Not a default; must explicitly enable:
```python
options = ClaudeAgentOptions(enable_file_checkpointing=True)
```
Then call `client.rewind_files(user_message_id)` to revert file changes.

---

## 8. TypeScript SDK Differences (TS-Only Features)

**Key TS-only or significantly different:**

1. **`continue: true`** instead of `ClaudeSDKClient` — TypeScript resumes most recent session via flag, Python uses client class
2. **Zod schemas for tools** — TypeScript uses `z.zod()`, Python uses dicts (more verbose JSON Schema)
3. **Warm subprocess startup** — TypeScript has `startup()` for pre-warming, Python doesn't
4. **Executable runtime choice** — TypeScript allows `executable: 'bun' | 'deno' | 'node'`, Python uses system Python
5. **Output format support** — TypeScript has `outputFormat` top-level option, Python doesn't
6. **Structured output** — TypeScript tool results support `structuredContent` field natively; Python SDK flattens it before CLI sees it
7. **Resource links** — TypeScript receives `resourceLinks` array on user message; Python doesn't
8. **Prompt caching boundary** — TypeScript can use `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` marker in array form of `systemPrompt`; Python only accepts string/preset/file

---

## 9. Minimal Complete Example

```python
import asyncio
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    StreamEvent
)

async def main():
    # Setup
    options = ClaudeAgentOptions(
        model="claude-3-5-sonnet-20241022",  # Specify model
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": "Always explain your reasoning step by step."
        },
        include_partial_messages=True,  # Enable StreamEvent for text deltas
        allowed_tools=["Read", "Bash"],
        permission_mode="acceptEdits",
        max_turns=10,
    )

    # Session management
    session_id = None
    
    async with ClaudeSDKClient(options=options) as client:
        # Turn 1: Initial query
        await client.query("What's in the current directory?")
        
        async for message in client.receive_response():
            if isinstance(message, StreamEvent):
                # Text delta streaming
                event = message.event
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        print(delta.get("text", ""), end="", flush=True)
            
            elif isinstance(message, AssistantMessage):
                # Complete assistant message
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"\n[Assistant]: {block.text}")
            
            elif isinstance(message, ResultMessage):
                session_id = message.session_id
                print(f"\n[Result]: {message.subtype}, Cost: ${message.total_cost_usd}")
        
        # Turn 2: Follow-up (auto-continues same session)
        await client.query("Now show me main.py")
        
        async for message in client.receive_response():
            if isinstance(message, ResultMessage):
                print(f"[Result]: {message.subtype}")
    
    # Resume in a new client later
    if session_id:
        print(f"\nSession ID for resumption: {session_id}")
        
        # Different session, same conversation
        options_resume = ClaudeAgentOptions(
            resume=session_id,
            allowed_tools=["Read"]
        )
        
        async for message in asyncio.to_thread(
            lambda: asyncio.run(
                query_resume(options_resume, "Summarize what we found.")
            )
        ):
            if isinstance(message, ResultMessage):
                print(f"Resumed: {message.result}")

async def query_resume(options, prompt):
    from claude_agent_sdk import query
    async for message in query(prompt=prompt, options=options):
        yield message

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 10. Query vs ClaudeSDKClient

| Use case | Function |
|----------|----------|
| One-shot task, no follow-up | `query()` |
| Multi-turn in same process | `ClaudeSDKClient` |
| Pick up after restart (same machine) | `query(..., options=ClaudeAgentOptions(resume=session_id, ...))` |
| Multi-user backend (one session per user) | `query()` with explicit `resume=user_session_id` for each user |

**`query()` function signature:**
```python
async def query(
    *,
    prompt: str | AsyncIterable[dict[str, Any]],
    options: ClaudeAgentOptions | None = None,
    transport: Transport | None = None
) -> AsyncIterator[Message]
```

---

## References

- https://code.claude.com/docs/en/agent-sdk/python.md — Full API reference
- https://code.claude.com/docs/en/agent-sdk/streaming-output.md — StreamEvent details
- https://code.claude.com/docs/en/agent-sdk/sessions.md — Session resume/continue/fork
- https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts.md — System prompt forms
- https://code.claude.com/docs/en/agent-sdk/mcp.md — MCP configuration
- https://code.claude.com/docs/en/agent-sdk/permissions.md — Permission modes and callbacks
- https://code.claude.com/docs/en/agent-sdk/custom-tools.md — Custom tool definition
- https://code.claude.com/docs/en/agent-sdk/quickstart.md — Installation and auth

