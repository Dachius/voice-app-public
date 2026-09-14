"""Conversation persistence: one JSON file per conversation under data/conversations."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, data_dir: Path):
        self.dir = data_dir / "conversations"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, cid: str) -> Path:
        if not cid.replace("-", "").isalnum():
            raise ValueError("bad id")
        return self.dir / f"{cid}.json"

    def create(self, backend: str, model: str, mode: str = "text") -> dict[str, Any]:
        now = time.time()
        conv = {
            "id": uuid.uuid4().hex[:12],
            "title": "New conversation",
            "backend": backend,
            "model": model,
            "mode": mode,
            "created": now,
            "updated": now,
            "session_id": None,
            "messages": [],
            "total_cost_usd": 0.0,
        }
        self.save(conv)
        return conv

    def load(self, cid: str) -> dict[str, Any] | None:
        p = self._path(cid)
        if not p.exists():
            return None
        return json.loads(p.read_text())

    def save(self, conv: dict[str, Any]) -> None:
        conv["updated"] = time.time()
        p = self._path(conv["id"])
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(conv, indent=1))
        os.replace(tmp, p)

    def delete(self, cid: str) -> bool:
        p = self._path(cid)
        if p.exists():
            p.unlink()
            return True
        return False

    def list(self) -> list[dict[str, Any]]:
        out = []
        for p in self.dir.glob("*.json"):
            try:
                c = json.loads(p.read_text())
            except Exception:
                continue
            out.append({k: c.get(k) for k in ("id", "title", "backend", "model", "mode", "created", "updated")}
                       | {"n": len(c.get("messages", []))})
        out.sort(key=lambda c: c["updated"] or 0, reverse=True)
        return out
