// 마롱이 갤럭시 시험 페이지(기능 명세 7.1). 말 내용은 어디에도 남기지 않아요.
"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const FAKE = new URLSearchParams(location.search).has("fake");
  const PAGE = (crypto.randomUUID && crypto.randomUUID()) || uuid4();
  const STANDALONE = matchMedia("(display-mode: standalone)").matches;
  const LABEL = { idle: "대기", connecting: "거는 중", talking: "통화 중", resting: "쉬는 중", ended: "끝남" };
  const S = {
    state: "idle", kind: "start", ctx: null, mic: null, micSrc: null, micAn: null,
    pc: null, dc: null, remSrc: null, remAn: null, fake: null,
    sid: null, reported: null, maxMin: 20, sessStart: 0, expiresAt: null, usage: null,
    closing: false, closedResolve: null, autoClose: null, dropTimer: null, reconnects: [],
    wl: null, wlBusy: false, wlText: "-", worklet: null, zero: null, tdTimer: null, td: null,
    det: { timer: 0, worklet: 0 }, lastBeatAt: 0, lastBeatOk: 0, beatSeq: 0, beatFail: 0,
    bat: "-", server: null,
  };
  const PENDING = [];
  const SHOWN = [];
  const RESULTS = {};
  let AGG = freshAgg();

  function uuid4() {
    const b = crypto.getRandomValues(new Uint8Array(16));
    b[6] = (b[6] & 15) | 64;
    b[8] = (b[8] & 63) | 128;
    const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
    return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
  }
  function freshAgg() {
    return { micMax: 0, remMax: 0, remOn: 0, remN: 0, outTx: 0, inTx: 0, alive: 0, late: 0, tdN: 0 };
  }
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const short = (id) => String(id || "").slice(0, 24);
  const visible = () => document.visibilityState === "visible";
  const mmss = (ms) => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}`;

  // ---- 기록 ----
  function ev(k, data) {
    const e = Object.assign({ t: Date.now(), k, st: S.state, vis: visible() ? "v" : "h" }, data || {});
    PENDING.push(e);
    if (PENDING.length > 800) PENDING.splice(0, PENDING.length - 800);
    SHOWN.unshift(e);
    if (SHOWN.length > 60) SHOWN.length = 60;
    renderLog();
  }
  function renderLog() {
    if (!visible()) return;
    $("log").textContent = SHOWN.map((e) => {
      const extra = Object.entries(e).filter(([k]) => !["t", "k", "st", "vis"].includes(k))
        .map(([k, v]) => `${k}=${v}`).join(" ");
      return `${new Date(e.t).toTimeString().slice(0, 8)} ${e.k}${extra ? " " + extra : ""}${e.vis === "h" ? " (숨김)" : ""}`;
    }).join("\n");
  }

  // ---- 상태 ----
  function setState(s) {
    if (S.state === s) return;
    S.state = s;
    ev("state", { s });
    $("state").textContent = LABEL[s] + (FAKE ? " (가짜 통화)" : "");
    const inCall = s === "connecting" || s === "talking";
    $("call").disabled = inCall;
    $("hang").disabled = !(inCall || s === "resting");
    $("rest").disabled = s === "resting" || s === "connecting";
    $("wake").disabled = s !== "resting";
    if (inCall) requestWakeLock();
    else releaseWakeLock();
    updateView();
  }

  function updateView() {
    if (!visible()) return;
    $("clock").textContent = S.sessStart && S.state === "talking" ? mmss(Date.now() - S.sessStart) : "-";
    $("rtc").textContent = S.pc ? `${S.pc.connectionState} · 채널 ${S.dc ? S.dc.readyState : "-"}`
      : S.mic ? "WebRTC 닫힘 · 마이크만 켜짐" : "-";
    $("wl").textContent = S.wlText;
    $("beat").textContent = S.lastBeatOk
      ? `${Math.round((Date.now() - S.lastBeatOk) / 1000)}초 전 받음${S.beatFail ? ` · 실패 ${S.beatFail}번` : ""}` : "-";
    $("det").textContent = `타이머 ${S.det.timer} · 워크릿 ${S.det.worklet}`;
    $("exp").textContent = S.expiresAt ? `${Math.round((S.expiresAt * 1000 - Date.now()) / 60000)}분 뒤` : "-";
    $("left").textContent = S.server && S.server.sessions_left !== undefined
      ? `${S.server.sessions_left}개${S.server.minutes_used !== undefined
          ? ` · 쓴 시간 약 ${S.server.minutes_used}${S.server.max_total_min ? `/${S.server.max_total_min}` : ""}분` : ""}`
        + `${S.server.run_left_min !== undefined ? ` · 서버 ${S.server.run_left_min}분 남음` : ""}`
      : FAKE ? "가짜 통화라 세지 않음" : "-";
    $("bat").textContent = S.bat;
  }

  // ---- 소리 ----
  async function ensureAudio() {
    if (!S.ctx) {
      S.ctx = new (window.AudioContext || window.webkitAudioContext)();
      S.ctx.addEventListener("statechange", () => ev("ctx", { s: S.ctx.state }));
    }
    if (S.ctx.state !== "running") {
      try { await S.ctx.resume(); } catch (e) { ev("ctx", { s: "resume_fail:" + e.name }); }
    }
    const live = S.mic && S.mic.getAudioTracks().some((t) => t.readyState === "live");
    if (live) return;
    S.mic = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const tr = S.mic.getAudioTracks()[0];
    ev("mic_on", { s: (tr.label || "").slice(0, 60) });
    tr.addEventListener("mute", () => ev("mic_mute"));
    tr.addEventListener("unmute", () => ev("mic_unmute"));
    tr.addEventListener("ended", () => ev("mic_ended"));
    if (S.micSrc) { try { S.micSrc.disconnect(); } catch (_) { /* 이미 끊김 */ } }
    S.micSrc = S.ctx.createMediaStreamSource(S.mic);
    S.micAn = S.ctx.createAnalyser();
    S.micAn.fftSize = 2048;
    S.micSrc.connect(S.micAn);
    listDevices("mic");
  }
  function stopMic() {
    stopDetectors();
    if (S.micSrc) { try { S.micSrc.disconnect(); } catch (_) { /* 이미 끊김 */ } }
    if (S.mic) S.mic.getTracks().forEach((t) => t.stop());
    S.mic = null;
    S.micSrc = null;
    S.micAn = null;
  }
  const BUF = new Float32Array(2048);
  function rms(an) {
    if (!an) return 0;
    an.getFloatTimeDomainData(BUF);
    let s = 0;
    for (let i = 0; i < BUF.length; i++) s += BUF[i] * BUF[i];
    return Math.sqrt(s / BUF.length);
  }
  function micLive() {
    return !!S.mic && S.mic.getAudioTracks().some((t) => t.readyState === "live" && t.enabled && !t.muted);
  }

  setInterval(() => {
    const m = rms(S.micAn);
    const r = S.remAn ? rms(S.remAn) : 0;
    if (m > AGG.micMax) AGG.micMax = m;
    if (S.remAn && S.state === "talking") {
      AGG.remN++;
      if (r > 0.01) AGG.remOn++;
      if (r > AGG.remMax) AGG.remMax = r;
    }
    if (visible()) {
      $("micm").style.width = Math.min(100, m * 400) + "%";
      $("remm").style.width = Math.min(100, r * 400) + "%";
      $("micv").textContent = m.toFixed(3);
      $("remv").textContent = r.toFixed(3);
      updateView();
    }
  }, 200);

  // ---- 화면 켜 두기(SPEC-027) ----
  async function requestWakeLock() {
    if (!("wakeLock" in navigator)) {
      if (S.wlText !== "지원 안 함") { S.wlText = "지원 안 함"; ev("wl", { s: "unsupported" }); }
      return;
    }
    if (S.wl || S.wlBusy || !visible()) return;
    S.wlBusy = true;
    try {
      const lock = await navigator.wakeLock.request("screen");
      if (S.state !== "connecting" && S.state !== "talking") { lock.release().catch(() => {}); return; }
      S.wl = lock;
      S.wlText = "잡음";
      ev("wl", { s: "on" });
      lock.addEventListener("release", () => {
        if (S.wl === lock) S.wl = null;
        S.wlText = "놓임";
        ev("wl", { s: "released" });
      });
    } catch (e) {
      S.wlText = `거절됨(${e.name})`;
      ev("wl", { s: "denied:" + e.name });
    } finally {
      S.wlBusy = false;
    }
  }
  function releaseWakeLock() {
    if (!S.wl) return;
    const lock = S.wl;
    S.wl = null;
    lock.release().catch(() => {});
  }

  // ---- 통화 ----
  async function api(path, body) {
    const r = await fetch(path, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      cache: "no-store", credentials: "same-origin",
    });
    let j = {};
    try { j = await r.json(); } catch (_) { /* 빈 답 */ }
    if (!r.ok) {
      const err = new Error(j.error || `http_${r.status}`);
      err.code = j.code;
      err.status = j.status || r.status;
      throw err;
    }
    return j;
  }
  function explain(e) {
    const m = {
      no_key: "서버에 OpenAI 키가 없어요.",
      session_cap: "시험 세션을 다 썼어요. 서버를 다시 켜야 해요.",
      minute_cap: "시험에 정한 통화 시간을 다 썼어요. 더 하려면 서버를 다시 켜야 해요.",
      too_many_open: "열린 세션이 많아요. 1분 뒤 다시 걸어 주세요.",
      run_over: "시험 서버 시간이 끝났어요.",
      origin: "주소가 맞지 않아요. 페이지를 새로 열어 주세요.",
      openai: `OpenAI가 거절했어요(${e.status || ""} ${e.code || ""}).`,
      NotAllowedError: "마이크 허용이 필요해요. 주소창 왼쪽에서 마이크를 허용해 주세요.",
    };
    const byCode = {
      credit_balance_exhausted: "OpenAI 크레딧이 없어요. 충전한 뒤 다시 걸어 주세요. 가짜 통화(?fake)와 쉬기 시험은 지금도 돼요.",
      project_spend_limit_exceeded: "OpenAI 프로젝트 한도에 닿았어요.",
      organization_spend_limit_exceeded: "OpenAI 조직 한도에 닿았어요.",
      organization_usage_limit_exceeded: "OpenAI 사용 한도에 닿았어요.",
    };
    return byCode[e.code] || m[e.message] || m[e.name] || String((e && e.message) || e);
  }
  function iceDone(pc, ms = 10000) {
    if (pc.iceGatheringState === "complete") return Promise.resolve();
    return new Promise((resolve) => {
      const t = setTimeout(done, ms);
      function done() {
        clearTimeout(t);
        pc.removeEventListener("icegatheringstatechange", check);
        resolve();
      }
      function check() { if (pc.iceGatheringState === "complete") done(); }
      pc.addEventListener("icegatheringstatechange", check);
    });
  }

  async function startCall(kind) {
    if (S.state === "connecting" || S.state === "talking") return;
    const from = S.state;
    S.kind = kind;
    S.closing = false;
    $("msg").textContent = "";
    stopDetectors();
    setState("connecting");
    ev("call", { s: kind });
    let pc = null;
    try {
      await ensureAudio();
      pc = new RTCPeerConnection();
      S.pc = pc;
      pc.addEventListener("track", (e) => onTrack(e, pc));
      for (const tr of S.mic.getAudioTracks()) pc.addTrack(tr, S.mic);
      const dc = pc.createDataChannel("oai-events");
      S.dc = dc;
      dc.addEventListener("open", () => ev("dc", { s: "open" }));
      dc.addEventListener("close", () => {
        ev("dc", { s: "close" });
        if (S.pc === pc && !S.closing) onDrop("dc_close");
      });
      dc.addEventListener("message", (m) => onDc(m, pc));
      pc.addEventListener("connectionstatechange", () => onPcState(pc));
      pc.addEventListener("iceconnectionstatechange", () => ev("ice", { s: pc.iceConnectionState }));
      await pc.setLocalDescription(await pc.createOffer());
      await iceDone(pc);
      const t0 = performance.now();
      const name = $("name").value.trim() || "동희";
      try { localStorage.setItem("galaxy-test-name", name); } catch (_) { /* 저장 못 해도 됨 */ }
      const res = FAKE ? await fakeAnswer(pc.localDescription.sdp)
        : await api("/api/session", { page: PAGE, kind, name, sdp: pc.localDescription.sdp });
      if (S.pc !== pc) { // 기다리는 사이 끊기를 누름
        if (!FAKE) reportEnd(res.session_id, "abandoned", null);
        return;
      }
      S.sid = res.session_id;
      S.reported = null;
      S.maxMin = res.max_min || 20;
      if (res.sessions_left !== undefined) S.server = Object.assign(S.server || {}, { sessions_left: res.sessions_left });
      ev("created", { ms: Math.round(performance.now() - t0), sid: short(S.sid) });
      await pc.setRemoteDescription({ type: "answer", sdp: res.sdp });
      S.sessStart = Date.now();
      clearTimeout(S.autoClose);
      S.autoClose = setTimeout(() => {
        if (S.pc === pc) { ev("auto_close"); hangUp("auto", "ended"); }
      }, Math.max(1, S.maxMin - 0.5) * 60000);
    } catch (err) {
      ev("call_fail", { s: `${err.message || err}${err.code ? ":" + err.code : ""}`.slice(0, 90) });
      $("msg").textContent = "전화를 걸지 못했어요: " + explain(err);
      if (S.sid && S.pc === pc) reportEnd(S.sid, "abandoned", null);
      cleanupPeer();
      if (from === "resting") { setState("resting"); startDetectors(); } else setState("idle");
    }
  }

  function onTrack(e, pc) {
    if (S.pc !== pc) return;
    const stream = (e.streams && e.streams[0]) || new MediaStream([e.track]);
    const a = $("remote");
    a.srcObject = stream;
    a.play().catch((er) => {
      ev("play_blocked", { s: er.name });
      $("msg").textContent = "소리가 막혔어요. 화면을 한 번 눌러 주세요.";
    });
    try {
      if (S.remSrc) S.remSrc.disconnect();
      S.remSrc = S.ctx.createMediaStreamSource(stream);
      S.remAn = S.ctx.createAnalyser();
      S.remAn.fftSize = 2048;
      S.remSrc.connect(S.remAn);
    } catch (er) {
      ev("error", { s: "remote_analyser:" + er.name });
    }
    ev("track");
  }

  function sendDc(obj, what) {
    try {
      if (S.dc && S.dc.readyState === "open") {
        S.dc.send(JSON.stringify(obj));
        if (what) ev("commentary", { s: what });
        return true;
      }
    } catch (e) {
      ev("error", { s: "dc_send:" + e.name });
    }
    return false;
  }

  function onDc(m, pc) {
    if (S.pc !== pc) return;
    let e;
    try { e = JSON.parse(m.data); } catch (_) { return; }
    switch (e.type) {
      case "session.started": {
        S.expiresAt = (e.session && e.session.expires_at) || null;
        ev("started", { sid: short(e.session && e.session.id),
          exp_s: S.expiresAt ? Math.round(S.expiresAt - Date.now() / 1000) : null });
        setState("talking");
        if (S.kind === "start") {
          sendDc({ type: "session.commentary.append", event_id: `greet_${Date.now()}`, delegation_id: null,
            content: "전화가 연결됐어. 친구가 전화 받듯 짧게 먼저 말해." }, "greet");
        }
        break;
      }
      case "session.output_transcript.delta": AGG.outTx++; break;
      case "session.input_transcript.delta": AGG.inTx++; break;
      case "session.usage.updated": if (e.usage) S.usage = e.usage.seconds; break;
      case "session.delegation.created": {
        ev("delegation");
        const id = e.delegation && e.delegation.id;
        if (id) {
          sendDc({ type: "session.commentary.append", event_id: `deleg_${Date.now()}`, delegation_id: id,
            content: "시험 통화라 지금은 기억을 찾거나 적어 둘 수 없어. 지금은 안 된다고 친구에게 솔직하게 말해 줘." }, "deleg");
        }
        break;
      }
      case "session.commentary.appended": ev("commentary_ok"); break;
      case "info": ev("info", { s: String(e.code || "").slice(0, 60) }); break;
      case "error": ev("error", { s: String((e.error && (e.error.code || e.error.type)) || "unknown").slice(0, 80) }); break;
      case "session.closed": {
        const usage = e.usage ? e.usage.seconds : null;
        S.usage = usage;
        ev("closed", { s: e.reason || "", v: usage });
        onClosed(e.reason || "", usage);
        break;
      }
      default: break;
    }
  }

  function onPcState(pc) {
    if (S.pc !== pc) return;
    const st = pc.connectionState;
    ev("pc", { s: st });
    clearTimeout(S.dropTimer);
    if (S.closing) return;
    if (st === "failed") onDrop("failed");
    else if (st === "disconnected") {
      S.dropTimer = setTimeout(() => {
        if (S.pc === pc && pc.connectionState === "disconnected") onDrop("disconnected_3s");
      }, 3000);
    }
  }

  function reportEnd(sid, reason, usage) {
    if (FAKE || !sid || S.reported === sid) return;
    S.reported = sid;
    api("/api/end", { page: PAGE, session_id: sid, reason, usage }).catch(() => {});
  }

  function onDrop(why) {
    if (S.closing || !S.pc) return;
    ev("drop", { s: why });
    reportEnd(S.sid, "drop:" + why, null);
    cleanupPeer();
    reconnectOrStop();
  }

  function onClosed(reason, usage) {
    reportEnd(S.sid, reason, usage);
    const wasClosing = S.closing;
    if (S.closedResolve) { S.closedResolve(); S.closedResolve = null; }
    if (wasClosing) return; // hangUp이 마무리해요
    cleanupPeer();
    reconnectOrStop();
  }

  function reconnectOrStop() {
    const now = Date.now();
    S.reconnects = S.reconnects.filter((t) => now - t < 600000);
    if (S.reconnects.length >= 3) {
      ev("reconnect", { s: "limit" });
      setState("idle");
      $("msg").textContent = "10분 안에 세 번 끊겨서 멈췄어요. 다시 걸어 주세요.";
      return;
    }
    S.reconnects.push(now);
    ev("reconnect", { n: S.reconnects.length });
    setState("idle");
    setTimeout(() => { if (S.state === "idle") startCall("again"); }, 1500);
  }

  async function hangUp(by, intent) {
    ev("hangup", { s: by });
    const pc = S.pc;
    if (!pc) { finish(intent); return; }
    S.closing = true;
    clearTimeout(S.autoClose);
    const done = new Promise((resolve) => { S.closedResolve = resolve; });
    const sent = sendDc({ type: "session.close", event_id: `close_${Date.now()}` });
    if (sent) await Promise.race([done, sleep(5000)]);
    S.closedResolve = null;
    if (S.reported !== S.sid) reportEnd(S.sid, sent ? "close_unconfirmed" : "abandoned", null);
    cleanupPeer();
    finish(intent);
  }

  function finish(intent) {
    S.closing = false;
    S.sid = null;
    S.expiresAt = null;
    S.sessStart = 0;
    if (intent === "rest") {
      setState("resting");
      startDetectors();
      ev("rest");
    } else {
      stopMic();
      setState("ended");
    }
  }

  function cleanupPeer() {
    clearTimeout(S.autoClose);
    clearTimeout(S.dropTimer);
    const pc = S.pc;
    S.pc = null;
    if (S.dc) { try { S.dc.close(); } catch (_) { /* 이미 닫힘 */ } S.dc = null; }
    if (pc) { try { pc.close(); } catch (_) { /* 이미 닫힘 */ } }
    if (S.remSrc) { try { S.remSrc.disconnect(); } catch (_) { /* 이미 끊김 */ } }
    S.remSrc = null;
    S.remAn = null;
    $("remote").srcObject = null;
    if (S.fake) { S.fake.close(); S.fake = null; }
  }

  // ---- 쉬는 중 말소리 감지(3.3: 잡음 바닥 +12dB, 350ms) ----
  async function startDetectors() {
    try {
      await ensureAudio();
      if (!S.worklet) {
        await S.ctx.audioWorklet.addModule("/worklet.js");
        S.worklet = new AudioWorkletNode(S.ctx, "detector");
        S.worklet.port.onmessage = (m) => {
          const d = m.data || {};
          if (d.type === "alive") { if (S.state === "resting") AGG.alive++; return; }
          if (d.type === "det" && S.state === "resting") onDetect("worklet", d.rms, d.floor);
        };
        S.zero = S.ctx.createGain();
        S.zero.gain.value = 0; // 소리는 내지 않아요(페이지가 '소리 나는 중'이 되지 않게)
        S.worklet.connect(S.zero);
        S.zero.connect(S.ctx.destination);
      }
      S.worklet.port.postMessage({ type: "reset" });
      try { S.micSrc.connect(S.worklet); } catch (_) { /* 이미 이어짐 */ }
      S.td = { floor: 0, above: 0, cool: 0, last: 0, warm: 1 };
      clearInterval(S.tdTimer);
      S.tdTimer = setInterval(timerDetect, 100);
    } catch (e) {
      ev("error", { s: "detector:" + (e.name || e) });
    }
  }
  function stopDetectors() {
    clearInterval(S.tdTimer);
    S.tdTimer = null;
    if (S.worklet && S.micSrc) { try { S.micSrc.disconnect(S.worklet); } catch (_) { /* 안 이어짐 */ } }
  }
  function timerDetect() {
    const td = S.td;
    const now = performance.now();
    const dt = td.last ? (now - td.last) / 1000 : 0.1;
    td.last = now;
    if (dt > 1) AGG.late++;
    AGG.tdN++;
    const x = rms(S.micAn);
    const step = Math.min(dt, 0.1); // 늦게 불려도 한 번 잰 것은 100ms어치로만 셈
    if (td.warm > 0) { td.warm -= step; td.floor = Math.max(x, 1e-4); return; }
    if (x < td.floor) td.floor = Math.max(x, 1e-4);
    else td.floor = Math.min(x, td.floor * Math.pow(10, (3 * step) / 20));
    const thr = Math.max(td.floor * 3.98, 0.008);
    td.above = x > thr ? td.above + step : 0;
    if (td.cool > 0) td.cool -= dt;
    if (td.above >= 0.35 && td.cool <= 0) {
      td.cool = 3;
      td.above = 0;
      onDetect("timer", x, td.floor);
    }
  }
  function onDetect(via, x, floor) {
    S.det[via]++;
    ev("det", { via, v: Number(x.toFixed(4)), fl: Number((floor || 0).toFixed(4)) });
    try { if (navigator.vibrate) navigator.vibrate(60); } catch (_) { /* 진동 없음 */ }
    if ($("autowake").checked && S.state === "resting") wake("voice_" + via);
  }
  function wake(why) {
    if (S.state !== "resting") return;
    ev("wake", { s: why });
    startCall("wake");
  }

  // ---- 서버 신호(15초, SPEC-010) ----
  function beatBody(events) {
    return {
      page: PAGE, seq: S.beatSeq, gap: S.lastBeatAt ? Date.now() - S.lastBeatAt : 0, st: S.state,
      vis: document.visibilityState, mic: micLive(), rtc: S.pc ? S.pc.connectionState : "-",
      ctx: S.ctx ? S.ctx.state : "-", wl: S.wlText, bat: S.bat, standalone: STANDALONE, fake: FAKE,
      agg: AGG, usage: S.usage, events,
    };
  }
  async function beat() {
    S.beatSeq++;
    const events = PENDING.splice(0, PENDING.length);
    const body = beatBody(events);
    S.lastBeatAt = Date.now();
    AGG = freshAgg();
    try {
      S.server = await api("/api/beat", body);
      S.lastBeatOk = Date.now();
    } catch (e) {
      S.beatFail++;
      PENDING.unshift(...events.slice(-400));
    }
  }
  setInterval(beat, 15000);
  function flushBeacon() {
    if (!navigator.sendBeacon) return;
    S.beatSeq++;
    const body = beatBody(PENDING.splice(0, PENDING.length));
    navigator.sendBeacon("/api/beat", new Blob([JSON.stringify(body)], { type: "application/json" }));
  }

  // ---- 페이지·기기 상태 ----
  async function listDevices(why) {
    try {
      const ds = await navigator.mediaDevices.enumerateDevices();
      const ins = ds.filter((d) => d.kind === "audioinput").map((d) => d.label || "?");
      const outs = ds.filter((d) => d.kind === "audiooutput").map((d) => d.label || "?");
      ev("devices", { s: `${why} 입력:${ins.join("|")} 출력:${outs.join("|")}`.slice(0, 100), n: ins.length + outs.length });
    } catch (_) { /* 목록 없음 */ }
  }
  document.addEventListener("visibilitychange", () => {
    ev("vis", { s: document.visibilityState });
    if (visible()) {
      renderLog();
      updateView();
      if (S.state === "talking" || S.state === "connecting") requestWakeLock();
    }
  });
  document.addEventListener("freeze", () => ev("freeze"));
  document.addEventListener("resume", () => ev("resume"));
  window.addEventListener("pagehide", (e) => { ev("pagehide", { s: e.persisted ? "persisted" : "" }); flushBeacon(); });
  window.addEventListener("pageshow", (e) => ev("pageshow", { s: e.persisted ? "persisted" : "" }));
  window.addEventListener("online", () => ev("online"));
  window.addEventListener("offline", () => ev("offline"));
  if (navigator.mediaDevices && navigator.mediaDevices.addEventListener) {
    navigator.mediaDevices.addEventListener("devicechange", () => listDevices("change"));
  }
  if (navigator.getBattery) {
    navigator.getBattery().then((b) => {
      const upd = () => {
        S.bat = `${Math.round(b.level * 100)}%${b.charging ? " 충전 중" : ""}`;
        ev("battery", { v: Math.round(b.level * 100), s: b.charging ? "charging" : "" });
      };
      upd();
      b.addEventListener("levelchange", upd);
      b.addEventListener("chargingchange", upd);
    }).catch(() => {});
  }
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").then(() => ev("sw", { s: "ok" })).catch((e) => ev("sw", { s: "fail:" + e.name }));
  }
  window.addEventListener("beforeinstallprompt", () => ev("installable"));
  window.addEventListener("appinstalled", () => ev("installed"));
  document.addEventListener("click", () => {
    if (S.ctx && S.ctx.state === "suspended") S.ctx.resume().catch(() => {});
    if ($("remote").srcObject && $("remote").paused) $("remote").play().catch(() => {});
  });

  // ---- 가짜 통화(?fake): 휴대폰 안에서 상대를 흉내 내요. 서버·OpenAI·요금 없음 ----
  async function fakeAnswer(offerSdp) {
    const f = new RTCPeerConnection();
    const osc = S.ctx.createOscillator();
    const gain = S.ctx.createGain();
    const dest = S.ctx.createMediaStreamDestination();
    gain.gain.value = 0;
    osc.frequency.value = 440;
    osc.connect(gain).connect(dest);
    osc.start();
    dest.stream.getAudioTracks().forEach((t) => f.addTrack(t, dest.stream));
    let timer = null;
    let secs = 0;
    f.addEventListener("datachannel", (e) => {
      const ch = e.channel;
      ch.addEventListener("open", () => {
        ch.send(JSON.stringify({ type: "session.started",
          session: { id: "live_fake", expires_at: Math.round(Date.now() / 1000) + 3600 } }));
        timer = setInterval(() => {
          secs++;
          const on = secs % 3 === 0;
          gain.gain.setTargetAtTime(on ? 0.3 : 0, S.ctx.currentTime, 0.01);
          if (on) ch.send(JSON.stringify({ type: "session.output_transcript.delta", delta: "삐", start_ms: secs * 1000, end_ms: secs * 1000 + 300 }));
          if (secs % 5 === 0) ch.send(JSON.stringify({ type: "session.usage.updated", usage: { seconds: secs } }));
        }, 1000);
      });
      ch.addEventListener("message", (m) => {
        let c;
        try { c = JSON.parse(m.data); } catch (_) { return; }
        if (c.type === "session.close") {
          clearInterval(timer);
          ch.send(JSON.stringify({ type: "session.closed", reason: "close_requested", usage: { seconds: secs } }));
        } else if (c.type === "session.commentary.append") {
          ch.send(JSON.stringify({ type: "session.commentary.appended", client_event_id: c.event_id }));
        }
      });
    });
    S.fake = { close: () => { clearInterval(timer); try { osc.stop(); } catch (_) { /* 멈춤 */ } f.close(); } };
    await f.setRemoteDescription({ type: "offer", sdp: offerSdp });
    await f.setLocalDescription(await f.createAnswer());
    await iceDone(f);
    return { session_id: `live_fake_${Date.now()}`, sdp: f.localDescription.sdp, max_min: 20 };
  }

  // ---- 버튼 ----
  $("call").addEventListener("click", () => startCall("start"));
  $("hang").addEventListener("click", () => {
    if (S.state === "resting") finish("ended");
    else hangUp("button", "ended");
  });
  $("rest").addEventListener("click", async () => {
    if (S.state === "talking" || S.state === "connecting") { await hangUp("rest_button", "rest"); return; }
    try {
      await ensureAudio();
      setState("resting");
      await startDetectors();
      ev("rest");
    } catch (e) {
      $("msg").textContent = "마이크를 켜지 못했어요: " + explain(e);
      ev("call_fail", { s: "mic:" + e.name });
    }
  });
  $("wake").addEventListener("click", () => wake("button"));
  $("stop").addEventListener("click", () => { if (S.pc) hangUp("stop", "ended"); else finish("ended"); });
  function flash(b) { b.style.outline = "3px solid var(--ok)"; setTimeout(() => { b.style.outline = ""; }, 600); }
  document.querySelectorAll("[data-mark]").forEach((b) => b.addEventListener("click", () => {
    const s = b.dataset.mark;
    let memo;
    if (s === "메모") {
      memo = (prompt("남길 메모(느낀 점만 짧게)") || "").trim().slice(0, 200);
      if (!memo) return;
    }
    ev("mark", memo ? { s, memo } : { s });
    flash(b);
  }));
  function renderChecks() {
    $("checks").textContent = Object.keys(RESULTS).sort().map((n) => `${n}번 ${RESULTS[n]}`).join(" · ");
  }
  document.querySelectorAll("[data-item]").forEach((div) => {
    for (const [label, val] of [["됐어요", "ok"], ["안 됐어요", "fail"], ["애매해요", "unsure"], ["메모", "memo"]]) {
      const b = document.createElement("button");
      b.textContent = label;
      b.addEventListener("click", () => {
        const n = Number(div.dataset.item);
        let memo;
        if (val === "memo") {
          memo = (prompt(`${n}번 메모`) || "").trim().slice(0, 200);
          if (!memo) return;
        } else {
          RESULTS[n] = label;
        }
        ev("check", memo ? { n, s: val, memo } : { n, s: val });
        renderChecks();
        flash(b);
      });
      div.appendChild(b);
    }
  });
  try { const saved = localStorage.getItem("galaxy-test-name"); if (saved) $("name").value = saved; } catch (_) { /* 없음 */ }

  const ua = navigator.userAgent;
  ev("load", {
    s: `${STANDALONE ? "standalone" : "browser"} ${(ua.match(/Android [\d.]+/) || [""])[0]} ${(ua.match(/Chrome\/[\d.]+/) || [""])[0]}`.trim(),
    ok: !!window.RTCPeerConnection && !!(window.AudioWorkletNode),
  });
  if (navigator.userAgentData && navigator.userAgentData.getHighEntropyValues) {
    navigator.userAgentData.getHighEntropyValues(["model", "platformVersion"])
      .then((v) => ev("device", { s: `${v.model || "?"} Android ${v.platformVersion || "?"}` })).catch(() => {});
  }
  setState("idle");
  $("state").textContent = LABEL.idle + (FAKE ? " (가짜 통화)" : "");
  updateView();
  beat();
})();
