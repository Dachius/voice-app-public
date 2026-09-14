"""Speech I/O: Deepgram prerecorded STT and OpenAI TTS, both pay-per-use via API keys in the service env."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any
from urllib.parse import urlencode

import httpx

log = logging.getLogger("media")


class STT:
    """Deepgram prerecorded transcription of one whole utterance (WAV/opus/anything Deepgram sniffs)."""

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.key = os.environ.get("DEEPGRAM_API_KEY", "")
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))

    async def transcribe(self, audio: bytes, content_type: str) -> dict[str, Any]:
        if not self.key:
            raise RuntimeError("DEEPGRAM_API_KEY is not set in the service environment")
        params: list[tuple[str, str]] = [
            ("model", self.cfg.get("model", "nova-3")),
            ("language", self.cfg.get("language", "en")),
            ("smart_format", "true"),
            ("punctuate", "true"),
        ]
        # Nova-3 keyterm prompting: bias recognition toward the spoken turn commands and any custom vocabulary.
        for kt in self.cfg.get("keyterms", []):
            params.append(("keyterm", kt))
        url = "https://api.deepgram.com/v1/listen?" + urlencode(params)
        headers = {"Authorization": f"Token {self.key}", "Content-Type": content_type or "audio/wav"}
        # Retry transport failures and 5xx: the pooled keep-alive connection goes stale between utterances and
        # Deepgram then closes it without a response ("Server disconnected"). A dropped utterance is
        # lost speech, so a couple of quick retries are worth far more than the extra second they cost.
        attempts = int(self.cfg.get("retries", 2)) + 1
        for i in range(attempts):
            try:
                r = await self.client.post(url, content=audio, headers=headers)
            except httpx.TransportError as e:
                if i + 1 >= attempts:
                    raise
                log.warning("deepgram transport error (attempt %d/%d): %s", i + 1, attempts, e)
                await asyncio.sleep(0.3 * (i + 1))
                continue
            if r.status_code >= 500 and i + 1 < attempts:
                log.warning("deepgram %s (attempt %d/%d)", r.status_code, i + 1, attempts)
                await asyncio.sleep(0.3 * (i + 1))
                continue
            break
        if r.status_code != 200:
            raise RuntimeError(f"deepgram {r.status_code}: {r.text[:300]}")
        j = r.json()
        alt = (((j.get("results") or {}).get("channels") or [{}])[0].get("alternatives") or [{}])[0]
        return {
            "text": (alt.get("transcript") or "").strip(),
            "confidence": alt.get("confidence"),
            "duration": (j.get("metadata") or {}).get("duration"),
        }


class TTS:
    """OpenAI speech synthesis (gpt-4o-mini-tts by default), streamed straight through to the browser."""

    MAX_INPUT = 4096  # API limit on `input` characters

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.key = os.environ.get("OPENAI_API_KEY", "")
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))

    @property
    def media_type(self) -> str:
        fmt = self.cfg.get("format", "mp3")
        return {"mp3": "audio/mpeg", "opus": "audio/ogg", "aac": "audio/aac", "wav": "audio/wav"}.get(fmt, "application/octet-stream")

    async def synthesize(self, text: str, voice: str | None = None, speed: float | None = None, instructions: str | None = None) -> bytes:
        """Whole-clip synthesis. (Streaming the upstream body through Starlette lost the tail of the audio, and the
        client plays paragraph-sized chunks anyway, so buffering costs little.)"""
        if not self.key:
            raise RuntimeError("OPENAI_API_KEY is not set in the service environment")
        body: dict[str, Any] = {
            "model": self.cfg.get("model", "gpt-4o-mini-tts"),
            "input": text[: self.MAX_INPUT],
            "voice": voice or self.cfg.get("voice", "marin"),
            "response_format": self.cfg.get("format", "mp3"),
        }
        instr = instructions if instructions is not None else self.cfg.get("instructions")
        if str(body["model"]).startswith("gpt-4o"):
            # gpt-4o-mini-tts: `instructions` steers delivery; `speed` makes it drop the last sentence (tested),
            # so playback rate is applied in the browser instead.
            if instr:
                body["instructions"] = instr
        elif speed:
            body["speed"] = speed
        r = await self.client.post("https://api.openai.com/v1/audio/speech", json=body, headers={"Authorization": f"Bearer {self.key}"})
        if r.status_code != 200:
            raise RuntimeError(f"openai tts {r.status_code}: {r.text[:300]}")
        if not r.content:
            raise RuntimeError("openai tts returned empty audio")
        return r.content
