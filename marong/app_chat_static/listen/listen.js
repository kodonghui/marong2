"use strict";
const API = "/chat/listen/api";
const testArea = document.querySelector("#test");
const statusLine = document.querySelector("#status");
const audio = document.querySelector("#audio");
const CONNECTION = "잠깐 문제가 생겼어. 조금 있다가 다시 해 줘";
const ERROR = "잠깐 문제가 생겼어. 다시 해 볼래?";
let test = null;
let index = 0;
let readId = 0;
let activeId = null;
let activeFailure = null;
let retryTimer;
let retryDelay = 5000;
let saveQueue = Promise.resolve();
const pending = new Set();
const errors = new Map();

function node(tag, cls, text) {
  const element = document.createElement(tag);
  if (cls) element.className = cls;
  if (text != null) element.textContent = text;
  return element;
}

function button(label, action, cls) {
  const element = node("button", cls, label);
  element.type = "button";
  element.addEventListener("click", action);
  return element;
}

function status(text) {
  statusLine.textContent = text;
  statusLine.hidden = !text;
}

function stop() {
  activeId = null;
  audio.pause();
  audio.removeAttribute("src");
  audio.load();
}

function state(face, words, action, trace) {
  test = null;
  stop();
  const block = node("div", "empty");
  const img = node("img");
  img.src = `/face/v1/${face}.webp`;
  img.alt = "";
  block.append(img, node("p", "", words));
  if (action) block.append(action);
  if (trace) block.append(node("small", "", trace));
  testArea.replaceChildren(block);
}

function permission(error) {
  if (error.status === 401) {
    if (!sessionStorage.getItem("listen-access-reload")) {
      sessionStorage.setItem("listen-access-reload", "1");
      location.reload();
    }
    return true;
  }
  if (error.status === 403 && error.code !== "cross_site") {
    status("");
    state("13-concerned", error.code === "no_dm"
      ? "디스코드 DM에서 마롱이한테 먼저 말 걸어 줘" : "이 계정으로는 시험을 볼 수 없어");
    return true;
  }
  return false;
}

async function request(path, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    const res = await fetch(API + path, {
      credentials: "same-origin", signal: controller.signal,
      method: body ? "PUT" : "GET", headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const reply = await res.json().catch(() => ({}));
    if (!res.ok) {
      const error = new Error(reply.code);
      throw Object.assign(error, { status: res.status, code: reply.code, trace: reply.traceId });
    }
    return reply;
  } finally {
    clearTimeout(timer);
  }
}

function retryRead(reset) {
  clearTimeout(retryTimer);
  retryTimer = setTimeout(() => void load(reset), retryDelay);
  retryDelay = Math.min(retryDelay * 2, 30000);
}

async function load(reset = false, keepStatus = false) {
  clearTimeout(retryTimer);
  if (reset) {
    errors.clear();
    activeFailure = null;
    stop();
  }
  const ticket = ++readId;
  try {
    const { test: current } = await request("/test");
    if (ticket !== readId) return;
    sessionStorage.removeItem("listen-access-reload");
    retryDelay = 5000;
    if (!keepStatus) status("");
    if (!current) {
      state("01-neutral", "지금은 들을 시험이 없어");
      return;
    }
    if (reset || current.testId !== test?.testId) index = 0;
    test = current;
    errors.clear();
    render();
  } catch (error) {
    if (ticket !== readId || permission(error)) return;
    if (error.status === 503) {
      status(CONNECTION);
      retryRead(reset);
    } else {
      status("");
      state("06-sad", ERROR, button("다시 해 볼게", () => void load(reset)), error.trace);
    }
  }
}

function play(clip) {
  if (activeId === clip) {
    if (audio.paused) void audio.play().catch(() => soundMissing(clip));
    else audio.pause();
    return;
  }
  activeId = clip;
  activeFailure = null;
  audio.src = `${API}/clips/${clip}`;
  void audio.play().catch(() => soundMissing(clip));
  render();
}

function soundMissing(clip) {
  if (activeId !== clip) return;
  activeFailure = clip;
  stop();
  render();
}

audio.addEventListener("error", () => { if (activeId) soundMissing(activeId); });
for (const event of ["playing", "pause", "ended", "timeupdate", "durationchange"]) {
  audio.addEventListener(event, () => {
    const player = testArea.querySelector(".playing");
    if (!player) return;
    const control = player.querySelector(".play");
    const progress = player.querySelector("progress");
    control.textContent = audio.paused ? "▶" : "■";
    control.setAttribute("aria-label", audio.paused ? "소리 듣기" : "소리 멈추기");
    progress.max = Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : 1;
    progress.value = audio.currentTime || 0;
  });
}

function save(sentence, clip, selection) {
  if (pending.has(clip.id) || !test) return;
  const testId = test.testId;
  pending.add(clip.id);
  errors.delete(clip.id);
  render();
  const work = async () => {
    try {
      if (test?.testId !== testId) return;
      const current = test.sentences[sentence.no - 1].clips.find(item => item.id === clip.id);
      const body = { testId, score: current.score, marongLike: current.marongLike, ...selection };
      const path = `/answers/${clip.id}`;
      let saved;
      try {
        saved = await request(path, body);
      } catch (error) {
        if (error.status !== 400) throw error;
        saved = await request(path, body);
      }
      if (test?.testId === testId) test.sentences[sentence.no - 1] = saved;
    } catch (error) {
      if (permission(error)) return;
      if (error.code === "stale_test") {
        status("시험이 바뀌었어. 새로 보여 줄게");
        await load(true, true);
      } else if (error.status === 404) {
        await load(true);
      } else if (error.status === 503) {
        status(CONNECTION);
        retryRead(false);
      } else {
        const message = error.code === "cross_site" ? "이 화면에서 다시 해 줘" : ERROR;
        errors.set(clip.id, error.trace ? `${message} (${error.trace})` : message);
      }
    } finally {
      pending.delete(clip.id);
      if (test) render();
    }
  };
  saveQueue = saveQueue.then(work, work);
}

function sample(sentence, clip, position) {
  const block = node("article", `sample${activeId === clip.id ? " playing" : ""}`);
  const line = node("div", "line");
  const playing = activeId === clip.id && !audio.paused;
  const control = button(playing ? "■" : "▶", () => play(clip.id), "play");
  control.setAttribute("aria-label", playing ? "소리 멈추기" : "소리 듣기");
  const name = node("strong", "", `소리 ${position + 1}`);
  const progress = node("progress");
  progress.max = Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : 1;
  progress.value = audio.currentTime || 0;
  progress.hidden = activeId !== clip.id;
  progress.setAttribute("aria-label", "재생 진행");
  line.append(control, name, progress);
  const scores = node("div", "scores");
  scores.setAttribute("aria-label", "자연스러움 점수");
  for (let value = 1; value <= 5; value++) {
    const option = button(value, () => save(sentence, clip, { score: value }));
    option.disabled = pending.has(clip.id);
    option.setAttribute("aria-label", `자연스러움 ${value}점`);
    option.setAttribute("aria-pressed", String(clip.score === value));
    scores.append(option);
  }
  const range = node("div", "range");
  range.append(node("small", "", "1 어색해"), node("small", "", "5 자연스러워"));
  const pick = button("마롱이 같다", () => save(sentence, clip, { marongLike: !clip.marongLike }), "choice");
  pick.disabled = pending.has(clip.id);
  pick.setAttribute("aria-pressed", String(clip.marongLike));
  block.append(line, scores, range, pick);
  if (activeFailure === clip.id || errors.has(clip.id)) {
    const issue = node("p", "answer-error", errors.get(clip.id) || "그 소리를 찾지 못했어");
    if (activeFailure === clip.id) issue.append(button("시험 다시 불러오기", () => void load(true)));
    block.append(issue);
  }
  return block;
}

function navigate(next) {
  stop();
  index = next;
  render();
  window.scrollTo(0, 0);
}

function render() {
  if (!test) return;
  const sentences = test.sentences;
  const complete = line => line.clips.every(clip => clip.score !== null);
  const count = node("p", "count", `${index + 1} / ${sentences.length}`);
  const dots = node("div", "dots");
  dots.setAttribute("aria-hidden", "true");
  sentences.forEach(sentence => dots.append(node("span", complete(sentence) ? "done-dot" : "", complete(sentence) ? "●" : "○")));
  const sentence = sentences[index];
  const children = [count, dots];
  if (sentences.every(complete)) children.push(node("p", "status", "다 들었어! 고마워. 바꾸고 싶으면 언제든 다시 골라도 돼"));
  if (index === 0) children.push(node("p", "intro", "같은 문장을 여러 목소리로 읽었어. 듣고 골라 줘"));
  children.push(node("p", "sentence", sentence.text));
  sentence.clips.forEach((clip, position) => children.push(sample(sentence, clip, position)));
  const nav = node("nav", "nav");
  const prior = button("‹ 앞 문장", () => navigate(index - 1));
  const next = button("다음 문장 ›", () => navigate(index + 1));
  prior.disabled = index === 0;
  next.disabled = index + 1 === sentences.length;
  nav.append(prior, next);
  children.push(nav);
  testArea.replaceChildren(...children);
}

function theme() {
  const hour = Number(new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Seoul", hour: "2-digit", hourCycle: "h23" })
    .format(new Date()));
  const light = hour >= 8 && hour < 20;
  document.documentElement.dataset.theme = light ? "chestnut" : "night";
  document.querySelector('meta[name="theme-color"]').content = light ? "#FBF6EE" : "#121729";
}

theme();
document.addEventListener("visibilitychange", () => { if (!document.hidden) theme(); });
setInterval(theme, 15000);
testArea.append(node("p", "count", "1 / 10"), node("div", "sentence skeleton"));
for (let i = 0; i < 4; i++) testArea.append(node("div", "sample skeleton"));
void load();
