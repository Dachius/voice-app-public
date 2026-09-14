/* Voice App — chat client. Text mode here; the hands-free voice pipeline lives in voice.js and hooks in via window.Voice. */
(() => {
  const $ = (s) => document.querySelector(s);
  const transcript = $("#transcript"), input = $("#input"), statusEl = $("#status");
  const state = { config: null, conv: null, ws: null, streaming: null, convs: [] };

  // ---------- helpers ----------
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const md = (s) => { try { return marked.parse(s ?? "", { breaks: true }); } catch { return `<p>${esc(s)}</p>`; } };
  const el = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstChild; };
  const setStatus = (t) => { statusEl.textContent = t || ""; };
  const scrollDown = () => { transcript.scrollTop = transcript.scrollHeight; };
  const api = async (path, opts = {}) => {
    const r = await fetch(path, { headers: { "content-type": "application/json" }, ...opts });
    if (r.status === 401) { document.body.innerHTML = "<p style='padding:2em'>Not logged in. Open <code>/login?t=&lt;token&gt;</code> once on this device.</p>"; throw new Error("unauthorized"); }
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    return r.status === 204 ? null : r.json();
  };
  const fmtInput = (inp) => {
    if (!inp || typeof inp !== "object") return String(inp ?? "");
    if (inp.command) return inp.command + (inp.description ? `\n# ${inp.description}` : "");
    if (inp.file_path && inp.content !== undefined) return `${inp.file_path}\n${String(inp.content).slice(0, 600)}`;
    if (inp.file_path) return inp.file_path;
    if (inp.query) return inp.query; if (inp.url) return inp.url; if (inp.pattern) return inp.pattern;
    const s = JSON.stringify(inp, null, 1); return s.length > 800 ? s.slice(0, 800) + " …" : s;
  };

  // ---------- rendering ----------
  function renderTool(p) {
    const d = el(`<details class="tool ${p.result !== null && p.result !== undefined ? (p.is_error ? "error" : "done") : ""}" data-id="${esc(p.id)}">
      <summary>${esc(p.name)}<span class="hint"> ${esc(fmtInput(p.input).split("\n")[0].slice(0, 80))}</span></summary>
      <pre class="in">${esc(fmtInput(p.input))}</pre>${p.result != null ? `<pre class="out">${esc(p.result)}</pre>` : ""}</details>`);
    return d;
  }
  function renderAssistant(m) {
    const box = el(`<div class="msg assistant"></div>`);
    for (const p of m.parts || []) {
      if (p.kind === "text") box.appendChild(el(`<div class="md">${md(p.text)}</div>`));
      else if (p.kind === "thinking") box.appendChild(el(`<details class="thinking"><summary>thinking</summary><pre>${esc(p.text)}</pre></details>`));
      else if (p.kind === "tool") box.appendChild(renderTool(p));
    }
    if (m.error) box.appendChild(el(`<div class="error">${esc(m.error)}</div>`));
    const u = m.usage || {};
    const meta = [m.model, m.cost != null ? `$${m.cost.toFixed(3)}` : null, u.output_tokens ? `${u.output_tokens} out` : null, m.ts?.slice(11, 16)].filter(Boolean).join(" · ");
    box.appendChild(el(`<div class="meta">${esc(meta)}</div>`));
    return box;
  }
  function renderConversation(c) {
    transcript.innerHTML = "";
    for (const m of c.messages || []) {
      if (m.role === "user") transcript.appendChild(el(`<div class="msg user">${esc(m.text)}</div>`));
      else transcript.appendChild(renderAssistant(m));
    }
    $("#title").textContent = c.title;
    renderSubtitle();
    scrollDown();
  }
  function renderSubtitle() {
    const c = state.conv; if (!c) return;
    const media = c.media?.usd ? ` + $${c.media.usd.toFixed(2)} speech` : "";
    $("#subtitle").textContent = `${modelLabel(c.backend, c.model)} · ${c.mode} · $${(c.total_cost_usd || 0).toFixed(2)}${media}`;
  }
  const modelLabel = (b, m) => (state.config?.backends?.[b]?.models || []).find((x) => x.id === m)?.label || m;

  // ---------- streaming turn ----------
  function beginStream() {
    const box = el(`<div class="msg assistant"></div>`);
    transcript.appendChild(box);
    state.streaming = { box, textEl: null, thinkEl: null, thinkBuf: "" };
    $("#interrupt").hidden = false;
    scrollDown();
  }
  function onEvent(ev) {
    const s = state.streaming;
    switch (ev.type) {
      case "ready": state.conv = ev.conversation; renderConversation(ev.conversation); break;
      case "status": setStatus(ev.text); break;
      case "turn_start": beginStream(); setStatus("thinking…"); Voice()?.onTurnStart(); break;
      case "thinking_start": if (s) { s.thinkEl = el(`<div class="live-thinking"></div>`); s.box.appendChild(s.thinkEl); s.thinkBuf = ""; } break;
      case "thinking_delta": if (s?.thinkEl) { s.thinkBuf += ev.text; s.thinkEl.textContent = s.thinkBuf.slice(-400); } break;
      case "text_start": if (s) { if (s.thinkEl) { s.thinkEl.remove(); s.thinkEl = null; } s.textEl = el(`<div class="md cursor"></div>`); s.textEl.dataset.raw = ""; s.box.appendChild(s.textEl); } Voice()?.onTextStart(); break;
      case "delta": if (s) { if (!s.textEl) onEvent({ type: "text_start" }); s.textEl.dataset.raw += ev.text; s.textEl.innerHTML = md(s.textEl.dataset.raw); scrollDown(); } Voice()?.onDelta(ev.text); break;
      case "tool_use": if (s) { if (s.textEl) s.textEl.classList.remove("cursor"); s.textEl = null; s.box.appendChild(renderTool({ ...ev, result: null })); setStatus(`running ${ev.name}…`); scrollDown(); } break;
      case "tool_result": if (s) { const d = s.box.querySelector(`details.tool[data-id="${CSS.escape(ev.id)}"]`); if (d) { d.classList.add(ev.is_error ? "error" : "done"); d.appendChild(el(`<pre class="out">${esc(ev.preview)}</pre>`)); } setStatus("thinking…"); } break;
      case "permission_request": showPermission(ev); break;
      case "turn_end": {
        if (s) { s.box.replaceWith(renderAssistant(ev.message)); state.streaming = null; }
        $("#interrupt").hidden = true; setStatus("");
        if (state.conv) { state.conv.messages.push(ev.message); state.conv.total_cost_usd = ev.total_cost_usd; if (ev.media) state.conv.media = ev.media; renderSubtitle(); }
        refreshConvs(); scrollDown(); Voice()?.onTurnEnd(ev.message); break;
      }
      case "error": setStatus("error: " + ev.message); if (ev.message === "a turn is already running") Voice()?.onTurnEnd(null); break;
    }
  }
  function showPermission(ev) {
    const box = state.streaming?.box || transcript;
    const p = el(`<div class="perm"><div class="tool">Allow ${esc(ev.tool)}?</div><pre>${esc(fmtInput(ev.input))}</pre>
      <div class="actions"><button class="primary allow">Allow</button><button class="deny">Deny</button></div></div>`);
    const answer = (allow) => { send({ type: "permission_response", id: ev.id, allow }); p.querySelector(".actions").innerHTML = `<span class="hint">${allow ? "allowed" : "denied"}</span>`; };
    p.querySelector(".allow").onclick = () => answer(true);
    p.querySelector(".deny").onclick = () => answer(false);
    box.appendChild(p); scrollDown();
    if (navigator.vibrate) navigator.vibrate(60);
  }

  // ---------- websocket ----------
  function send(obj) { if (state.ws?.readyState === 1) state.ws.send(JSON.stringify(obj)); }
  function connect(cid) {
    if (state.ws) { state.ws.onclose = null; state.ws.close(); }
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/${cid}`);
    state.ws = ws;
    ws.onmessage = (e) => onEvent(JSON.parse(e.data));
    ws.onclose = () => { setStatus("disconnected · reconnecting…"); setTimeout(() => { if (state.conv?.id === cid) connect(cid); }, 2000); };
    ws.onerror = () => {};
  }
  function sendUser() {
    const text = input.value.trim();
    if (!text || !state.ws || state.ws.readyState !== 1) return;
    transcript.appendChild(el(`<div class="msg user">${esc(text)}</div>`));
    state.conv.messages.push({ role: "user", text });
    if (state.conv.title === "New conversation") { state.conv.title = text.slice(0, 60); $("#title").textContent = state.conv.title; }
    const mode = Voice()?.isOn() ? "voice" : "text";
    state.conv.mode = mode; renderSubtitle();
    send({ type: "user", text, mode });
    input.value = ""; input.style.height = "auto"; scrollDown();
  }

  // ---------- conversations drawer ----------
  async function refreshConvs() {
    state.convs = await api("/api/conversations");
    const list = $("#convs"); list.innerHTML = "";
    for (const c of state.convs) {
      const d = el(`<div class="conv ${c.id === state.conv?.id ? "active" : ""}"><div class="t">${esc(c.title)}</div><div class="s">${esc(modelLabel(c.backend, c.model))} · ${c.n} msgs · ${new Date(c.updated * 1000).toLocaleString()}</div></div>`);
      d.onclick = () => { openConv(c.id); closeDrawer(); };
      let timer;
      const del = async (e) => { e.preventDefault(); if (confirm(`Delete "${c.title}"?`)) { await api(`/api/conversations/${c.id}`, { method: "DELETE" }); if (state.conv?.id === c.id) { state.conv = null; transcript.innerHTML = ""; $("#title").textContent = "…"; } refreshConvs(); } };
      d.oncontextmenu = del;
      d.ontouchstart = () => { timer = setTimeout(() => del(new Event("x")), 700); };
      d.ontouchend = d.ontouchmove = () => clearTimeout(timer);
      list.appendChild(d);
    }
  }
  async function openConv(cid) {
    if (Voice()?.isOn()) await Voice().off();
    const c = await api(`/api/conversations/${cid}`);
    state.conv = c; renderConversation(c); connect(cid);
    localStorage.setItem("lastConv", cid);
  }
  async function newConv() {
    const backend = $("#backend").value, model = $("#model").value;
    const c = await api("/api/conversations", { method: "POST", body: JSON.stringify({ backend, model, mode: "text" }) });
    await refreshConvs(); await openConv(c.id); closeDrawer(); input.focus();
  }
  function fillModels() {
    const b = $("#backend").value; const sel = $("#model"); sel.innerHTML = "";
    for (const m of state.config.backends[b].models) sel.appendChild(el(`<option value="${esc(m.id)}">${esc(m.label)}</option>`));
    sel.value = state.config.backends[b].default_model;
  }
  const openDrawer = () => { $("#drawer").classList.add("open"); refreshConvs(); };
  const closeDrawer = () => $("#drawer").classList.remove("open");

  // ---------- wiring ----------
  $("#composer").onsubmit = (e) => { e.preventDefault(); sendUser(); };
  input.onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing && matchMedia("(pointer:fine)").matches) { e.preventDefault(); sendUser(); } };
  input.oninput = () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, innerHeight * 0.4) + "px"; };
  $("#interrupt").onclick = () => send({ type: "interrupt" });
  $("#menu").onclick = openDrawer;
  $("#drawer").onclick = (e) => { if (e.target.id === "drawer") closeDrawer(); };
  $("#new").onclick = newConv;
  $("#backend").onchange = fillModels;
  $("#ttsVoice").onchange = (e) => localStorage.setItem("ttsVoice", e.target.value);
  $("#ttsSpeed").onchange = (e) => localStorage.setItem("ttsSpeed", e.target.value);
  function fillVoiceSettings() {
    const t = state.config.tts || {}, sel = $("#ttsVoice"); sel.innerHTML = "";
    for (const v of t.voices || []) sel.appendChild(el(`<option value="${esc(v)}">${esc(v)}</option>`));
    sel.value = localStorage.getItem("ttsVoice") || t.voice || "";
    $("#ttsSpeed").value = localStorage.getItem("ttsSpeed") || String(t.speed || 1);
  }
  const Voice = () => window.Voice;
  window.App = { state, send, sendUser, setStatus, renderSubtitle };

  (async () => {
    state.config = await api("/api/config");
    const bsel = $("#backend");
    for (const [id, b] of Object.entries(state.config.backends)) bsel.appendChild(el(`<option value="${id}">${esc(b.label)}</option>`));
    bsel.value = state.config.default_backend; fillModels(); fillVoiceSettings();
    await refreshConvs();
    const last = localStorage.getItem("lastConv");
    if (last && state.convs.some((c) => c.id === last)) openConv(last);
    else if (state.convs.length) openConv(state.convs[0].id);
    else openDrawer();
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  })();
})();
