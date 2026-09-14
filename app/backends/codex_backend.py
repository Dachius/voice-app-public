"""OpenAI backend via the Codex CLI in headless mode (`codex exec --json`) under the user's ChatGPT login.

Verified against codex-cli 0.154.0: events are thread.started{thread_id}, turn.started, item.started/
item.completed{item:{id,type:command_execution|agent_message|...,command,aggregated_output,exit_code,status,text}},
turn.completed{usage}. `--approve-for-me` is Codex's classifier-reviewed auto mode inside a workspace-write sandbox.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Awaitable, Callable

log = logging.getLogger("codex")
Emit = Callable[[dict[str, Any]], Awaitable[None]]


class CodexBackend:
    def __init__(self, work_dir: str, instructions_dir: Path, extra_args: list[str]):
        self.work_dir = work_dir
        self.instructions_dir = instructions_dir
        self.extra_args = extra_args
        self._active: dict[str, asyncio.subprocess.Process] = {}
        self.bin = shutil.which("codex") or os.path.expanduser("~/.local/bin/codex")

    async def interrupt(self, conv_id: str) -> bool:
        p = self._active.get(conv_id)
        if not p:
            return False
        try:
            p.terminate()
            return True
        except ProcessLookupError:
            return False

    async def run_turn(self, conv: dict, text: str, system_prompt: str, emit: Emit, ask: Any = None) -> dict:
        parts: list[dict] = []
        result: dict[str, Any] = {"parts": parts, "session_id": conv.get("session_id"), "cost": None, "usage": None, "error": None}
        if not os.path.exists(self.bin):
            result["error"] = "codex CLI is not installed on the server"
            return result

        self.instructions_dir.mkdir(parents=True, exist_ok=True)
        instr = self.instructions_dir / f"{conv['id']}.md"
        instr.write_text(system_prompt)

        common = ["--json", "--skip-git-repo-check", "-C", self.work_dir,
                  "-c", f"model_instructions_file={json.dumps(str(instr))}",
                  "-m", conv["model"], *self.extra_args]
        # Global options must precede the `resume` subcommand (it only accepts a small option subset itself).
        if conv.get("session_id"):
            cmd = [self.bin, "exec", *common, "resume", conv["session_id"], text]
        else:
            cmd = [self.bin, "exec", *common, text]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=self.work_dir)
        except Exception as e:
            result["error"] = f"failed to start codex: {e}"
            return result
        self._active[conv["id"]] = proc
        tools_by_id: dict[str, dict] = {}
        try:
            assert proc.stdout
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").strip()
                if not line.startswith("{"):
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = ev.get("type", "")
                if t == "thread.started":
                    result["session_id"] = ev.get("thread_id") or result["session_id"]
                elif t.startswith("item."):
                    item = ev.get("item", {})
                    itype = item.get("type") or item.get("item_type")
                    iid = item.get("id", "")
                    if itype == "agent_message":
                        txt = item.get("text") or item.get("content") or ""
                        if t == "item.completed" and txt:
                            parts.append({"kind": "text", "text": txt})
                            await emit({"type": "text_start"})
                            await emit({"type": "delta", "text": txt})
                    elif itype == "reasoning":
                        if t == "item.completed" and item.get("text"):
                            parts.append({"kind": "thinking", "text": item.get("text", "")})
                    elif itype in ("command_execution", "file_change", "mcp_tool_call", "web_search"):
                        if t == "item.started":
                            name = "Bash" if itype == "command_execution" else itype
                            inp = {k: v for k, v in item.items() if k not in ("id", "type", "status")}
                            part = {"kind": "tool", "id": iid, "name": name, "input": inp, "result": None, "is_error": False}
                            parts.append(part)
                            tools_by_id[iid] = part
                            await emit({"type": "tool_use", "id": iid, "name": name, "input": inp})
                        elif t == "item.completed":
                            part = tools_by_id.get(iid)
                            out = item.get("aggregated_output") or item.get("output") or json.dumps(
                                {k: v for k, v in item.items() if k not in ("id", "type")})[:400]
                            is_err = item.get("status") in ("failed", "error") or (item.get("exit_code") not in (None, 0))
                            if part is not None:
                                part["result"] = str(out)[:400]
                                part["is_error"] = bool(is_err)
                            await emit({"type": "tool_result", "id": iid, "is_error": bool(is_err), "preview": str(out)[:400]})
                elif t == "turn.completed":
                    result["usage"] = ev.get("usage")
                elif t in ("turn.failed", "error"):
                    result["error"] = str(ev.get("error") or ev.get("message") or ev)[:500]
            await proc.wait()
            if proc.returncode not in (0, None) and not result["error"]:
                err = (await proc.stderr.read()).decode(errors="replace") if proc.stderr else ""
                result["error"] = f"codex exited {proc.returncode}: {err[-500:]}"
        except Exception as e:
            log.exception("codex turn failed")
            result["error"] = f"{type(e).__name__}: {e}"[:500]
        finally:
            self._active.pop(conv["id"], None)
        return result
