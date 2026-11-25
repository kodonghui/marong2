(() => {
  "use strict";

  const states = new Map(window.MarongFixture.states.map(state => [state.key, state]));
  const pairedStates = new Set(window.MarongFixture.pairs);
  const elements = Object.fromEntries(
    ["state", "theme", "width", "scenario", "launch", "next", "disconnect", "sim-note", "frames"]
      .map(name => [name, document.getElementById(name)])
  );
  const names = {
    "SCR-001": "통화 홈", "SCR-002": "통화", "SCR-107": "글 대화",
    "SCR-109": "글 대화 메뉴", "SCR-163": "가입", "SCR-164": "로그인",
    "SCR-165": "내 마롱이", "SCR-230": "iOS 시스템 알림"
  };
  const faces = "../../marong/call/static/face/v1/";
  const parameters = new URLSearchParams(location.search);
  const defaultState = "scr-001-notice-ring-ready";
  const counters = { micChecks: 0, acceptRequests: 0, resultChecks: 0, ordinaryStarts: 0, reconnects: 0 };
  let state = states.get(defaultState);
  let activePane = "a";
  let pending = null;
  let reauthenticated = false;
  let targetKind = "ring";
  let acceptedCallId = null;
  let connectedCallId = null;

  function createPane(direction) {
    const figure = document.createElement("figure");
    const titleId = "phone-title-" + direction;
    figure.className = "specimen";
    figure.dataset.pane = direction;
    figure.innerHTML = [
      '<figcaption><h2></h2><p></p></figcaption>',
      '<article class="phone"><header class="phone-header"><img class="small-face" alt=""><span></span></header>',
      '<div class="phone-body"><p class="context-text"></p><section class="card">',
      '<img class="hero" alt="" hidden>',
      '<h3 class="card-title" id="' + titleId + '" tabindex="-1"></h3><p class="card-copy"></p>',
      '<div class="extra" hidden></div><div class="actions inline-actions"></div></section></div>',
      '<footer class="dock"><div class="actions"></div></footer><p class="sr-only" role="status"></p></article>'
    ].join("");
    elements.frames.append(figure);
    const phone = figure.querySelector(".phone");
    const inline = figure.querySelector(".inline-actions");
    return {
      figure, phone, heading: figure.querySelector("h3"), buttons: new Map(),
      controls: direction === "a" ? inline : figure.querySelector(".dock .actions")
    };
  }

  const panes = { a: createPane("a"), b: createPane("b") };

  function keyFor(label) {
    const byLabel = {
      "받기": "accept", "받는 중": "accept", "결과 확인": "result", "결과 확인 중": "result",
      "일반 통화": "ordinary", "알림 탭": "notification", "들어가기": "login",
      "알림 켜기": "enable", "알림 다시 켜기": "enable", "알림 끄기": "disable",
      "변경 확인 중": "saving", "상태 다시 확인": "status", "다시 확인": "resolve",
      "연결 확인": "connection", "끊기": "hangup", "닫기": "back",
      "음소거": "mute", "내 마롱이": "profile", "다시 해 볼게": "mic-retry",
      "다시 걸기": "redial", "글 대화로": "chat", "메시지 입력": "message"
    };
    return byLabel[label] || "example";
  }

  function syncButtons(pane) {
    const keys = state.controls.map(({label}) => keyFor(label));
    for (const [key, node] of pane.buttons) {
      if (!keys.includes(key)) {
        node.remove();
        pane.buttons.delete(key);
      }
    }
    state.controls.forEach((control, index) => {
      const key = keys[index];
      let node = pane.buttons.get(key);
      if (!node) {
        node = document.createElement("button");
        node.type = "button";
        node.dataset.action = key;
        node.addEventListener("click", () => runAction(key, pane.figure.dataset.pane, node));
        pane.buttons.set(key, node);
      }
      node.className = key === "hangup" ? "hangup" : index === 0 ? "primary" : "";
      node.textContent = control.label;
      node.setAttribute("aria-disabled", String(control.disabled));
      if (pane.controls.children[index] !== node) {
        pane.controls.insertBefore(node, pane.controls.children[index] || null);
      }
    });
  }

  function syncExtra(pane) {
    const box = pane.phone.querySelector(".extra");
    if (box.dataset.state === state.key) return;
    box.dataset.state = state.key;
    box.replaceChildren();
    if (state.screen === "SCR-164") {
      const label = document.createElement("label");
      const input = document.createElement("input");
      label.textContent = "기기 추가 코드";
      input.inputMode = "numeric";
      input.pattern = "[0-9]{6}";
      input.maxLength = 6;
      input.required = true;
      input.autocomplete = "off";
      input.placeholder = "숫자 6자리";
      label.append(input);
      box.append(label);
    } else if (state.key === "scr-107-notice-room") {
      for (const text of ["오늘 오후에 산책하고 왔어.", "바람은 좀 선선했어?"]) {
        const bubble = document.createElement("p");
        bubble.className = "bubble";
        bubble.textContent = text;
        box.append(bubble);
      }
    }
    box.hidden = !box.children.length;
  }

  function display(pane, paired) {
    const { figure, phone, heading } = pane;
    const direction = figure.dataset.pane;
    const isSystem = state.screen === "SCR-230";
    const call = state.screen === "SCR-001" || state.screen === "SCR-002";
    figure.querySelector("figcaption h2").textContent = paired ?
      (direction === "a" ? "A · 카드 안 동작" : "B · 하단 동작") :
      (state.inherited ? "기존 화면 연결" : "공용 상태");
    figure.querySelector("figcaption p").textContent =
      state.screen + "#" + state.slug + " · " + elements.width.value + "px";
    phone.dataset.state = state.key;
    phone.dataset.platform = isSystem ? "ios-system" : "web";
    phone.classList.toggle("call-pane", call);
    phone.classList.toggle("call-decision", ["notice-ring-ready", "notice-ring-accepting",
      "notice-ring-result", "notice-ring-result-loading"].includes(state.slug));
    phone.querySelector(".phone-header span").textContent = names[state.screen];
    const smallFace = phone.querySelector(".small-face");
    smallFace.hidden = isSystem;
    if (!isSystem && !smallFace.hasAttribute("src")) smallFace.src = faces + "01-neutral.webp";
    phone.querySelector(".context-text").textContent = isSystem ? "iOS가 표시하고 잠금을 처리합니다." :
      state.screen === "SCR-165" ? "이 기기의 알림" : "";
    phone.querySelector(".context-text").hidden = !(isSystem || state.screen === "SCR-165");
    const card = phone.querySelector(".card");
    card.setAttribute("aria-busy", String(state.kind === "loading"));
    const hero = phone.querySelector(".hero");
    hero.hidden = !call;
    if (call) {
      const emotional = ["error", "permission", "stale"].includes(state.kind);
      hero.src = faces + (emotional ? "13-concerned.webp" : "01-neutral.webp");
    }
    heading.textContent = state.title;
    phone.querySelector(".card-copy").textContent = state.body;
    syncExtra(pane);
    syncButtons(pane);
  }

  function show(key, { focus = "none", pane = activePane } = {}) {
    const next = states.get(key);
    if (!next) return;
    const lastActive = document.activeElement;
    state = next;
    activePane = pane;
    elements.state.value = state.key;
    const paired = pairedStates.has(state.key);
    for (const [direction, entry] of Object.entries(panes)) {
      entry.figure.hidden = !paired && direction !== pane;
      if (!entry.figure.hidden) display(entry, paired);
    }
    const active = panes[pane];
    if (focus === "title") {
      active.phone.querySelector('[role="status"]').textContent = "";
      active.heading.focus({ preventScroll: true });
    } else if (focus === "keep") {
      active.phone.querySelector('[role="status"]').textContent = state.title;
      if (lastActive && !lastActive.isConnected) active.heading.focus({ preventScroll: true });
    }
    if (location.hash.slice(1) !== key) history.replaceState(null, "", "#" + key);
    elements.disconnect.disabled = !["scr-002-talking", "scr-002-notice-reconnecting"].includes(key);
  }

  function queue(message, handler) {
    pending = handler;
    elements.next.disabled = !handler;
    elements["sim-note"].textContent = message;
  }

  function advance() {
    if (!pending) return;
    const respond = pending;
    queue("합성 응답을 화면에 적용합니다.", null);
    respond();
  }

  function resolve(pane, kind = "ring") {
    const scenario = elements.scenario.value;
    if (scenario === "denied") return show("scr-107-notice-denied", { focus: "title", pane });
    if (scenario === "offline") return show("scr-107-notice-unavailable", { focus: "title", pane });
    if (scenario === "reauth-expired" && !reauthenticated)
      return show("scr-164-notice-login", { focus: "title", pane });
    if (kind === "message") return show("scr-107-notice-room", { focus: "title", pane });
    const phoneState = scenario === "reauth-expired" ? "expired" : scenario === "answered" ? "answered" : "ready";
    show("scr-001-notice-ring-" + phoneState, { focus: "title", pane });
  }

  function resolveAgain(pane, kind) {
    if (kind) targetKind = kind;
    show("scr-107-notice-loading", { focus: "title", pane });
    queue("이 예시는 알림의 대상만 조회합니다.", () => resolve(pane, targetKind));
  }

  function verifiedConnection(pane, description, callId) {
    show("scr-002-notice-connecting", { focus: "title", pane });
    queue(description, () => {
      connectedCallId = callId;
      show("scr-002-talking", { focus: "title", pane });
    });
  }

  function reconnect(pane = activePane) {
    if (!["scr-002-talking", "scr-002-notice-reconnecting"].includes(state.key)) return;
    counters.reconnects++;
    show("scr-002-notice-reconnecting", { focus: "keep", pane });
    queue("기존 통화와 클라이언트를 확인한 합성 결과입니다.", () => show("scr-002-talking", { focus: "keep", pane }));
  }

  function runAction(action, pane, node) {
    if (node.getAttribute("aria-disabled") === "true") return;
    switch (action) {
      case "notification":
        resolveAgain(pane, state.slug === "notice-ring" ? "ring" : "message");
        return;
      case "login": {
        const input = panes[pane].phone.querySelector("input");
        if (!input?.reportValidity()) return;
        reauthenticated = true;
        if (state.slug === "notification-settings-login") {
          show("scr-165-notify-loading", { focus: "title", pane });
          queue("현재 설치의 설정만 확인합니다.", () => show("scr-165-notify-off", { focus: "title", pane }));
        } else {
          resolveAgain(pane);
        }
        return;
      }
      case "accept":
        if (state.key !== defaultState) return;
        counters.micChecks++;
        if (elements.scenario.value === "mic-denied") {
          show("scr-002-mic-denied", { focus: "title", pane });
          queue("마이크 권한 거절 · 합성 수락 요청 0건", null);
          return;
        }
        counters.acceptRequests++;
        show("scr-001-notice-ring-accepting", { focus: "keep", pane });
        queue("별도 받기 선택에 대한 합성 응답을 기다립니다.", () => {
          const scenario = elements.scenario.value;
          if (scenario === "accept-expired") return show("scr-001-notice-ring-expired", { focus: "title", pane });
          if (scenario === "answered") return show("scr-001-notice-ring-answered", { focus: "title", pane });
          acceptedCallId = "synthetic-appointment-call";
          if (scenario === "lost") return show("scr-001-notice-ring-result", { focus: "title", pane });
          verifiedConnection(pane, "최초 수락 뒤 같은 통화에 연결하는 예시입니다.", acceptedCallId);
        });
        return;
      case "result":
        if (state.key !== "scr-001-notice-ring-result") return;
        counters.resultChecks++;
        show("scr-001-notice-ring-result-loading", { focus: "keep", pane });
        queue("이미 처리한 수락의 결과를 확인합니다.", () => {
          if (!acceptedCallId) return reconnectFromUnknown(pane);
          verifiedConnection(pane, "기존 통화 결과를 확인했습니다. 새로운 수락은 없습니다.", acceptedCallId);
        });
        return;
      case "ordinary":
        if (state.key !== "scr-001-notice-ring-expired") return;
        counters.ordinaryStarts++;
        verifiedConnection(pane, "만료를 확인한 뒤 별도로 선택한 일반 통화 예시입니다.", "synthetic-ordinary-call");
        return;
      case "connection":
        reconnectFromUnknown(pane);
        return;
      case "mic-retry":
        show(defaultState, { focus: "title", pane });
        return;
      case "hangup":
      case "back":
        queue("미리보기에서 연결을 종료했습니다.", null);
        show("scr-001-notice-call-ended", { focus: "title", pane });
        return;
      case "enable":
      case "disable":
        show("scr-165-notify-saving", { focus: "title", pane });
        queue("명시적 선택에 대한 합성 등록 결과입니다.", () =>
          show(action === "enable" ? "scr-165-notify-active" : "scr-165-notify-revoked", { focus: "title", pane }));
        return;
      case "status":
        if (state.screen === "SCR-165") {
          show("scr-165-notify-loading", { focus: "title", pane });
          queue("현재 설치의 구독 상태를 조회합니다.", () => show("scr-165-notify-off", { focus: "title", pane }));
        } else resolveAgain(pane);
        return;
      case "resolve": resolveAgain(pane); return;
      case "profile": show("scr-165-notify-off", { focus: "title", pane }); return;
      case "chat": show("scr-107-notice-room", { focus: "title", pane }); return;
      case "mute": {
        const on = node.getAttribute("aria-pressed") !== "true";
        node.setAttribute("aria-pressed", String(on));
        node.textContent = on ? "음소거 풀기" : "음소거";
        return;
      }
      default: queue("이 조작은 기존 화면에서 이어집니다.", null);
    }
  }

  function reconnectFromUnknown(pane) {
    queue("여기에서는 연결을 다시 확인합니다. 수락이나 일반 통화를 실행하지 않습니다.", null);
    show("scr-002-notice-call-check", { focus: "keep", pane });
  }

  const screenGroups = new Map();
  for (const row of states.values()) {
    const name = row.inherited ? "기존 화면 연결" : row.screen + " · " + names[row.screen];
    if (!screenGroups.has(name)) {
      const group = document.createElement("optgroup");
      group.label = name;
      elements.state.append(group);
      screenGroups.set(name, group);
    }
    const item = document.createElement("option");
    item.value = row.key;
    item.textContent = row.title + " · " + row.slug;
    screenGroups.get(name).append(item);
  }

  function viewport() {
    document.body.dataset.theme = elements.theme.value;
    elements.frames.style.setProperty("--demo-width", elements.width.value + "px");
  }

  elements.width.value = parameters.get("width") === "430" ? "430" : "360";
  elements.theme.value = parameters.get("theme") === "night" ? "night" : "chestnut";
  viewport();
  elements.width.addEventListener("change", viewport);
  elements.theme.addEventListener("change", viewport);
  elements.state.addEventListener("change", () => {
    queue("선택한 화면 상태입니다.", null);
    show(elements.state.value, { pane: "a" });
  });
  elements.launch.addEventListener("click", () => {
    reauthenticated = false;
    acceptedCallId = null;
    connectedCallId = null;
    Object.keys(counters).forEach(k => { counters[k] = 0; });
    queue("잠금 해제 뒤 알림을 눌러 앱 진입을 확인할 수 있습니다.", null);
    show("scr-230-notice-ring", { focus: "title", pane: "a" });
  });
  elements.next.addEventListener("click", advance);
  elements.disconnect.addEventListener("click", () => reconnect());
  window.addEventListener("hashchange", () => show(location.hash.slice(1), { pane: "a" }));
  window.MarongDemo = {
    inspect: () => ({ state: state.key, acceptedCallId, connectedCallId, ...counters }),
    reconnect
  };
  show(states.has(location.hash.slice(1)) ? location.hash.slice(1) : defaultState, { pane: "a" });
})();
