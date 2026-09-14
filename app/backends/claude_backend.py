"""Claude backend on the Claude Agent SDK (runs the user's own logged-in Claude Code CLI).

Tool permissions are decided by the app, not the CLI: the SDK calls `can_use_tool` for anything that would
normally prompt, and we either auto-allow (policy "allow") or forward the prompt to the UI (policy "ask").

Sessions stay warm: one connected ClaudeSDKClient (= one `claude` process) is kept per conversation and reused
across turns, instead of spawning a fresh CLI and `--resume`-ing the transcript every turn (measured:
first turn ~4 s, later turns on the same client ~1.3 s). A client is dropped and rebuilt (with `resume`) when the
system prompt or model changes, after an error, when idle for `idle_close_s`, or when more than `max_warm`
conversations are warm (LRU). The websocket's emit/ask callbacks are rebound on every turn, so a page reload
between turns keeps the warm process.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any, Awaitable, Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from claude_agent_sdk.types import StreamEvent

log = logging.getLogger("claude")
Emit = Callable[[dict[str, Any]], Awaitable[None]]
Ask = Callable[[str, dict[str, Any]], Awaitable[bool]]


def _preview(content: Any, limit: int = 400) -> str:
    if isinstance(content, str):
        s = content
    elif isinstance(content, list):
        s = "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    else:
        s = str(content)
    s = s.strip()
    return s if len(s) <= limit else s[:limit] + " …"


class _Warm:
    """A connected client for one conversation plus the per-turn callbacks it should currently use."""

    def __init__(self, client: ClaudeSDKClient, key: str):
        self.client = client
        self.key = key                  # hash of (model, system prompt) the process was started with
        self.ask: Ask | None = None     # rebound every turn (the websocket may have reconnected)
        self.busy = False
        self.last_used = time.monotonic()
        self.last_total_cost = 0.0      # ResultMessage.total_cost_usd is cumulative per process; we report deltas


class ClaudeBackend:
    def __init__(self, cli_path: str, work_dir: str, policy: str, idle_close_s: float = 1800, max_warm: int = 4):
        self.cli_path = cli_path
        self.work_dir = work_dir
        self.policy = policy  # "allow" | "ask"
        self.idle_close_s = idle_close_s
        self.max_warm = max_warm
        self._warm: dict[str, _Warm] = {}
        self._reaper: asyncio.Task | None = None

    # ---------- lifecycle ----------
    async def _close(self, conv_id: str, why: str) -> None:
        w = self._warm.pop(conv_id, None)
        if not w:
            return
        log.info("closing warm session %s (%s)", conv_id, why)
        try:
            await asyncio.wait_for(w.client.disconnect(), 15)
        except Exception as e:
            log.warning("disconnect %s failed: %s", conv_id, e)

    async def close_all(self) -> None:
        for cid in list(self._warm):
            await self._close(cid, "shutdown")

    async def _reap(self) -> None:
        while True:
            await asyncio.sleep(60)
            now = time.monotonic()
            for cid, w in list(self._warm.items()):
                if not w.busy and now - w.last_used > self.idle_close_s:
                    await self._close(cid, "idle")

    async def _evict_lru(self, keep: str) -> None:
        idle = sorted((w.last_used, cid) for cid, w in self._warm.items() if cid != keep and not w.busy)
        while len(self._warm) > self.max_warm and idle:
            _, cid = idle.pop(0)
            await self._close(cid, "lru")

    async def _get_client(self, conv: dict, system_prompt: str, emit: Emit) -> _Warm:
        if self._reaper is None:
            self._reaper = asyncio.create_task(self._reap())
        cid = conv["id"]
        key = hashlib.sha1(f"{conv['model']}\n{system_prompt}".encode()).hexdigest()
        w = self._warm.get(cid)
        if w and w.key != key:
            await self._close(cid, "prompt or model changed")
            w = None
        if w:
            return w

        holder: dict[str, _Warm] = {}

        async def can_use_tool(tool_name: str, input_data: dict, context: Any):
            if self.policy == "allow":
                return PermissionResultAllow()
            ask = holder["w"].ask if "w" in holder else None
            ok = bool(ask and await ask(tool_name, input_data))
            return PermissionResultAllow() if ok else PermissionResultDeny(message="The user declined this tool call.")

        opts = ClaudeAgentOptions(
            model=conv["model"],
            system_prompt=system_prompt,
            include_partial_messages=True,
            setting_sources=["user"],  # user settings.json: hooks (memory auto-commit)
            permission_mode="default",
            can_use_tool=can_use_tool,
            cli_path=self.cli_path,
            cwd=self.work_dir,
            resume=conv.get("session_id"),
        )
        client = ClaudeSDKClient(options=opts)
        await client.connect()
        w = _Warm(client, key)
        holder["w"] = w
        self._warm[cid] = w
        await self._evict_lru(keep=cid)
        await emit({"type": "status", "text": "session started" + (" (resumed)" if conv.get("session_id") else "")})
        return w

    async def interrupt(self, conv_id: str) -> bool:
        w = self._warm.get(conv_id)
        if not w or not w.busy:
            return False
        try:
            await w.client.interrupt()
            return True
        except Exception as e:
            log.warning("interrupt failed: %s", e)
            return False

    # ---------- one turn ----------
    async def run_turn(self, conv: dict, text: str, system_prompt: str, emit: Emit, ask: Ask) -> dict:
        parts: list[dict] = []  # ordered text/thinking/tool parts of the assistant message
        tools_by_id: dict[str, dict] = {}
        result: dict[str, Any] = {
            "parts": parts,
            "session_id": conv.get("session_id"),
            "cost": None,
            "usage": None,
            "error": None,
        }
        w: _Warm | None = None
        try:
            w = await self._get_client(conv, system_prompt, emit)
            w.ask = ask
            w.busy = True
            w.last_used = time.monotonic()
            await w.client.query(text)
            async for m in w.client.receive_response():
                if isinstance(m, StreamEvent):
                    ev = m.event
                    t = ev.get("type")
                    if t == "content_block_delta":
                        d = ev.get("delta", {})
                        if d.get("type") == "text_delta":
                            await emit({"type": "delta", "text": d.get("text", "")})
                        elif d.get("type") == "thinking_delta":
                            await emit({"type": "thinking_delta", "text": d.get("thinking", "")})
                    elif t == "content_block_start":
                        cb = ev.get("content_block", {})
                        if cb.get("type") == "thinking":
                            await emit({"type": "thinking_start"})
                        elif cb.get("type") == "text":
                            await emit({"type": "text_start"})
                elif isinstance(m, AssistantMessage):
                    for b in m.content:
                        if isinstance(b, TextBlock):
                            if b.text.strip():
                                parts.append({"kind": "text", "text": b.text})
                        elif isinstance(b, ThinkingBlock):
                            parts.append({"kind": "thinking", "text": b.thinking})
                        elif isinstance(b, ToolUseBlock):
                            part = {"kind": "tool", "id": b.id, "name": b.name, "input": b.input, "result": None, "is_error": False}
                            parts.append(part)
                            tools_by_id[b.id] = part
                            await emit({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
                elif isinstance(m, UserMessage):
                    content = m.content if isinstance(m.content, list) else []
                    for b in content:
                        if isinstance(b, ToolResultBlock):
                            part = tools_by_id.get(b.tool_use_id)
                            prev = _preview(b.content)
                            if part is not None:
                                part["result"] = prev
                                part["is_error"] = bool(b.is_error)
                            await emit({"type": "tool_result", "id": b.tool_use_id, "is_error": bool(b.is_error), "preview": prev})
                elif isinstance(m, SystemMessage):
                    if m.subtype == "init":
                        mcp = ", ".join(s.get("name", "?") for s in m.data.get("mcp_servers", [])) or "none"
                        await emit({"type": "status", "text": f"session ready · {len(m.data.get('tools', []))} tools · mcp: {mcp}"})
                elif isinstance(m, ResultMessage):
                    result["session_id"] = m.session_id
                    total = m.total_cost_usd or 0.0
                    result["cost"] = max(0.0, total - w.last_total_cost)  # per-turn share of the process-cumulative figure
                    w.last_total_cost = total
                    result["usage"] = m.usage
                    result["subtype"] = m.subtype
                    if m.is_error or (m.subtype not in ("success", "user_interrupted")):
                        result["error"] = f"{m.subtype}: {(m.errors or m.result or '')}"[:500]
                    if not parts and m.result:
                        parts.append({"kind": "text", "text": m.result})
        except Exception as e:
            log.exception("claude turn failed")
            result["error"] = f"{type(e).__name__}: {e}"[:500]
            if w is not None:
                w.busy = False
                await self._close(conv["id"], "turn failed")  # next turn starts a fresh process with resume
        finally:
            if w is not None:
                w.busy = False
                w.ask = None
                w.last_used = time.monotonic()
        return result
