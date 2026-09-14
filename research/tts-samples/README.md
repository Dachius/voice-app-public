# TTS sample clips: ElevenLabs vs OpenAI

All clips are vendor-published marketing/docs audio, so they are
best-case, hand-picked outputs, not random API results. For a fair A/B, the next step is to
generate the same sentence through both APIs yourself (see "Caveats" below).

## Downloaded files

The clips themselves are not in git (`*.mp3` / `*.wav` under this directory are ignored); the table records what was
fetched and from where so the comparison can be reproduced.

| File | Vendor / model | Voice | Dur | Source | Caveat |
|---|---|---|---|---|---|
| `elevenlabs-v3-jessica-capricorn.mp3` | ElevenLabs Eleven v3 | Jessica (premade, US female, "playful, bright, warm") | 19 s | https://elevenlabs.io/blog/eleven-v3 (CDN: https://eleven-public-cdn.elevenlabs.io/payloadcms/ky6ru6bv00p-Jessica%20-%20Capricorn.mp3) | v3 launch-blog showcase; uses audio tags, marketing-selected |
| `elevenlabs-v3-britney-narration.wav` | ElevenLabs Eleven v3 | "Britney" (narration) | 16 s | https://elevenlabs.io/blog/eleven-v3 (CDN: https://eleven-public-cdn.elevenlabs.io/payloadcms/dkvbr9y46rm-009.%20Britney%20-%20I%20couldn%C3%A2t%20sleep%20that%20night%20(narration).wav) | Narrative style rather than conversational; 4.5 MB WAV |
| `elevenlabs-v3-marissa-bunny.mp3` | ElevenLabs Eleven v3 | "Marissa" | 19 s | https://elevenlabs.io/blog/eleven-v3 (CDN: https://eleven-public-cdn.elevenlabs.io/payloadcms/26zxs12764c-004.%20Marissa%20-%20Bunny%20rabbit%20was%20soooo%20cute.mp3) | Casual conversational monologue with [laughs]/[giggle] tags; showcase |
| `elevenlabs-v3-mark-chris-dialogue.mp3` | ElevenLabs Eleven v3 (Text to Dialogue) | "Mark" + "Chris", two speakers | 29 s | https://elevenlabs.io/v3 (CDN: https://eleven-public-cdn.elevenlabs.io/payloadcms/acmrrbz64tu-BADJOKES%20FINAL.mp3) | Knock-knock-joke dialogue; shows multi-speaker + [chuckles] tags; showcase |
| `elevenlabs-voicepreview-roger.mp3` | ElevenLabs voice-library preview (model not stated; voice lists `eleven_multilingual_v2` / `eleven_flash_v2_5` as high-quality base models) | Roger (premade, US male, middle-aged, "laid-back, casual, resonant", use case: conversational) | 4 s | `GET https://api.elevenlabs.io/v1/voices` -> `preview_url` = https://storage.googleapis.com/eleven-public-prod/premade/voices/CwhRBWXzGAHq8TQ4Fs17/58ee3ff5-f6f2-4628-93b8-e38eb31806b0.mp3 | Short 56 kbps preview; generation model unspecified (v2-era library preview, NOT v3) |
| `elevenlabs-voicepreview-jessica.mp3` | ElevenLabs voice-library preview (as above) | Jessica (premade, US female, young, conversational) | 4 s | https://storage.googleapis.com/eleven-public-prod/premade/voices/cgSgspJ2msm6clMCkdW9/56a97bf8-b69b-448f-846c-c3a11683d45a.mp3 | Same voice as the v3 Capricorn clip, so you can compare v3 vs library-preview rendering of one voice |
| `elevenlabs-voicepreview-chris.mp3` | ElevenLabs voice-library preview (as above) | Chris (premade, US male, middle-aged, "charming, down-to-earth", conversational) | 3 s | https://storage.googleapis.com/eleven-public-prod/premade/voices/iP95p4xoKVk53GoZ742B/3f4bde72-cc48-40dd-829f-57fbf906f4d7.mp3 | Short preview, model unspecified |
| `elevenlabs-ttspage-english-demo.mp3` | ElevenLabs (model not stated) | Unnamed voice (voice id NOpBlnGInO9m6vDvFkFC), English | ~13 s | https://elevenlabs.io/text-to-speech language-demo widget (CDN: https://storage.googleapis.com/eleven-public-prod/database/workspace/64971298bfc24086b69026970a21f1f9/voices/NOpBlnGInO9m6vDvFkFC/M4xySW4rr1SbAKKwMAtI.mp3) | Landing-page demo, model/voice not identified in page data |
| `openai-docs-alloy.wav` | OpenAI TTS docs sample (model not stated; 16 kHz PCM, original 2023 voice -> almost certainly tts-1 / tts-1-hd era) | alloy | 7 s | https://platform.openai.com/docs/guides/text-to-speech (CDN: https://cdn.openai.com/API/docs/audio/alloy.wav) | The only sample actually embedded on the docs page; older-generation render |
| `openai-docs-nova.wav` | OpenAI TTS docs sample (16 kHz, 2023 voice, same caveat) | nova | 9 s | https://cdn.openai.com/API/docs/audio/nova.wav | Same CDN path pattern, not linked from the current docs page |
| `openai-docs-ash.wav` | OpenAI TTS docs sample (24 kHz PCM; ash/coral/sage shipped with gpt-4o-mini-tts in Mar 2025, so very likely a gpt-4o-mini-tts render) | ash | 10 s | https://cdn.openai.com/API/docs/audio/ash.wav | Model inferred from voice launch date + 24 kHz default output; not confirmed by OpenAI |
| `openai-docs-coral.wav` | OpenAI TTS docs sample (24 kHz, same inference) | coral | 12 s | https://cdn.openai.com/API/docs/audio/coral.wav | As above |
| `openai-docs-sage.wav` | OpenAI TTS docs sample (24 kHz, same inference) | sage | 10 s | https://cdn.openai.com/API/docs/audio/sage.wav | As above |

Also available on the same OpenAI CDN path but not downloaded: `echo.wav`, `fable.wav`, `onyx.wav`,
`shimmer.wav`. Not present (404): `ballad`, `verse`, `marin`, `cedar` (the newest voices; docs currently
recommend `marin` or `cedar` for best quality, and these only exist on openai.fm / via the API).

## Sample pages that could not be downloaded from

- https://www.openai.fm/ - interactive demo for gpt-4o-mini-tts (all 13 voices incl. marin/cedar, with style
  prompts). Behind a Vercel security checkpoint for curl; audio is generated live by the API, no static files.
  Best place to hear the current OpenAI model in a browser.
- https://openai.com/index/introducing-our-next-generation-audio-models/ - launch post for
  gpt-4o-mini-tts / gpt-4o-transcribe with embedded samples; openai.com serves a JS challenge page to curl.
- https://elevenlabs.io/v3 - has additional v3 showcase clips (football commentary, pirate character,
  overlapping-speech dialogue) at eleven-public-cdn.elevenlabs.io/payloadcms/...; downloadable but skipped
  as non-conversational.
- https://elevenlabs.io/docs/models - model comparison table (v3, Multilingual v2, Flash v2.5, Turbo v2.5,
  v3 Conversational); no embedded audio in the static HTML.
- https://elevenlabs.io/blog/introducing-eleven-flash - no direct media URLs in the static HTML, so no
  Flash-specific sample was obtained. The voice-library previews above are the closest proxy for v2/Flash
  quality.

## Pricing (snapshot at time of research; check the vendor pages)

### ElevenLabs

Source: https://elevenlabs.io/pricing/api (monthly billing tab). "Characters" are billed per model;
v3 and Multilingual v2 cost 2x the Flash/Turbo/v3-Conversational rate.

| Plan | Price / mo | Included TTS (v3-rate characters) |
|---|---|---|
| Free / Pay as you go | $0 | pay per use at the rates below (free tier: 10,000 chars, ~10 min) |
| Starter | $6 | 60,000 (~60 min) |
| Creator | $22 (first month $11) | 220,000 (~220 min) |
| Pro | $99 | 990,000 (~990 min) |
| Scale | $299 | 2,990,000 |
| Business | $990 | 9,900,000 |

Per-model rates (pay-as-you-go / overage):

| Model | Rate |
|---|---|
| Eleven v3 | $0.10 / 1K chars (~$0.10/min) |
| Multilingual v2 | $0.10 / 1K chars |
| v3 Conversational (~280 ms latency) | $0.05 / 1K chars |
| Flash / Turbo (v2.5, ~75 ms) | $0.05 / 1K chars |
| Scribe v2 (STT, batch) | $0.22 / hour (~$0.0037/min) |
| Scribe v2 Realtime (STT) | $0.39 / hour (~$0.0065/min) |
| Speech Engine (agents, all-in) | $0.08 / min |

### OpenAI

Source: https://platform.openai.com/docs/pricing (audio-model tables; openai.com/api/pricing returned 403).
Note: gpt-4o-mini-tts, tts-1 and tts-1-hd are now in the collapsed "older models" section of the table;
the headline audio models are gpt-realtime-2.1 / gpt-audio.

| Model | Price | Approx per minute |
|---|---|---|
| gpt-4o-mini-tts | $0.60 / 1M text input tokens + $12.00 / 1M audio output tokens | ~$0.015 / min (OpenAI's earlier published estimate; today's page lists token rates only) |
| tts-1 | $15.00 / 1M characters | ~$0.015 / min at ~1,000 chars/min |
| tts-1-hd | $30.00 / 1M characters | ~$0.030 / min |
| gpt-4o-transcribe | $2.50 / 1M audio input, $10.00 / 1M text output | $0.006 / min |
| gpt-4o-mini-transcribe | $1.25 / 1M audio input, $5.00 / 1M text output | $0.003 / min |
| gpt-4o-transcribe-diarize | $2.50 / $10.00 | $0.006 / min |
| gpt-transcribe (newer) | - | $0.0045 / min |
| gpt-live-transcribe / gpt-realtime-whisper (streaming) | - | $0.017 / min |
| whisper-1 ("Whisper") | - | $0.006 / min |
| gpt-realtime-2.1 (speech-to-speech, for reference) | audio $32 in / $64 out per 1M tokens | - |
| gpt-realtime-2.1-mini | audio $10 in / $20 out per 1M tokens | - |

### Deepgram (STT)

Source: https://deepgram.com/pricing (Pay As You Go tab). Free credit: **$200 on signup, no credit card**,
still offered.

| Model | Streaming | Pre-recorded |
|---|---|---|
| Nova-3 English | $0.0048 / min (promo; regular $0.0077) | $0.0043 / min |
| Nova-3 Multilingual | $0.0058 / min (promo; regular $0.0092) | $0.0052 / min |
| Flux English (newer conversational STT) | $0.0065 / min (regular $0.0077) | - |
| Flux Multilingual | $0.0078 / min | - |
| Aura-2 TTS | $0.030 / 1K chars | |
| Aura-1 TTS | $0.015 / 1K chars | |

### Quick comparison, per minute of TTS output (approx, at ~1,000 chars/min)

- OpenAI gpt-4o-mini-tts: ~$0.015
- ElevenLabs Flash / v3 Conversational: ~$0.05 (pay-as-you-go), less on plans
- ElevenLabs v3 / Multilingual v2: ~$0.10
- OpenAI tts-1-hd: ~$0.03

## Caveats

- Every clip here was chosen by the vendor. The ElevenLabs v3 clips in particular are heavily
  produced (audio tags, dialogue, emotional performances) and were likely regenerated many times.
- The OpenAI docs clips are plain, un-styled renders of a short sentence and the older ones (16 kHz)
  do not represent gpt-4o-mini-tts. To hear current OpenAI quality, use openai.fm with `marin`/`cedar`.
- Sample rates differ (16/24 kHz WAV vs 44.1/48 kHz MP3), which itself biases perceived quality.
- Recommended next step: script the same 3-4 conversational sentences through both APIs
  (ElevenLabs v3 + Flash v2.5, OpenAI gpt-4o-mini-tts with marin/cedar) and blind-compare.
