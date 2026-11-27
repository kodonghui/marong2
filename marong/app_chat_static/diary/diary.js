import { makeSheets } from "./sheets.js";
import { drawStickers, imageSource, moveSticker, paintDecor, resizeSticker, styleSticker } from "./decor.js";

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
let bookStyle, stickers = [], editingStickers = null;
let stickerInventory = [];
let stickerLoading = false;

function requestedSticker() {
  if (!location.hash.startsWith('#sticker=')) return null;
  try { return decodeURIComponent(location.hash.slice('#sticker='.length)); } catch { return null; }
}

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
      error.errors = Array.isArray(body?.errors) ? body.errors : [];
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

function stickerLoadFailed(retry = () => void loadDecor(date, loadId)) {
  showBanner(RETRY);
  banner.append(" ", button("다시 해 볼게", () => { showBanner(); retry(); }, "text-button"));
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
    stickers = [];
    editingStickers = null;
    stickerLoading = false;
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
    if (next.diary && (reset || bookStyle === undefined || !stickers.length)) {
      void loadDecor(date, id);
    }
  } catch (error) {
    readingFailed(error, id);
  }
}

async function loadDecor(forDate, id) {
  if (location.hash === "#stickers" || requestedSticker()) { stickerLoading = true; draw(); }
  try {
    const decor = bookStyle === undefined ? await api("/decor") : bookStyle;
    if (id !== loadId || date !== forDate) return;
    bookStyle = decor;
    if (!decor) return;
    const values = await api(`/days/${forDate}/stickers`);
    if (id !== loadId || date !== forDate) return;
    stickers = values.stickers;
    if ((location.hash === "#stickers" || requestedSticker()) && !editingStickers) {
      await openStickers();
    } else draw();
  } catch (error) {
    if (id !== loadId || date !== forDate) return;
    if (bookStyle === undefined && error.status === 404) bookStyle = null;
    else if (stickerLoading) stickerLoadFailed();
  } finally {
    if (id === loadId && stickerLoading) { stickerLoading = false; draw(); }
  }
}

async function openStickers() {
  if (!bookStyle || !day?.diary || editingStickers) return;
  const current = date;
  stickerLoading = true;
  draw();
  try {
    const reply = await fetch("/chat/api/closet", {cache: "no-store"});
    if (!reply.ok) throw new Error("closet");
    const body = await reply.json();
    if (date !== current) return;
    stickerInventory = body.items.filter(item => item.kind === "sticker" && imageSource(item.thumbUrl));
    editingStickers = stickers.map(sticker => ({...sticker}));
    const selected = stickerInventory.find(item => item.id === requestedSticker());
    if (selected && editingStickers.length < 10) {
      editingStickers.push({itemId: selected.id, imageUrl: selected.thumbUrl, x: 500, y: 500, scale: 100, rotation: 0});
    }
    stickerLoading = false;
    history.replaceState(history.state, "", location.pathname + "#stickers");
    draw();
  } catch {
    stickerLoading = false;
    draw();
    stickerLoadFailed(() => void openStickers());
  }
}

function renderStickerEditor(paper) {
  const panel = element("section", "sticker-editor");
  const fieldTargets = [];
  const label = element("h2", "", "스티커 붙이기");
  const count = element("p", "caption", `${editingStickers.length}/10`);
  panel.append(label, count);
  for (const item of stickerInventory) {
    const add = button(item.name, () => {
      if (editingStickers.length >= 10) return;
      editingStickers.push({itemId: item.id, imageUrl: item.thumbUrl, x: 500, y: 500, scale: 100, rotation: 0});
      draw();
    }, "text-button");
    add.disabled = editingStickers.length >= 10;
    panel.append(add);
  }
  if (editingStickers.length === 10) panel.append(element("p", "caption", "한 장에 10개까지야"));
  if (!stickerInventory.length) {
    const shop = element("a", "text-button", "상점 가기");
    shop.href = "/chat/shop";
    panel.append(element("p", "caption", "스티커는 상점에서 받을 수 있어"), shop);
  }
  for (const [index, sticker] of editingStickers.entries()) {
    const url = imageSource(sticker.imageUrl);
    if (!url) continue;
    const control = button("스티커 " + (index + 1), () => {}, "diary-sticker sticker-movable");
    const image = new Image();
    image.src = url;
    image.alt = '';
    image.draggable = false;
    const handle = element("span", "sticker-handle");
    handle.setAttribute("aria-hidden", "true");
    control.replaceChildren(image, handle);
    control.setAttribute("aria-label", "스티커 " + (index + 1) + " 움직이기");
    paper.append(control);
    styleSticker(control, sticker);
    moveSticker(control, paper, sticker);
    resizeSticker(handle, control, sticker);
    const tools = element("div", "sticker-controls");
    const size = element("input");
    size.type = "range"; size.min = "50"; size.max = "200"; size.value = sticker.scale;
    size.setAttribute("aria-label", "스티커 " + (index + 1) + " 크기");
    size.addEventListener("input", () => { sticker.scale = Number(size.value); styleSticker(control, sticker); });
    const rotation = element("input");
    rotation.type = "range"; rotation.min = "-180"; rotation.max = "180"; rotation.value = sticker.rotation;
    rotation.setAttribute("aria-label", "스티커 " + (index + 1) + " 기울기");
    rotation.addEventListener("input", () => { sticker.rotation = Number(rotation.value); styleSticker(control, sticker); });
    const sizeField = element("div", "sticker-control-field");
    const rotationField = element("div", "sticker-control-field");
    sizeField.append(size);
    rotationField.append(rotation);
    tools.append(sizeField, rotationField, button("떼기", () => {
      editingStickers.splice(index, 1);
      draw();
    }, "text-button"));
    fieldTargets[index] = {tools, control, size, rotation};
    panel.append(tools);
  }
  function clearFieldErrors() {
    panel.querySelectorAll(".sticker-field-error").forEach(note => note.remove());
    for (const {control, size, rotation} of fieldTargets.filter(Boolean)) {
      for (const input of [control, size, rotation]) { input.removeAttribute("aria-invalid"); input.removeAttribute("aria-describedby"); }
    }
  }
  function showFieldErrors(errors) {
    const names = {x: "가로 위치", y: "세로 위치", scale: "크기", rotation: "기울기", itemId: "스티커"};
    const ranges = {x: "가로 위치는 0~1000으로 골라 줘", y: "세로 위치는 0~1000으로 골라 줘",
      scale: "크기는 50~200%로 골라 줘", rotation: "기울기는 -180~180도로 골라 줘"};
    for (const entry of errors.slice(0, 10)) {
      if (!entry || typeof entry !== "object") continue;
      if (!["required", "bad_format", "out_of_range", "wrong_kind"].includes(entry.reason)) continue;
      if (entry.field === "stickers" && entry.index == null) {
        const rule = entry.reason === "required" ? "스티커 목록을 보내야 해" : "스티커 목록 형식을 확인해 줘";
        const note = element("p", "caption sticker-field-error", "다시 한번 확인해 줄래? " + rule);
        label.after(note);
        continue;
      }
      if (!Number.isInteger(entry.index) || entry.index < 0 || entry.index >= fieldTargets.length) continue;
      const fields = fieldTargets[entry.index];
      if (!fields || (!Object.prototype.hasOwnProperty.call(names, entry.field) && entry.field !== "stickers")) continue;
      const name = names[entry.field] || "스티커 정보";
      const rule = entry.reason === "out_of_range" ? ranges[entry.field]
        : entry.reason === "wrong_kind" ? "스티커 아이템을 골라 줘"
        : entry.field === "itemId" ? "스티커를 다시 골라 줘"
        : entry.reason === "required" ? name + " 값을 골라 줘"
        : entry.field === "stickers" ? "스티커 정보를 확인해 줘" : name + "는 숫자로 골라 줘";
      if (!rule) continue;
      const input = entry.field === "scale" ? fields.size : entry.field === "rotation" ? fields.rotation : fields.control;
      const note = element("span", "caption sticker-field-error");
      note.id = `sticker-error-${entry.index}-${entry.field}`;
      note.append(element("span", "", "다시 한번 확인해 줄래?"), document.createElement("br"), element("span", "", rule));
      if (input === fields.control) fields.tools.prepend(note); else input.after(note);
      input.setAttribute("aria-invalid", "true");
      input.setAttribute("aria-describedby", [input.getAttribute("aria-describedby"), note.id].filter(Boolean).join(" "));
    }
  }
  function close() {
    editingStickers = null;
    history.replaceState(history.state, "", location.pathname);
    draw();
  }
  const payload = items => items.map(({itemId, x, y, scale, rotation}) => ({itemId, x, y, scale, rotation}));
  const cancel = button("그만둘래", () => {
    if (JSON.stringify(payload(editingStickers)) === JSON.stringify(payload(stickers)) ||
        window.confirm("안 남기고 나갈까?")) close();
  }, "text-button");
  const save = button("다 했어", async () => {
    clearFieldErrors();
    save.disabled = true;
    cancel.disabled = true;
    save.textContent = "붙이는 중이야…";
    try {
      const result = await api(`/days/${date}/stickers`, {method: "PUT",
        body: {stickers: payload(editingStickers)}});
      stickers = result.stickers;
      close();
    } catch (error) {
      save.disabled = false;
      cancel.disabled = false;
      save.textContent = "다시 해 볼게";
      showBanner(error.code === "too_many_stickers" ? "한 장에 10개까지야"
        : error.code === "not_owned" ? "아직 안 받은 거야"
        : error.code === "cross_site" ? "이 화면에서 다시 해 줘"
        : error.code === "invalid_input" ? "다시 한번 확인해 줄래?" : RETRY);
      if (error.code === "invalid_input") showFieldErrors(error.errors);
      if (error.code === "not_found") {
        const home = element("a", "text-button", "내 마롱이로");
        home.href = "/chat/me";
        banner.replaceChildren(element("span", "", "찾지 못했어"), " ", home);
        banner.hidden = false;
      }
    }
  });
  panel.append(save, cancel);
  return panel;
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
  const alt = diary.writer?.name ? `${diary.writer.name}의 '${diary.title}' 그림` : `마롱이가 그린 '${diary.title}' 그림`;

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
  if (editingStickers || stickers?.length) paper.classList.add("has-stickers");
  paintDecor(paper, view, bookStyle);
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
  if (bookStyle && !editingStickers) {
    drawStickers(paper, stickers);
    actions.append(button("스티커", openStickers, "text-button"));
    const decor = element("a", "text-button", "꾸미기");
    decor.href = "/chat/diary/decor";
    actions.append(decor);
  }
  view.replaceChildren(paper, editingStickers ? renderStickerEditor(paper) : actions);
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
  view.setAttribute("aria-busy", String(loadedState === "loading" || stickerLoading));
  if (stickerLoading) {
    const placeholder = element("article", "paper loading");
    placeholder.setAttribute("aria-hidden", "true");
    for (const cls of ["wide", "picture-frame", "manuscript"]) placeholder.append(element("div", `shape ${cls}`));
    view.replaceChildren(placeholder);
  } else if (day?.diary) drawReady(day.diary);
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
  } else if (requestedSticker() && EMPTY[loadedState]) {
    drawEmpty("01-neutral", "오늘 일기가 생기면 붙일 수 있어요", button("일기장으로 가기", () => navigate("")));
  } else if (location.hash === "#stickers" && EMPTY[loadedState]) {
    drawEmpty("01-neutral", "아직 일기가 없는 날이야", button("일기장으로", () => navigate("")));
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
void load(true).then(() => {
  if (sessionStorage.getItem("diary-decor-saved")) {
    sessionStorage.removeItem("diary-decor-saved");
    showBanner("일기장을 새로 꾸몄어");
  }
  sheets.show(location.hash.slice(1));
});
