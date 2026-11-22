import { makeSheets } from "./sheets.js";

const BASE = "/chat/diary/";
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const FACE = "/face/v1/";
const KST = "Asia/Seoul";
const RETRY = "잠깐 문제가 생겼어. 다시 해 볼래?";
const CONNECTION = "잠깐 문제가 생겼어. 조금 있다가 다시 해 줘";
const BLOCKS = {
  fix_limit: "이 일기는 다섯 번 다 고쳤어",
  redraw_limit: "그림은 두 번 다 다시 그렸어",
  drawing_budget: "이번 달 그림을 다 그렸어. 다음 달에 또 그려 줄게",
};
const WEATHER = {
  sunny: ["맑음", "☼"], cloudy: ["구름", "☁"], rain: ["비", "☂"],
  snow: ["눈", "❅"], rainbow: ["무지개", "◠"],
};
const EMPTY = {
  writing: ["04-thinking", "마롱이가 아직 일기를 쓰는 중이야. 다 쓰면 알려 줄게"],
  skipped: ["11-drowsy", "그 날은 얘기가 적어서 일기를 쉬었어"],
  failed: ["06-sad", "그 날 일기를 못 썼어"],
  none: ["01-neutral", "그 날 내 일기가 없어"],
  empty: ["05-excited", "아직 일기가 없어. 오늘 마롱이랑 얘기하면 내일 아침에 첫 일기를 보여 줄게"],
  off: ["01-neutral", "지금은 일기를 쓰지 않고 있어. 일기가 켜지면 아침마다 알려 줄게"],
};
const view = document.querySelector("#day");
const pages = document.querySelector("#pages");
const menu = document.querySelector("#menu");
const more = document.querySelector("#more");
const calendar = document.querySelector("#calendar");
const banner = document.querySelector("#banner");
const toast = document.querySelector("#toast");

let day = null;
let date = "";
let loadId = 0;
let poll, retry, toastTimer, staleTimer;
let retryDelay = 5000;
let busySince = 0;
let expectedRedraw = false;
let newScene = false;
let weatherOpen = false;
let changing = false;
let lastTrouble = null;
let loadedState = "loading";

export function element(tag, cls, value) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (value != null) node.textContent = value;
  return node;
}

export function button(label, action, cls = "button") {
  const node = element("button", cls, label);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}

export function formatDay(value, full = false) {
  if (!DAY.test(value)) return "";
  const [year, month, day] = value.split("-").map(Number);
  if (!full) return `${month}월 ${day}일`;
  const weekday = new Intl.DateTimeFormat("ko-KR", { weekday: "long", timeZone: "UTC" })
    .format(new Date(`${value}T00:00:00Z`));
  return `${year}년 ${month}월 ${day}일 ${weekday}`;
}

export function weatherMark(key) {
  const node = element("span", `weather-mark ${key}`, WEATHER[key]?.[1]);
  node.setAttribute("aria-hidden", "true");
  return node;
}

export async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeout || 10000);
  try {
    const headers = { Accept: "application/json" };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (options.key) headers["Idempotency-Key"] = options.key;
    const response = await fetch(`${BASE}api${path}`, {
      method: options.method || "GET", headers, credentials: "same-origin", signal: controller.signal,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    const body = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok || (response.status !== 204 && body === null)) {
      const error = new Error(body?.code || "network");
      error.code = body?.code || "network";
      error.status = response.status;
      error.trace = body?.traceId;
      error.retryAfter = Number(response.headers.get("Retry-After")) || 1;
      throw error;
    }
    return body;
  } finally {
    clearTimeout(timer);
  }
}

function setTheme() {
  const hour = Number(new Intl.DateTimeFormat("en-GB", { timeZone: KST, hour: "2-digit", hourCycle: "h23" })
    .format(new Date()));
  const light = hour >= 8 && hour < 20;
  document.documentElement.dataset.theme = light ? "chestnut" : "night";
  document.querySelector('meta[name="theme-color"]').content = light ? "#FBF6EE" : "#121729";
}

function announce(message) {
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.hidden = !message;
  if (message) toastTimer = setTimeout(() => { toast.hidden = true; }, 3000);
}

function showBanner(message = "") {
  banner.textContent = message;
  banner.hidden = !message;
}

function loadAgain() {
  if (!sessionStorage.getItem("diary-access-reload")) {
    sessionStorage.setItem("diary-access-reload", "1");
    window.location.reload();
  } else {
    window.location.assign("/chat/");
  }
}

function permission(error) {
  if (error.status === 401) {
    loadAgain();
    return true;
  }
  if (error.status === 403 && error.code !== "cross_site") {
    closeSheet(false);
    loadedState = "permission";
    lastTrouble = error;
    day = null;
    draw();
    return true;
  }
  return false;
}

function hideMenu() {
  menu.hidden = true;
  more.setAttribute("aria-expanded", "false");
}

function openSheet(name) {
  hideMenu();
  if (location.hash !== `#${name}`) history.pushState({ diarySheet: true }, "", `#${name}`);
  sheets.show(name);
}

function closeSheet(goBack = true) {
  sheets.close();
  if (!location.hash) return;
  if (goBack && history.state?.diarySheet) history.back();
  else history.replaceState(null, "", location.pathname);
}

function navigate(next, replace = false) {
  sheets.close();
  closeSheet(false);
  hideMenu();
  const path = DAY.test(next) ? `${BASE}${next}` : BASE;
  if (location.pathname !== path) {
    if (replace) history.replaceState(null, "", path);
    else history.pushState(null, "", path);
  }
  void load(true);
  window.scrollTo(0, 0);
}

function readingFailed(error, id) {
  if (id !== loadId || permission(error)) return;
  lastTrouble = error;
  if (error.status === 400 && date) {
    day = null;
    loadedState = "none";
    draw();
  } else if (error.status === 503) {
    if (day) showBanner(CONNECTION);
    else {
      loadedState = "reconnecting";
      draw();
    }
    retry = setTimeout(() => { if (id === loadId) void load(false); }, retryDelay);
    retryDelay = Math.min(retryDelay * 2, 30000);
  } else {
    loadedState = "error";
    if (day) {
      showBanner(RETRY);
      const action = button("다시 해 볼게", () => void load(false), "text-button");
      banner.append(action);
    } else draw();
  }
}

async function load(reset) {
  clearTimeout(poll);
  clearTimeout(retry);
  const id = ++loadId;
  if (reset) {
    date = location.pathname.slice(BASE.length);
    day = null;
    weatherOpen = false;
    busySince = 0;
    expectedRedraw = false;
    newScene = false;
    loadedState = "loading";
    showBanner();
    draw();
  }
  try {
    if (!date) {
      const head = await api("/latest");
      if (id !== loadId) return;
      document.querySelector("#off-note").hidden = head.enabled || !head.date;
      if (!head.date) {
        loadedState = head.enabled ? "empty" : "off";
        sessionStorage.removeItem("diary-access-reload");
        draw();
        return;
      }
      date = head.date;
      history.replaceState(history.state, "", `${BASE}${date}${location.hash}`);
    }
    if (!DAY.test(date)) {
      loadedState = "none";
      draw();
      return;
    }
    const next = await api(`/days/${date}`);
    if (id !== loadId) return;
    sessionStorage.removeItem("diary-access-reload");
    retryDelay = 5000;
    if (banner.textContent === CONNECTION || banner.textContent.startsWith(RETRY)) showBanner();
    setDay(next);
  } catch (error) {
    readingFailed(error, id);
  }
}

function setDay(value) {
  const prior = day?.diary?.busy;
  day = value;
  loadedState = value.state;
  const active = day.diary?.busy;
  if (active && active !== prior) busySince = Date.now();
  if (prior === "redraw" && !active && expectedRedraw && day.diary?.redraw.last?.result === "done") {
    announce("새로 그렸어!");
    newScene = false;
    sheets.clear("redraw");
  }
  if (!active) expectedRedraw = false;
  draw();
  clearTimeout(poll);
  if (active && Date.now() - busySince < 120000) poll = setTimeout(() => void load(false), 2000);
}

async function change(action, body) {
  if (changing || !day?.diary) return;
  const currentDate = date;
  changing = true;
  weatherOpen = false;
  draw();
  try {
    const updated = await api(`/days/${currentDate}/${action}`, { method: "PUT", body });
    if (date !== currentDate) return;
    setDay(updated);
    if (action === "hidden" && body.hidden) announce("숨겼어. 숨긴 일기에서 다시 볼 수 있어");
  } catch (error) {
    if (date !== currentDate || permission(error)) return;
    if (["stale_revision", "not_ready", "busy"].includes(error.code)) {
      if (error.code === "stale_revision") {
        showBanner("그 사이 일기가 바뀌었어. 새로 보여 줄게");
        clearTimeout(staleTimer);
        staleTimer = setTimeout(() => showBanner(), 3000);
      }
      await load(false);
    } else {
      const words = error.code === "cross_site" ? "이 화면에서 다시 해 줘" : CONNECTION;
      announce(words);
    }
  } finally {
    changing = false;
    draw();
  }
}

function renderManuscript(text, paper) {
  const grid = element("div", "manuscript");
  grid.setAttribute("aria-hidden", "true");
  const paragraph = element("p", "readable", text);
  paper.append(grid, paragraph);
  drawGrid(grid, text);
}

function drawGrid(grid, text) {
  const width = document.querySelector(".diary").getBoundingClientRect().width;
  const columns = Math.max(1, Math.floor((width - 32) / 32));
  grid.style.setProperty("--columns", columns);
  const cells = [" "];
  for (const letter of text) {
    if (/\s/.test(letter) && cells.length % columns === 0) continue;
    cells.push(letter);
  }
  while (cells.length % columns !== 0) cells.push("");
  grid.replaceChildren(...cells.map(letter => element("span", "", letter)));
}

function fallbackArt() {
  const node = element("div", "placeholder");
  const side = element("span", "", "✦");
  side.setAttribute("aria-hidden", "true");
  const face = element("img");
  face.alt = "";
  face.src = `${FACE}01-neutral.webp`;
  node.append(side, face, side.cloneNode(true));
  return node;
}

function drawPicture(diary) {
  const figure = element("figure", "picture");
  const frame = element("div", "picture-frame");
  const caption = element("figcaption");
  const status = element("div");
  const busy = diary.busy === "redraw";
  const alt = `${diary.writer?.name || "마롱이"}의 '${diary.title}' 그림`;

  function picture(reload = false) {
    status.replaceChildren();
    let img;
    if (diary.drawing.kind === "ai") {
      img = element("img", "art");
      img.alt = alt;
      img.src = `${BASE}api/drawings/${diary.drawing.id}${reload ? `?retry=${Date.now()}` : ""}`;
      caption.textContent = "AI가 그린 그림";
      img.addEventListener("error", () => {
        if (!img.isConnected) return;
        img.replaceWith(fallbackArt());
        caption.textContent = "기본 그림";
        status.replaceChildren(button("그림 다시 보기", () => picture(true), "text-button"));
      }, { once: true });
    } else if (diary.writer) {
      img = element("div", "placeholder writer-placeholder", "오늘은 그림을 못 그렸어요");
      caption.textContent = "";
    } else {
      img = fallbackArt();
      caption.textContent = "기본 그림";
      if (!diary.redraw.blocked && !busy) {
        status.append(element("p", "paper-note", "이번엔 그림을 못 그렸어. 다시 그려 볼래?"));
      }
    }
    img.classList.toggle("faded", busy);
    frame.replaceChildren(img);
    if (busy) {
      const writer = diary.writer?.name || "마롱이";
      const syllable = writer.charCodeAt(writer.length - 1) - 0xac00;
      const subject = writer + (syllable >= 0 && syllable <= 11171 && syllable % 28 ? "이" : "가");
      const words = Date.now() - busySince >= 120000
        ? "오래 걸리네. 조금 있다가 다시 열어 줘" : `${subject} 다시 그리는 중이야`;
      frame.append(element("p", "over-picture", words));
      if (Date.now() - busySince >= 120000) {
        status.append(button("새로 보기", () => {
          busySince = Date.now();
          void load(false);
        }, "text-button"));
      }
    }
  }
  picture();
  figure.append(frame, caption, status);
  return figure;
}

function drawReady(diary) {
  const paper = element("article", "paper");
  if (diary.hidden) {
    const strip = element("div", "paper-note", "숨긴 일기야. 넘기기와 달력에는 안 보여");
    const reveal = button("다시 보이게", () => void change("hidden", { hidden: false }), "text-button");
    reveal.disabled = changing;
    strip.append(reveal);
    paper.append(strip);
  }
  const dateLine = element("div", "date-line");
  const weather = button(WEATHER[diary.weather][0], () => {
    weatherOpen = !weatherOpen;
    draw();
    document.querySelector(".weather-options button")?.focus();
  }, "weather-toggle");
  weather.prepend(weatherMark(diary.weather));
  weather.disabled = Boolean(diary.busy || changing);
  weather.setAttribute("aria-expanded", String(weatherOpen));
  weather.setAttribute("aria-label", `마음 날씨, ${WEATHER[diary.weather][0]}`);
  dateLine.append(element("time", "", formatDay(day.date, true)), weather);
  paper.append(dateLine);
  if (weatherOpen) {
    const options = element("div", "weather-options");
    options.setAttribute("role", "radiogroup");
    options.setAttribute("aria-label", "마음 날씨");
    for (const [name, [label]] of Object.entries(WEATHER)) {
      const choice = button(label, () => void change("weather", { revision: diary.revision, weather: name }),
        "weather-toggle");
      choice.prepend(weatherMark(name));
      choice.setAttribute("role", "radio");
      choice.setAttribute("aria-checked", String(name === diary.weather));
      options.append(choice);
    }
    paper.append(options);
  }
  const title = element("div", "title-line");
  title.append(element("small", "", "제목"), element("h2", "", diary.title));
  if (diary.writer) {
    const who = element("p", "diary-writer");
    const face = element("img", "");
    face.alt = "";
    face.src = diary.writer.faceUrl;
    face.addEventListener("error", () => face.remove(), {once: true});
    who.append(face, document.createTextNode(diary.writer.name));
    paper.append(who);
  }
  paper.append(title, drawPicture(diary));
  const feedback = diary.redraw.last?.result;
  const canRedraw = diary.writer?.active !== false;
  if (newScene && canRedraw && !diary.redraw.blocked && !diary.busy) {
    const note = element("p", "paper-note", "글이 바뀌어서 그림이랑 조금 다를 수 있어. 다시 그려 볼래?");
    note.append(button("다시 그리기", () => openSheet("redraw"), "text-button"));
    paper.append(note);
  } else if (feedback === "scene_rejected") {
    const note = element("p", "paper-note", "그 말로는 그릴 수 없어. 이름이나 숫자는 빼고 적어 줘");
    if (canRedraw && !diary.redraw.blocked) note.append(button("다시 적기", () => openSheet("redraw"), "text-button"));
    paper.append(note);
  } else if (feedback === "draw_failed" || feedback === "draw_refused") {
    paper.append(element("p", "paper-note", "지금은 못 그렸어. 조금 있다가 다시 해 볼래?"));
  }
  if (diary.busy === "fix") {
    paper.append(element("p", "paper-note working", "마롱이가 일기를 고치는 중이야"));
  }
  renderManuscript(diary.body, paper);
  const stamping = element("div", "stamping");
  const stamped = Boolean(diary.stampedAt);
  const seal = button(stamped ? "참 잘했어" : "도장 찍어 주기", () => void change("stamp", { stamped: !stamped }), "stamp");
  seal.setAttribute("aria-pressed", String(stamped));
  seal.setAttribute("aria-label", stamped ? "도장 빼기" : "도장 찍어 주기");
  seal.disabled = changing;
  if (stamped) {
    const stampDate = new Intl.DateTimeFormat("ko-KR", { timeZone: KST, month: "long", day: "numeric" })
      .format(new Date(diary.stampedAt));
    stamping.append(element("p", "", `${stampDate}에 찍어 줬어`));
  }
  stamping.append(seal);
  paper.append(stamping);
  const actions = element("div", "work-actions");
  for (const [kind, label] of [["fix", "말로 고치기"], ["redraw", "다시 그리기"]]) {
    if (kind === "redraw" && !canRedraw) continue;
    const slot = element("div");
    const action = button(label, () => openSheet(kind));
    action.setAttribute("aria-label", `${label} · ${diary[kind].left}번 남음`);
    action.disabled = Boolean(diary.busy || diary[kind].blocked);
    slot.append(action, element("p", "caption", `${diary[kind].left}번 남음`));
    if (BLOCKS[diary[kind].blocked]) slot.append(element("p", "caption", BLOCKS[diary[kind].blocked]));
    actions.append(slot);
  }
  view.replaceChildren(paper, actions);
}

function drawEmpty(face, text, action, trace) {
  const node = element("div", "empty");
  const img = element("img");
  img.src = `${FACE}${face}.webp`;
  img.alt = "";
  node.append(img, element("p", "", text));
  if (action) node.append(action);
  if (trace) node.append(element("small", "", trace));
  view.replaceChildren(node);
}

function updatePages() {
  pages.hidden = !day;
  if (!day) return;
  const prev = button(day.prev ? `‹ ${formatDay(day.prev)}` : "‹ 앞 날", () => navigate(day.prev));
  const next = button(day.next ? `${formatDay(day.next)} ›` : "뒷 날 ›", () => navigate(day.next));
  prev.disabled = !day.prev;
  next.disabled = !day.next;
  pages.replaceChildren(prev, next);
}

function draw() {
  const locked = ["permission", "loading"].includes(loadedState);
  calendar.disabled = locked;
  more.disabled = locked;
  view.dataset.state = loadedState;
  view.setAttribute("aria-busy", String(loadedState === "loading"));
  if (day?.diary) drawReady(day.diary);
  else if (loadedState === "loading") {
    const placeholder = element("article", "paper loading");
    placeholder.setAttribute("aria-hidden", "true");
    for (const cls of ["short", "wide", "picture-frame", "manuscript"]) {
      placeholder.append(element("div", `shape ${cls}`));
    }
    const actions = element("div", "work-actions");
    for (const label of ["말로 고치기", "다시 그리기"]) {
      const disabled = button(label, () => {});
      disabled.disabled = true;
      actions.append(disabled);
    }
    view.replaceChildren(placeholder, actions);
  } else if (loadedState === "permission") {
    drawEmpty("13-concerned", "이 계정으로는 일기장을 열 수 없어");
  } else if (loadedState === "error") {
    drawEmpty("06-sad", RETRY, button("다시 해 볼게", () => void load(false)), lastTrouble?.trace);
  } else if (loadedState === "reconnecting") {
    drawEmpty("13-concerned", CONNECTION);
  } else if (EMPTY[loadedState]) {
    let action;
    if (loadedState === "none") action = button("가장 최근 일기 보기", () => navigate(""));
    if (loadedState === "empty") action = button("내 모습 카드 만들기", () => openSheet("look"));
    drawEmpty(...EMPTY[loadedState], action);
  }
  updatePages();
}

const sheets = makeSheets({
  day: () => day,
  close: closeSheet,
  go: navigate,
  showDay(value, { redraw, scene } = {}) {
    if (value.date !== date) return;
    if (redraw !== undefined) expectedRedraw = redraw;
    if (redraw) newScene = false;
    if (scene) newScene = true;
    setDay(value);
  },
  refresh: () => load(false),
  permission,
  blocks: BLOCKS,
});

calendar.addEventListener("click", () => openSheet("calendar"));
more.addEventListener("click", () => {
  if (!menu.hidden) return hideMenu();
  const children = [];
  if (day?.diary && !day.diary.hidden) {
    children.push(button("이 날 숨기기", () => {
      hideMenu();
      void change("hidden", { hidden: true });
    }, "text-button"));
  }
  children.push(button("숨긴 일기", () => openSheet("hidden"), "text-button"),
    button("내 모습 카드", () => openSheet("look"), "text-button"));
  menu.replaceChildren(...children);
  menu.hidden = false;
  more.setAttribute("aria-expanded", "true");
});
document.addEventListener("click", event => {
  if (event.target !== more && !more.contains(event.target) && !menu.contains(event.target)) hideMenu();
});
document.addEventListener("keydown", event => { if (event.key === "Escape") hideMenu(); });
window.addEventListener("popstate", () => {
  const next = location.pathname.slice(BASE.length);
  if (next !== date) void load(true).then(() => sheets.show(location.hash.slice(1)));
  else sheets.show(location.hash.slice(1));
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    setTheme();
    void load(false);
  }
});
window.addEventListener("resize", () => {
  const grid = view.querySelector(".manuscript");
  if (grid && day?.diary) drawGrid(grid, day.diary.body);
});
function updateThemeOnMinute() {
  setTheme();
  setTimeout(updateThemeOnMinute, 60000 - Date.now() % 60000);
}
updateThemeOnMinute();
void load(true).then(() => sheets.show(location.hash.slice(1)));
