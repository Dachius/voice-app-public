/* Voice App — hands-free voice pipeline.
 *
 * Listening: Silero VAD (vendored @ricky0123/vad-web) cuts the mic into utterances; each one is WAV-encoded and
 * sent to /api/stt (Deepgram). Transcripts accumulate in the composer as "segments" until the turn ends.
 * Turn end: a silence countdown after the last transcript (longer when the text ends mid-sentence, see waitMs), a
 * spoken end command, or the Send button. An utterance still in progress when the countdown fires is carried into
 * the next message rather than lost; utterances that transcribe to nothing do not restart the countdown.
 * Spoken commands (config.voice.commands): hold (freeze the countdown until you speak again), end, scratch
 * (drop the previous segment). Speaking: assistant text is chunked by paragraph as it streams, synthesized via
 * /api/tts (OpenAI) and played in order; the mic is paused from turn start until playback finishes (no barge-in yet).
 */
(() => {
  const $ = (s) => document.querySelector(s);
  const input = $("#input");
  const V = {
    on: false, vad: null, ready: false, loading: false,
    state: "off",            // off | loading | listening | hearing | transcribing | held | thinking | speaking
    segments: [], synced: "", inflight: 0, lastEnd: 0, prevEnd: 0, held: false, pendingEnd: false,
    carry: [],               // transcripts that landed after the turn was sent; become the start of the next message
    turnRunning: false, wake: null, cfg: null, rx: null, tick: null,
  };
  const App = () => window.App;
  const cfg = () => V.cfg || (V.cfg = App()?.state?.config?.voice || {});
  const cid = () => App()?.state?.conv?.id || "";

  // ---------- spoken command matching ----------
  const escRx = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  function buildRx() {
    const c = cfg().commands || {};
    const alts = (k) => (c[k] || []).map(escRx).join("|");
    const tail = (k) => (c[k] || []).length ? new RegExp(`(?:^|[\\s,;:.!?—-]+)(?:${alts(k)})[\\s.!?,]*$`, "i") : null;
    V.rx = {
      end: tail("end"), hold: tail("hold"),
      scratch: (c.scratch || []).length ? new RegExp(`(?:^|[\\s,;:.!?—-]+)(?:${alts("scratch")})[\\s.!?,]*`, "i") : null,
    };
  }

  // ---------- UI ----------
  const bar = $("#voicebar"), stateEl = $("#vstate"), dot = $("#vdot");
  function setState(s) { V.state = s; render(); }
  function render() {
    if (!bar) return;
    bar.hidden = !V.on;
    $("#mic").classList.toggle("on", V.on);
    let label = V.state;
    if (V.state === "listening" && V.lastEnd && input.value.trim()) {
      const left = Math.max(0, Math.ceil((waitMs() - (performance.now() - V.lastEnd)) / 1000));
      label = `listening · sending in ${left}s`;
    } else if (V.state === "listening") label = "listening";
    else if (V.state === "held") label = "holding · say something or tap Resume";
    else if (V.state === "transcribing") label = "transcribing…";
    else if (V.state === "hearing") label = "hearing you…";
    else if (V.state === "thinking") label = "thinking…";
    else if (V.state === "speaking") label = "speaking";
    else if (V.state === "loading") label = "loading voice model…";
    stateEl.textContent = label;
    dot.dataset.state = V.state;
    $("#v-hold").textContent = V.held ? "Resume" : "Hold";
    $("#v-hold").disabled = V.turnRunning;
    $("#v-send").disabled = V.turnRunning || !input.value.trim();
    $("#v-scratch").disabled = V.turnRunning || !V.segments.length;
    $("#v-stop").hidden = !(V.state === "speaking" || V.state === "thinking");
  }
  function syncInput() {
    V.synced = V.segments.join(" ");
    input.value = V.synced;
    V.syncing = true; input.dispatchEvent(new Event("input")); V.syncing = false;
    render();
  }
  function absorbTyped() {
    // If the composer was edited by hand since we last wrote it, treat its content as the current segment list.
    const cur = input.value.trim();
    if (cur !== V.synced.trim()) V.segments = cur ? [cur] : [];
  }

  // ---------- listening ----------
  async function ensureVad() {
    if (V.vad) return V.vad;
    if (typeof vad === "undefined") throw new Error("VAD library not loaded");
    const o = cfg().vad || {};
    V.vad = await vad.MicVAD.new({
      model: o.model || "v5",
      baseAssetPath: "/static/vendor/vad/", onnxWASMBasePath: "/static/vendor/vad/",
      ortConfig: (ort) => { ort.env.wasm.numThreads = 1; ort.env.logLevel = "error"; },
      positiveSpeechThreshold: o.positiveSpeechThreshold ?? 0.6,
      negativeSpeechThreshold: o.negativeSpeechThreshold ?? 0.35,
      redemptionMs: o.redemptionMs ?? 900, preSpeechPadMs: o.preSpeechPadMs ?? 400, minSpeechMs: o.minSpeechMs ?? 250,
      startOnLoad: false,
      // vad-web's default on pause() is to DISCARD an utterance in progress; we want it delivered to onSpeechEnd so
      // that speech cut off by the send countdown is carried into the next message (the carry path
      // never received anything because of this default).
      submitUserSpeechOnPause: true,
      // Mic processing constraints come from config.voice.mic. Chrome's noise suppression makes Deepgram drop all
      // punctuation (tested with a fake mic; AGC alone was harmless), so it is off by default.
      getStream: () => navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: false, autoGainControl: false, ...(cfg().mic || {}) } }),
      // Keep the mic stream open across pause/resume (default vad-web stops the tracks and re-requests
      // getUserMedia, which is slow on phones and hung under test); muting the tracks is enough.
      pauseStream: async (s) => { s.getTracks().forEach((t) => { t.enabled = false; }); },
      resumeStream: async (s) => { s.getTracks().forEach((t) => { t.enabled = true; }); return s; },
      onSpeechStart: () => { if (!V.on || V.turnRunning) return; V.prevEnd = V.lastEnd; V.lastEnd = 0; setState("hearing"); },
      onVADMisfire: () => { if (V.on && !V.turnRunning) { if (!V.lastEnd) V.lastEnd = V.prevEnd; setState(V.held ? "held" : "listening"); } },
      // Speech that ends after the turn was sent (you were mid-utterance when the countdown fired) is kept, not dropped.
      onSpeechEnd: (audio) => { if (!V.on) return; if (V.turnRunning) carryUtterance(audio); else onUtterance(audio); },
    });
    return V.vad;
  }
  async function onUtterance(audio) {
    V.inflight++; setState("transcribing");
    const wav = vad.utils.encodeWAV(audio, 1, 16000, 1, 16);  // 16-bit PCM mono
    V.lastUtteranceS = audio.length / 16000;
    let got = false;
    try {
      const r = await fetch(`/api/stt?cid=${encodeURIComponent(cid())}`, { method: "POST", headers: { "content-type": "audio/wav" }, body: wav });
      if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
      const j = await r.json();
      if (V.on && !V.turnRunning) got = handleTranscript(j.text || "");
    } catch (e) {
      App().setStatus("transcription failed: " + e.message);
    } finally {
      V.inflight--;
      if (V.on && !V.turnRunning) {
        // An utterance that produced no text (noise, or STT missed it) must not restart the countdown from zero,
        // or a silent room keeps extending the wait; resume from where it was before that "speech" began.
        V.lastEnd = got ? performance.now() : (V.prevEnd || performance.now());
        if (V.state === "transcribing") setState(V.held ? "held" : "listening");
        if (V.pendingEnd && !V.inflight) { V.pendingEnd = false; endTurn(); }
      }
      render();
    }
  }
  function flash(t) { App().setStatus(t); setTimeout(() => { if (App().state.streaming == null) App().setStatus(""); }, 2500); }
  // Transcribe an utterance that finished after the turn went out and park it for the next message.
  async function carryUtterance(audio) {
    const wav = vad.utils.encodeWAV(audio, 1, 16000, 1, 16);
    try {
      const r = await fetch(`/api/stt?cid=${encodeURIComponent(cid())}`, { method: "POST", headers: { "content-type": "audio/wav" }, body: wav });
      if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
      const t = ((await r.json()).text || "").trim();
      if (!t || !V.on) return;
      if (V.turnRunning) { V.carry.push(t); flash("kept what you were saying for your next message"); }
      else { absorbTyped(); V.segments.push(t); syncInput(); V.lastEnd = performance.now(); }
    } catch (e) {
      App().setStatus("transcription failed: " + e.message);
    }
  }
  // Returns true if the transcript changed the composer (so the countdown should restart), false if it was empty.
  function handleTranscript(text) {
    let t = text.trim();
    if (!t) return false;
    absorbTyped();
    const rx = V.rx;
    if (rx.scratch) {
      const m = rx.scratch.exec(t);
      if (m) {
        const before = t.slice(0, m.index).trim(), after = t.slice(m.index + m[0].length).trim();
        // "Scratch that" alone, or with a short lead-in ("actually, scratch that"), drops the previous segment;
        // a longer run of words before it is content you are retracting in the same breath.
        const leadIn = before.split(/\s+/).filter(Boolean).length <= 2;
        if (leadIn) V.segments.pop();
        flash(leadIn ? "scratched the last segment" : "scratched what you just said");
        t = after;
        if (!t) { syncInput(); return true; }
      }
    }
    if (rx.hold && rx.hold.test(t)) {
      t = t.replace(rx.hold, "").trim();
      if (t) V.segments.push(t);
      V.held = true; syncInput(); setState("held"); flash("holding, take your time");
      return true;
    }
    if (rx.end && rx.end.test(t)) {
      t = t.replace(rx.end, "").trim();
      if (t) V.segments.push(t);
      V.held = false; syncInput(); endTurn();
      return true;
    }
    V.segments.push(t);
    V.held = false; syncInput(); setState("listening");
    return true;
  }
  function endTurn() {
    if (V.inflight) { V.pendingEnd = true; return; }
    if (V.turnRunning) return;
    if (!input.value.trim()) { render(); return; }
    V.segments = []; V.synced = ""; V.held = false; V.lastEnd = 0; V.pendingEnd = false;
    App().sendUser();
  }
  function tickFn() {
    if (!V.on || V.turnRunning || V.held || V.inflight || !V.lastEnd) return render();
    if (!input.value.trim()) return render();
    if (performance.now() - V.lastEnd >= waitMs()) endTurn();
    else render();
  }
  // Silence to wait before sending. Longer when the composer text does not end in terminal punctuation: Deepgram
  // punctuates, so a missing period means it heard you stop mid-sentence (thinking), not finish one.
  function waitMs() {
    const c = cfg();
    let s = c.silence_timeout_s || 4;
    const t = input.value.trim();
    if (t && !/[.!?…]["'”’)\]]*$/.test(t)) s += c.unfinished_extra_s || 0;
    return s * 1000;
  }

  // ---------- speaking ----------
  const speaker = {
    audio: null, queue: [], playing: false, finished: false, abort: null, idx: 0,
    reset() { this.stop(); this.finished = false; this.queue = []; this.idx = 0; this.abort = new AbortController(); },
    stop() {
      if (this.abort) this.abort.abort();
      this.abort = null;
      for (const c of this.queue) if (c.url) URL.revokeObjectURL(c.url);
      this.queue = []; this.playing = false; this.finished = true;
      if (this.audio) { try { this.audio.pause(); } catch {} this.audio.removeAttribute("src"); }
    },
    enqueue(text) {
      const clean = cleanForSpeech(text);
      if (!clean) return;
      for (const piece of splitLong(clean, 3500)) this.queue.push({ text: piece, blob: null, fetching: false, url: null });
      this.pump();
    },
    async pump() {
      // Fetch at most two chunks ahead of the one being played, then play in order.
      for (const c of this.queue.slice(this.idx, this.idx + 2)) if (!c.fetching) { c.fetching = true; c.blob = this.fetchOne(c); }
      if (!this.playing) this.playNext();
    },
    async fetchOne(c) {
      const tts = App().state.config.tts || {};
      const voice = localStorage.getItem("ttsVoice") || tts.voice;
      const r = await fetch(`/api/tts?cid=${encodeURIComponent(cid())}`, {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text: c.text, voice }), signal: this.abort?.signal });
      if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
      return r.blob();
    },
    async playNext() {
      if (this.idx >= this.queue.length) {
        this.playing = false;
        if (this.finished) onSpeechDone();
        return;
      }
      this.playing = true;
      const c = this.queue[this.idx];
      try {
        setState("speaking");
        const blob = await c.blob;
        if (!this.queue.includes(c)) return;  // stopped meanwhile
        c.url = URL.createObjectURL(blob);
        await new Promise((res, rej) => {
          this.audio.onended = res; this.audio.onerror = () => rej(new Error("audio playback failed"));
          this.audio.src = c.url;
          this.audio.playbackRate = parseFloat(localStorage.getItem("ttsSpeed") || App().state.config.tts?.speed || 1) || 1;  // speed is applied here, not by the TTS API
          this.audio.play().catch(rej);
        });
      } catch (e) {
        if (e.name !== "AbortError") App().setStatus("speech failed: " + e.message);
        if (!this.queue.includes(c)) return;
      } finally {
        if (c.url) { URL.revokeObjectURL(c.url); c.url = null; }
      }
      this.idx++;
      this.playing = false;
      this.pump();
    },
    finish() { this.finished = true; if (!this.playing && this.idx >= this.queue.length) onSpeechDone(); },
  };
  function cleanForSpeech(s) {
    return s
      .replace(/```[\s\S]*?```/g, " (code shown on screen) ")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .replace(/^#{1,6}\s+/gm, "")
      .replace(/^\s*[-*+]\s+/gm, "")
      .replace(/\*\*|__/g, "")
      .replace(/(^|\s)[*_](\S[^*_]*\S)[*_](?=\s|$)/g, "$1$2")
      .replace(/[ \t]+\n/g, "\n").trim();
  }
  function splitLong(s, max) {
    const out = [];
    while (s.length > max) {
      let cut = s.lastIndexOf(". ", max); if (cut < max / 2) cut = s.lastIndexOf(" ", max); if (cut < 0) cut = max;
      out.push(s.slice(0, cut + 1).trim()); s = s.slice(cut + 1);
    }
    if (s.trim()) out.push(s.trim());
    return out;
  }
  // Streams assistant text into TTS chunks; stops at a "---" line (screen-only tail).
  // Cuts at paragraph breaks, and also at sentence ends so that speech starts after the first sentence instead of
  // after the whole paragraph: the first chunk goes out as soon as one sentence of FIRST_MIN chars is complete,
  // later ones whenever LATER_MIN chars of pending text end in a sentence (a longer window keeps the number of TTS
  // requests down and gives the voice more context per clip). Never cuts inside an unclosed ``` fence.
  const FIRST_MIN = 40, LATER_MIN = 220;
  const SENT_END = /[.!?…]["'”’)\]]*\s/g;
  const chunker = {
    full: "", at: 0, cut: false, n: 0,
    reset() { this.full = ""; this.at = 0; this.cut = false; this.n = 0; },
    push(t) {
      if (this.cut) return;
      this.full += t;
      const rest = this.full.slice(this.at);
      const m = /(^|\n)\s*---\s*(\n|$)/.exec(rest);
      if (m) { this.emit(this.at, this.at + m.index); this.at = this.full.length; this.cut = true; return; }
      let i;
      while ((i = this.full.indexOf("\n\n", this.at)) >= 0) { this.emit(this.at, i); this.at = i + 2; }
      this.sentenceCut();
    },
    sentenceCut() {
      const pending = this.full.slice(this.at);
      const min = this.n ? LATER_MIN : FIRST_MIN;
      if (pending.length < min) return;
      if ((pending.match(/```/g) || []).length % 2) return;  // inside a code fence
      let mm;
      SENT_END.lastIndex = 0;
      while ((mm = SENT_END.exec(pending))) {
        const end = mm.index + mm[0].length;
        if (end >= min) { this.emit(this.at, this.at + end); this.at += end; return; }  // first sentence end past the window
      }
    },
    break() { if (!this.cut) { this.emit(this.at, this.full.length); this.at = this.full.length; } },
    flush() { this.break(); },
    emit(a, b) { const s = this.full.slice(a, b).trim(); if (s) { this.n++; speaker.enqueue(s); } },
  };
  async function onSpeechDone() {
    if (!V.on) return;
    V.turnRunning = false;
    V.lastEnd = 0; V.pendingEnd = false;
    try { await V.vad.start(); } catch (e) { App().setStatus("mic restart failed: " + e.message); }
    if (V.carry.length) {
      // Speech cut off by the previous send starts this message, but a fragment alone is not a message: hold
      // (no countdown) until you continue, say an end command, or tap Send. (Originally the countdown
      // started immediately and a silent user got "and I'm" sent as a whole turn.)
      V.segments = V.carry.slice(); V.carry = []; V.held = true;
      syncInput(); flash("kept what you were saying · continue, or say go ahead");
    }
    setState(V.held ? "held" : "listening");
  }

  // ---------- turn hooks (called from app.js) ----------
  const hooks = {
    async onTurnStart() {
      if (!V.on) return;
      V.turnRunning = true; V.lastEnd = 0;
      speaker.reset(); chunker.reset();
      try { await V.vad.pause(); } catch {}
      setState("thinking");
    },
    onTextStart() { if (V.on) chunker.break(); },
    onDelta(t) { if (V.on) chunker.push(t); },
    onTurnEnd(msg) {
      if (!V.on) return;
      if (!V.turnRunning) return;  // playback was stopped by hand and listening already resumed
      chunker.flush();
      if (msg?.error) App().setStatus(msg.error);
      speaker.finish();
    },
  };

  // ---------- wake lock ----------
  async function wake(on) {
    try {
      if (on && !V.wake && navigator.wakeLock) { V.wake = await navigator.wakeLock.request("screen"); V.wake.onrelease = () => { V.wake = null; }; }
      else if (!on && V.wake) { await V.wake.release(); V.wake = null; }
    } catch {}
  }
  document.addEventListener("visibilitychange", () => { if (V.on && document.visibilityState === "visible") wake(true); });

  // ---------- on/off ----------
  async function turnOn() {
    if (!App()?.state?.conv) { App()?.setStatus("open a conversation first"); return; }
    V.cfg = null; buildRx();
    if (!speaker.audio) { speaker.audio = $("#tts"); speaker.audio.load(); }  // touch the element inside the tap gesture
    V.on = true; setState("loading");
    try {
      await ensureVad();
      await V.vad.start();
    } catch (e) {
      V.on = false; setState("off"); App().setStatus("voice unavailable: " + e.message); return;
    }
    V.turnRunning = false; V.lastEnd = 0; V.held = false; V.segments = []; V.synced = input.value;
    if (App().state.conv) { App().state.conv.mode = "voice"; App().renderSubtitle(); }
    setState(App().state.streaming ? "thinking" : "listening");
    if (App().state.streaming) { V.turnRunning = true; await V.vad.pause(); }
    wake(true);
    V.tick = setInterval(tickFn, 200);
  }
  async function turnOff() {
    V.on = false; clearInterval(V.tick); V.tick = null;
    speaker.stop(); chunker.reset();
    try { await V.vad?.pause(); } catch {}
    V.turnRunning = false; V.held = false; V.pendingEnd = false;
    if (App().state.conv) { App().state.conv.mode = "text"; App().renderSubtitle(); }
    wake(false); setState("off");
  }

  // ---------- wiring ----------
  $("#mic").onclick = () => (V.on ? turnOff() : turnOn());
  $("#v-hold").onclick = () => { V.held = !V.held; if (!V.held) V.lastEnd = performance.now(); setState(V.held ? "held" : "listening"); };
  $("#v-send").onclick = () => { V.held = false; endTurn(); };
  $("#v-scratch").onclick = () => { absorbTyped(); V.segments.pop(); syncInput(); V.lastEnd = performance.now(); };
  $("#v-stop").onclick = () => {
    if (V.state === "speaking") { speaker.stop(); chunker.cut = true; onSpeechDone(); }
    else App().send({ type: "interrupt" });
  };
  input.addEventListener("input", () => { if (V.on && !V.turnRunning && !V.syncing) V.lastEnd = performance.now(); });

  window.Voice = { isOn: () => V.on, ...hooks, off: turnOff, state: V };
})();
