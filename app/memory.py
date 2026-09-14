"""Memory repo access: pull before a turn, read the index, commit/push leftovers after a turn."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

log = logging.getLogger("memory")


class Memory:
    def __init__(self, repo: Path):
        self.repo = repo

    async def _git(self, *args: str, timeout: float = 20) -> tuple[int, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "-C", str(self.repo), *args,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout)
            return proc.returncode or 0, out.decode(errors="replace")
        except asyncio.TimeoutError:
            log.warning("git %s timed out", args[0])
            return 124, "timeout"
        except Exception as e:  # git missing, repo missing
            log.warning("git %s failed: %s", args[0], e)
            return 1, str(e)

    async def pull(self) -> None:
        rc, out = await self._git("pull", "--rebase", "--quiet")
        if rc:
            log.warning("memory pull rc=%s: %s", rc, out.strip()[:200])

    def index(self) -> str:
        p = self.repo / "MEMORY.md"
        try:
            return p.read_text()
        except Exception as e:
            return f"(MEMORY.md unreadable: {e})"

    async def commit_leftovers(self, msg: str) -> None:
        """Belt-and-braces: the Claude Code PostToolUse hook normally commits memory writes; catch anything it missed."""
        rc, out = await self._git("status", "--porcelain")
        if rc or not out.strip():
            return
        await self._git("add", "-A")
        rc, out = await self._git("commit", "-q", "-m", msg)
        if rc:
            log.warning("memory commit rc=%s: %s", rc, out.strip()[:200])
            return
        rc, out = await self._git("push", "--quiet", timeout=30)
        if rc:
            log.warning("memory push rc=%s: %s", rc, out.strip()[:200])
