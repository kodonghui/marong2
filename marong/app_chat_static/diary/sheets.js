import { api, button, element, formatDay, weatherMark } from "./diary.js";

const LATER = "잠깐 문제가 생겼어. 조금 있다가 다시 해 줘";
const AGAIN = "잠깐 문제가 생겼어. 다시 해 볼래?";
const CROSS_SITE = "이 화면에서 다시 해 줘";
const TITLES = {
  fix: "어디가 달랐어?", redraw: "어떻게 다시 그릴까?",
  calendar: "달력", hidden: "숨긴 일기", look: "내 모습 카드",
};
const LOOK = {
  hair: ["머리 모양", { long: "긴 머리", bob: "단발", short: "짧은 머리", ponytail: "묶은 머리", curly: "곱슬머리" }],
  glasses: ["안경", { none: "안경 없음", round: "동그란 안경", square: "네모 안경" }],
  top: ["윗옷 색", { white: "하양", black: "검정", gray: "회색", navy: "남색",
    beige: "베이지", pink: "분홍", yellow: "노랑", green: "초록" }],
};
const WEATHER_NAMES = { sunny: "맑음", cloudy: "구름", rain: "비", snow: "눈", rainbow: "무지개" };
function monthNow() {
  const parts = new Intl.DateTimeFormat("en", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit" })
    .formatToParts(new Date());
  return `${parts.find(part => part.type === "year").value}-${parts.find(part => part.type === "month").value}`;
}

export function makeSheets(parent) {
  const dialog = document.querySelector("#sheet");
  let kind, body, flash, generation = 0, retry, timer, flashTimer;
  const pending = new Set();
  const requestKeys = new Map();
  const stashKey = (type, date = parent.day()?.date || "latest") => `marong-diary:${date}:${type}`;
  const valid = version => version === generation && dialog.open;

  function close() {
    clearTimeout(retry);
    clearInterval(timer);
    clearTimeout(flashTimer);
    kind = "";
    generation++;
    if (dialog.open) dialog.close();
  }

  function clear(type) {
    sessionStorage.removeItem(stashKey(type));
  }

  function show(type) {
    if (!TITLES[type] || (["fix", "redraw"].includes(type) && !parent.day()?.diary)) {
      close();
      return;
    }
    if (kind === type && dialog.open) return;
    close();
    kind = type;
    const version = generation;
    dialog.className = ["fix", "redraw"].includes(type) ? "" : "full";
    dialog.setAttribute("aria-labelledby", "sheet-title");
    const header = element("header");
    const title = element("h2", "", TITLES[type]);
    title.id = "sheet-title";
    header.append(button("닫기", () => parent.close(), "text-button"), title);
    body = element("div", "sheet-body");
    flash = element("p", "sheet-toast");
    flash.setAttribute("role", "status");
    flash.hidden = true;
    dialog.replaceChildren(header, body, flash);
    dialog.showModal();
    if (type === "fix" || type === "redraw") editor(type, version);
    if (type === "calendar") calendar(version);
    if (type === "hidden") hidden(version);
    if (type === "look") look(version);
  }

  dialog.addEventListener("cancel", event => {
    event.preventDefault();
    parent.close();
  });
  dialog.addEventListener("click", event => {
    if (event.target === dialog) {
      const bounds = dialog.getBoundingClientRect();
      if (event.clientY < bounds.top || event.clientX < bounds.left || event.clientX > bounds.right) parent.close();
    }
  });

  function announce(words) {
    flash.textContent = words;
    flash.hidden = false;
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => { flash.hidden = true; }, 3000);
  }

  function errorBox(error, action) {
    const words = error.code === "cross_site" ? CROSS_SITE : error.status === 503 ? LATER : AGAIN;
    const box = element("div", "sheet-error");
    box.setAttribute("role", "status");
    box.append(element("p", "", words));
    if (error.trace && error.status !== 503 && error.code !== "cross_site") box.append(element("small", "", error.trace));
    if (error.code !== "cross_site") box.append(button("다시 해 볼게", action, "text-button"));
    return box;
  }

  function schedule(error, version, work, delay) {
    if (error.status === 503 && valid(version)) {
      clearTimeout(retry);
      retry = setTimeout(() => {
        if (valid(version)) void work(Math.min(delay * 2, 30000));
      }, delay);
    }
  }

  function skeleton(count) {
    const box = element("div", "loading");
    box.setAttribute("aria-hidden", "true");
    for (let i = 0; i < count; i++) box.append(element("div", "shape wide"));
    return box;
  }

  function editor(type, version) {
    const fixing = type === "fix";
    const date = parent.day().date;
    const keyName = stashKey(type, date);
    const label = fixing ? "고쳐 줘" : "다시 그려 줘";
    let limitedUntil = 0;
    let blocked = false;
    const form = element("form");
    const labelNode = element("label", "", fixing
      ? "고쳐 줄 말을 적어 줘. 예: 떡볶이가 아니라 라면이었어"
      : "바꿀 점을 적어 줘. 안 적으면 같은 장면으로 새로 그려");
    labelNode.htmlFor = "change-note";
    const textarea = element("textarea");
    textarea.id = labelNode.htmlFor;
    textarea.value = sessionStorage.getItem(keyName) || "";
    const count = element("p", "sheet-note");
    const status = element("p", "sheet-error");
    status.setAttribute("role", "status");
    const submit = element("button", "button primary", label);
    submit.type = "submit";
    const actions = element("div", "sheet-actions");
    actions.append(submit);
    const left = element("p", "sheet-note");
    form.append(labelNode);
    if (!fixing) form.append(element("p", "sheet-note", "이름이나 숫자는 그림에 넣지 않아"));
    form.append(textarea, count, left, status, actions);
    body.append(form);

    function sync() {
      const running = pending.has(keyName);
      const seconds = Math.max(0, Math.ceil((limitedUntil - Date.now()) / 1000));
      const length = Array.from(fixing ? textarea.value.trim() : textarea.value).length;
      const diary = parent.day()?.diary;
      count.textContent = `${length}/200`;
      left.textContent = `${diary?.[type].left || 0}번 더 ${fixing ? "고칠" : "그릴"} 수 있어`;
      submit.disabled = running || blocked || Boolean(seconds) || !diary || length > 200 || (fixing && !length);
      textarea.disabled = running;
      if (seconds) status.textContent = `너무 빨라! 조금 있다가 해 줘 (${seconds}초)`;
      else if (limitedUntil) {
        limitedUntil = 0;
        status.textContent = "";
        clearInterval(timer);
      }
    }

    textarea.addEventListener("input", () => {
      sessionStorage.setItem(keyName, textarea.value);
      requestKeys.delete(keyName);
      if (!limitedUntil && !blocked) status.textContent = "";
      submit.textContent = label;
      sync();
    });
    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (submit.disabled || pending.has(keyName)) return;
      const note = fixing ? textarea.value.trim() : textarea.value;
      const revision = parent.day()?.diary?.revision;
      if (!revision) return;
      const request = requestKeys.get(keyName) || { key: crypto.randomUUID(), revision };
      requestKeys.set(keyName, request);
      pending.add(keyName);
      status.textContent = fixing ? "마롱이가 고치는 중이야…" : "보내는 중…";
      sync();
      try {
        const output = await api(`/days/${date}/${fixing ? "fixes" : "drawings"}`, {
          method: "POST", key: request.key, timeout: fixing ? 45000 : 12000,
          body: { revision: request.revision, [fixing ? "text" : "change"]: note },
        });
        requestKeys.delete(keyName);
        if (fixing) sessionStorage.removeItem(keyName);
        if (valid(version)) parent.close();
        parent.showDay(output.day, { redraw: !fixing, scene: output.sceneChanged });
      } catch (error) {
        if (error.status && error.code !== "network") requestKeys.delete(keyName);
        if (!valid(version) || parent.permission(error)) return;
        if (error.code === "stale_revision") {
          await parent.refresh();
          status.textContent = "그 사이 일기가 바뀌었어. 새로 보여 줄게";
        } else if (["busy", "not_ready", "fix_limit"].includes(error.code)) {
          parent.close();
          void parent.refresh();
        } else if (error.code === "too_many_requests") {
          limitedUntil = Date.now() + error.retryAfter * 1000;
          clearInterval(timer);
          timer = setInterval(sync, 250);
        } else if (parent.blocks[error.code]) {
          blocked = true;
          status.textContent = parent.blocks[error.code];
        } else if (error.code === "fix_failed") {
          status.textContent = "지금은 못 고쳤어. 조금 있다가 다시 해 볼래?";
          submit.textContent = "다시 보내기";
        } else if (error.status === 400) {
          status.textContent = "뭔가 잘못 보냈나 봐. 다시 해 볼게";
        } else {
          const words = error.code === "cross_site" ? CROSS_SITE : error.status === 503 ? LATER : AGAIN;
          status.textContent = error.trace && words === AGAIN ? `${words} (${error.trace})` : words;
          submit.textContent = "다시 보내기";
        }
      } finally {
        pending.delete(keyName);
        if (valid(version)) sync();
      }
    });
    sync();
  }

  function calendar(version) {
    let month = parent.day()?.date.slice(0, 7) || monthNow();
    let request = 0;
    const header = element("div", "month-bar");
    const title = element("h3");
    const area = element("div");
    function shift(delta) {
      const [year, number] = month.split("-").map(Number);
      month = new Date(Date.UTC(year, number - 1 + delta, 1)).toISOString().slice(0, 7);
      void load(5000);
    }
    const prior = button("‹ 앞 달", () => shift(-1), "text-button");
    const next = button("뒷 달 ›", () => shift(1), "text-button");
    header.append(prior, title, next);
    body.append(header, area, element("p", "sheet-note", "새벽 4시 전에 한 얘기는 전날 일기에 들어가"));

    function grid(values, loading) {
      const [year, number] = month.split("-").map(Number);
      const first = new Date(Date.UTC(year, number - 1, 1)).getUTCDay();
      const last = new Date(Date.UTC(year, number, 0)).getUTCDate();
      const node = element("div", `month-grid${loading ? " loading" : ""}`);
      for (const char of "일월화수목금토") node.append(element("span", "", char));
      for (let i = 0; i < 42; i++) {
        const n = i - first + 1;
        if (n < 1 || n > last) {
          node.append(element("span", "calendar-day"));
          continue;
        }
        const key = `${month}-${String(n).padStart(2, "0")}`;
        const row = values.get(key);
        const cell = button(String(n), () => parent.go(key), "calendar-day");
        cell.disabled = !row;
        let accessible = formatDay(key);
        if (row) {
          cell.append(weatherMark(row.weather));
          const words = element("span", "calendar-weather", WEATHER_NAMES[row.weather]);
          words.setAttribute("aria-hidden", "true");
          cell.append(words);
          accessible += `, ${WEATHER_NAMES[row.weather]}`;
          if (row.stamped) {
            const mark = element("span", "stamp-mark", "◎");
            mark.setAttribute("aria-hidden", "true");
            cell.append(mark);
            accessible += ", 도장";
          }
        } else if (loading) cell.append(element("span", "shape", "•"));
        if (key === parent.day()?.date) cell.setAttribute("aria-current", "date");
        cell.setAttribute("aria-label", accessible);
        node.append(cell);
      }
      area.replaceChildren(node);
    }

    async function load(delay = 5000) {
      clearTimeout(retry);
      const id = ++request;
      const [year, number] = month.split("-").map(Number);
      title.textContent = `${year}년 ${number}월`;
      next.disabled = month >= monthNow();
      grid(new Map(), true);
      try {
        const { days } = await api(`/days?month=${month}`);
        if (!valid(version) || id !== request) return;
        grid(new Map(days.map(item => [item.date, item])), false);
        if (!days.length) area.append(element("p", "sheet-note", "이 달에는 일기가 없어"));
      } catch (error) {
        if (!valid(version) || id !== request || parent.permission(error)) return;
        if (error.status === 503) area.prepend(errorBox(error, load));
        else area.replaceChildren(errorBox(error, load));
        schedule(error, version, load, delay);
      }
    }
    void load();
  }

  function hidden(version) {
    const items = element("div");
    const footer = element("div");
    body.append(items, footer);
    let before = null;
    let loading = false;

    function row(item) {
      const node = element("div", "hidden-row");
      const open = button(`${formatDay(item.date)} · ${item.title}`, () => parent.go(item.date), "text-button hidden-title");
      const errorSlot = element("div", "hidden-row-error");
      const reveal = button("다시 보이게", async () => {
        reveal.disabled = true;
        errorSlot.replaceChildren();
        try {
          const value = await api(`/days/${item.date}/hidden`, { method: "PUT", body: { hidden: false } });
          if (!valid(version)) return;
          node.remove();
          parent.showDay(value);
          announce("다시 보이게 했어");
          if (!items.children.length && !before) empty();
        } catch (error) {
          if (!valid(version) || parent.permission(error)) return;
          if (error.code === "not_ready") void load();
          else errorSlot.replaceChildren(errorBox(error, () => reveal.click()));
        } finally {
          reveal.disabled = false;
        }
      }, "button");
      node.append(open, reveal, errorSlot);
      return node;
    }

    function empty() {
      items.replaceChildren(element("p", "", "숨긴 일기가 없어. 일기장 ⋯에서 날마다 숨길 수 있어"));
    }

    async function load(delay = 5000, append = false) {
      if (loading) return;
      loading = true;
      footer.replaceChildren();
      if (!append) items.replaceChildren(skeleton(4));
      const query = append && before ? `?before=${before}` : "";
      try {
        const data = await api(`/hidden${query}`);
        if (!valid(version)) return;
        if (!append) items.replaceChildren();
        items.append(...data.items.map(row));
        before = data.nextBefore;
        if (!items.children.length) empty();
        if (before) footer.append(button("더 보기", () => void load(5000, true), "text-button"));
      } catch (error) {
        if (!valid(version) || parent.permission(error)) return;
        const box = errorBox(error, () => void load(5000, append));
        if (append) footer.append(box);
        else items.replaceChildren(box);
        schedule(error, version, wait => load(wait, append), delay);
      } finally {
        loading = false;
      }
    }
    void load();
  }

  function look(version) {
    const key = stashKey("look");
    let selected = {};
    let saved = null;
    let busy = false;
    let status = null;
    let lastAction = null;

    function render() {
      if (!valid(version)) return;
      const nodes = [];
      if (!saved) nodes.push(element("p", "", "카드가 없으면 그림에 너는 안 나와. 고르면 다음 그림부터 너도 그려 줄게"));
      for (const [field, [label, options]] of Object.entries(LOOK)) {
        const set = element("fieldset");
        const choices = element("div", "choices");
        choices.setAttribute("role", "radiogroup");
        choices.setAttribute("aria-label", label);
        for (const [value, title] of Object.entries(options)) {
          const chip = button(title, () => {
            selected[field] = value;
            status = null;
            render();
            body.querySelector(`[data-value="${field}-${value}"]`)?.focus();
          });
          chip.dataset.value = `${field}-${value}`;
          chip.setAttribute("role", "radio");
          chip.setAttribute("aria-checked", String(selected[field] === value));
          chip.disabled = busy;
          if (field === "top") chip.prepend(element("span", `swatch ${value}`));
          choices.append(chip);
        }
        set.append(element("legend", "", label), choices);
        nodes.push(set);
      }
      const complete = Object.keys(LOOK).every(field => Boolean(selected[field]));
      if (complete) {
        nodes.push(element("p", "look-preview",
          `그림에서 너는 ${LOOK.hair[1][selected.hair]}, ${LOOK.glasses[1][selected.glasses]}, ${LOOK.top[1][selected.top]} 윗옷이야`));
      }
      const bar = element("div", "sheet-actions");
      const save = button("저장", () => void write("PUT"), "button primary");
      save.disabled = busy || !complete || Object.keys(LOOK).every(field => selected[field] === saved?.[field]);
      bar.append(save);
      if (saved) {
        const erase = button("카드 비우기", () => void write("DELETE"));
        erase.disabled = busy;
        bar.append(erase);
      }
      nodes.push(bar);
      if (saved) nodes.push(element("p", "sheet-note", "이미 그린 그림은 그대로야. 다시 그리기로 새로 그릴 수 있어"));
      if (busy) nodes.push(element("p", "sheet-note working", "저장하는 중…"));
      if (status) nodes.push(errorBox(status, () => void write(lastAction)));
      body.replaceChildren(...nodes);
    }

    async function write(method) {
      if (busy) return;
      busy = true;
      status = null;
      lastAction = method;
      render();
      try {
        const data = await api("/look", { method, body: method === "PUT" ? selected : undefined });
        if (!valid(version)) return;
        saved = data?.look || null;
        selected = { ...saved };
        sessionStorage.removeItem(key);
        announce(saved ? "다음 그림부터 이 모습으로 그릴게" : "이제 그림에 너는 안 나와. 마롱이랑 물건·장소만 그릴게");
      } catch (error) {
        if (!valid(version)) return;
        if (error.status === 401) sessionStorage.setItem(key, JSON.stringify(selected));
        if (!parent.permission(error)) status = error;
      } finally {
        busy = false;
        render();
      }
    }

    async function load(delay = 5000) {
      body.replaceChildren(skeleton(3));
      try {
        const data = await api("/look");
        if (!valid(version)) return;
        saved = data.look;
        const resumed = sessionStorage.getItem(key);
        selected = resumed ? JSON.parse(resumed) : { ...saved };
        sessionStorage.removeItem(key);
        render();
      } catch (error) {
        if (!valid(version) || parent.permission(error)) return;
        body.replaceChildren(errorBox(error, load));
        schedule(error, version, load, delay);
      }
    }
    void load();
  }

  return { show, close, clear };
}
