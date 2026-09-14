# Disclaimer

Everything in this repo except this disclaimer and the license was written by an AI.

# Voice App

Single-user, self-hosted chat PWA that drives the vendors' own CLI harnesses under existing
subscriptions (no API-priced LLM calls):

- **Claude** via the Claude Agent SDK → the logged-in Claude Code CLI (`claude` user on the VM, Claude subscription).
- **OpenAI** via `codex exec --json` under ChatGPT sign-in (`codex login --device-auth` as the `claude` user).

Speech (STT/TTS) is the one pay-per-use part; it is cheap enough not to matter (rates in `config.json`).

## Layout

```
app/
  server.py            FastAPI: token cookie gate, REST for conversations, websocket chat, PWA routes
  store.py             one JSON file per conversation under data/conversations/
  memory.py            git pull before a turn, MEMORY.md index for the prompt, commit/push leftovers after
  backends/            claude_backend.py (Agent SDK), codex_backend.py (codex exec --json)
  prompts/system.md    the system prompt template; style_text.md / style_voice.md are swapped in by mode
  media.py             Deepgram prerecorded STT + OpenAI TTS (pay-per-use, keys from .env)
  static/              PWA (index.html, app.js, style.css, sw.js, manifest, icons, vendored marked.js)
  static/voice.js      hands-free voice pipeline (VAD, segments, spoken commands, TTS playback queue)
  static/vendor/vad/   @ricky0123/vad-web 0.0.30 bundle + Silero models + onnxruntime-web 1.22 wasm
  config.json          models, permission policy, paths, stt/tts/voice settings
deploy.sh              from a workstation: rsync app/ → <vm>:/home/claude/voice-app over ssh and restart the service
deploy-vm.sh           from a clone on the VM itself: same sync locally + restart; `--no-restart` for static-only
                       changes. Pick one clone as canonical and pull before deploying from the other.
voice-app.service      systemd unit (runs as `claude`, uvicorn on 127.0.0.1:8770)
research/              SDK cheat sheet, TTS sample clip notes + pricing snapshot
```

`deploy.sh` assumes an ssh alias `dev` for the VM; adjust to taste.

## Runtime state on the VM (not in git)

- `/home/claude/voice-app/token` — the login secret (any random string of 20+ chars). Visit `/login?t=<token>` once per device.
- `/home/claude/voice-app/.env` — API keys for STT/TTS (`DEEPGRAM_API_KEY`, `OPENAI_API_KEY`) and `GH_TOKEN`
  (for pushing the memory repo), loaded by systemd.
- `/home/claude/voice-app/data/` — conversations.
- `/home/claude/.claude/memory` — a git repo of memory notes with a `MEMORY.md` index, injected into every system
  prompt (see `prompts/system.md`; drop the Memory section if you do not use one).
- `/home/claude/.local/bin/codex` **and** `/home/claude/.local/bin/codex-code-mode-host` — both from the same
  GitHub release (`rust-v<ver>`, assets `codex-x86_64-unknown-linux-musl.tar.gz` and
  `codex-code-mode-host-x86_64-unknown-linux-musl.tar.gz`). GPT-6 Astra and the GPT-5.6 family are
  `code_mode_only` models: every tool call goes through the helper, and without it the model gets
  "failed to spawn code-mode host ... No such file or directory" for even `pwd`. Upgrade both
  together. `bubblewrap` (apt) is also required or the sandbox panics and every command needs escalation.

## Warm Claude sessions

`backends/claude_backend.py` keeps one connected `ClaudeSDKClient` (one `claude` process) per conversation and
reuses it across turns instead of spawning + `--resume`-ing every time (measured: ~1 s per turn warm
vs ~4–5 s cold). It is rebuilt (with `resume`) when the system prompt or model changes (mode switch, memory index
edits, date rollover), after a failed turn, after `claude_idle_close_s` without a turn, or LRU beyond
`claude_max_warm`. Reported per-turn cost is the delta of the process-cumulative `total_cost_usd`.
Page reloads between turns keep the process; a service restart still kills whatever is running.

## Tool permissions

`config.json → tool_permission_policy` (default `"ask"`): `"ask"` forwards anything Claude Code would prompt for to the
phone UI (allow/deny buttons, denied after `permission_prompt_timeout_s`); `"allow"` auto-approves.
The Claude Code auto-mode classifier still runs first, so routine commands never prompt either way.
Codex flags live in `codex_extra_args` (default `--approve-for-me`, Codex's classifier-reviewed auto mode inside a workspace-write sandbox).

## Voice mode

Tap the mic button in the composer. Everything is hands-free from there:

1. **Listening.** Silero VAD (in the browser, `vad-web`) cuts the mic into utterances. Each one is
   WAV-encoded and POSTed to `/api/stt` (Deepgram Nova-3); the transcript is appended to the composer as a
   segment, so you can watch what was heard while you keep talking.
2. **Ending a turn.** A silence countdown (`voice.silence_timeout_s`, default 20 s, plus
   `voice.unfinished_extra_s` when the text does not end in terminal punctuation, default 0) starts after each
   transcript arrives and sends the composer text when it expires. Say _go ahead_ to skip the wait. Spoken commands are matched on the
   transcript (`voice.commands`, matched at the end of an utterance and stripped from the text):
   - _hold on / let me think / hang on …_ freezes the countdown until you say something else,
   - _go ahead / over / send it …_ ends the turn now,
   - _scratch that / strike that …_ drops the previous segment (or the words before it in the same breath).

   The voice bar has Hold / Send / Scratch / Stop buttons for the same things, and typing in the composer
   also works (typed text counts as the current segment).

3. **Speaking.** The reply is chunked at paragraph breaks as it streams, each chunk synthesized via
   `/api/tts` (OpenAI `gpt-4o-mini-tts`, voice/speed selectable in the drawer, speed applied as playback rate)
   and played in order. The mic tracks are muted from turn start until playback ends; no barge-in yet.
   Text after a line containing only `---` is shown but not spoken (see `prompts/style_voice.md`).

Screen wake lock is held while voice mode is on. Speech usage (STT seconds, TTS characters) accumulates
per conversation under `media` and shows as an estimated cost in the subtitle (rates in config).

Empirical gotchas (all verified with a fake-mic headless Chrome run):

- Chrome **noise suppression** makes Deepgram return unpunctuated transcripts; it is off by default
  (`voice.mic`). AGC and echo cancellation are harmless.
- Deepgram **keyterm** biasing of the command phrases also killed punctuation; only proper nouns are passed.
- `gpt-4o-mini-tts` **drops the last sentence** when the `speed` field is sent, so it is never sent to
  that model. It also occasionally drops a trailing short sentence on its own (1 of 9 runs).
- Streaming the OpenAI audio body through Starlette truncated the tail; the endpoint buffers the clip.
- A short silence timeout (4–6 s) sends half-thoughts whenever you pause to think, and punctuation is not a
  reliable "finished" signal either; a flat 20 s with _go ahead_ as the escape hatch worked best in practice.

End-to-end testing: launch headless Chrome with `--use-file-for-fake-audio-capture=<wav>` (e.g. from a small
puppeteer script) and drive a full listen → send → speak cycle against the live site.

## Ops

```
./deploy.sh                                   # sync + restart
ssh dev sudo journalctl -u voice-app -f       # logs
ssh dev sudo cat /home/claude/voice-app/token # login secret
```

Routing: put an nginx vhost (or any reverse proxy with websocket upgrade) in front of 127.0.0.1:8770 and
expose it however you like (a Cloudflare tunnel works well; the app itself only listens on localhost).
