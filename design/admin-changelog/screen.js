// SCR-220 목업 그리기(상태: normal filtered filter-empty skipped long empty unreadable loading error). 글은 모두 textContent로 넣어요(SPEC-502). 구현은 admin.js에 같은 모양으로 들어가요.
(function () {
  const params = new URLSearchParams(location.search);
  const state = params.get("state") || "normal";
  const THIS_YEAR = 2026; // 목업 화면을 고정하려고 둔 값. 구현은 한국 시각의 오늘을 써요.
  const AREAS = [["all", "전체"], ["app", "앱"], ["web", "웹"], ["call", "통화"], ["chat", "대화"], ["admin", "관리"], ["legacy", "카톡·디스코드"]];
  const AREA_NAME = Object.fromEntries(AREAS);
  const TYPE_NAME = {added: "추가", improved: "개선", fixed: "수정", removed: "제거"};
  const COLS = [["type", "구분"], ["area", "영역"], ["title", "항목"], ["before", "변경 전"], ["after", "변경 후"], ["ev", "근거"]];
  const root = document.getElementById("admin");
  const chipsBox = root.querySelector(".changes-chips");
  const countBox = root.querySelector(".changes-count");
  const groupsBox = root.querySelector(".changes-groups");
  let data = null;
  let area = state === "filtered" ? "call" : state === "filter-empty" ? "chat" : "all";

  function el(tag, attrs, text) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function day(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    return (y === THIS_YEAR ? "" : y + "년 ") + m + "월 " + d + "일";
  }
  function evLinks(list, parent) {
    list.forEach((e, i) => {
      if (i) parent.append(el("span", {class: "sep"}, " · "));
      const label = e.label.startsWith("PR #") ? e.label : e.label.slice(0, 7);
      parent.append(el("a", {href: e.url, target: "_blank", rel: "noopener noreferrer"}, label));
    });
  }
  function labelled(cls, label, text) {
    const td = el("td", {role: "cell", class: cls});
    td.append(el("span", {class: "c-label"}, label));
    if (text !== undefined) td.append(document.createTextNode(text));
    return td;
  }

  function drawChips(disabled) {
    chipsBox.replaceChildren();
    for (const [key, name] of AREAS) {
      const b = el("button", {type: "button", "aria-pressed": String(key === area)}, name);
      b.disabled = disabled;
      b.addEventListener("click", () => { area = key; drawChips(false); drawList(); });
      const li = el("li");
      li.append(b);
      chipsBox.append(li);
    }
  }

  function unitBlock(u, items) {
    const box = el("article", {class: "change-unit"});
    const head = el("div", {class: "change-unit-head"});
    const title = day(u.sortOn) + " · " + u.title;
    head.append(el("h2", {}, title));
    if (u.backfilled) head.append(el("span", {class: "change-tag"}, "지난 기록에서 채움"));
    const cap = el("p", {class: "caption"});
    const lead = (u.deployedOn ? "" : "반영일 기록 없음 · 날짜는 PR을 합친 날 · ") +
      (u.kind === "app" ? "앱 " + u.app.versionName + "(" + u.app.versionCode + ")" : "서버 반영") + " · ";
    cap.append(document.createTextNode(lead));
    evLinks(u.evidence, cap);
    box.append(head, cap);

    const table = el("table", {class: "change-table", role: "table"});
    table.append(el("caption", {}, title + " 항목"));
    const cg = el("colgroup");
    for (const [k] of COLS) cg.append(el("col", {class: "k-" + k}));
    const thead = el("thead", {role: "rowgroup"});
    const hr = el("tr", {role: "row"});
    for (const [, name] of COLS) hr.append(el("th", {role: "columnheader", scope: "col"}, name));
    thead.append(hr);
    const tbody = el("tbody", {role: "rowgroup"});
    for (const it of items) {
      const tr = el("tr", {role: "row"});
      const type = el("td", {role: "cell", class: "c-type"});
      type.append(el("span", {class: "change-badge", "data-type": it.type}, TYPE_NAME[it.type]));
      tr.append(type, el("td", {role: "cell", class: "c-area"}, AREA_NAME[it.area]), el("td", {role: "cell", class: "c-title"}, it.title));
      for (const k of ["before", "after"]) {
        const td = labelled("c-" + k, k === "before" ? "변경 전" : "변경 후", it[k]);
        if (it[k] === "없음" || it[k] === "기록 없음") td.classList.add("unknown");
        tr.append(td);
      }
      const ev = labelled("c-ev", "근거");
      evLinks(it.evidence, ev);
      tr.append(ev);
      tbody.append(tr);
    }
    table.append(cg, thead, tbody);
    box.append(table);
    return box;
  }

  function message(text, buttonText, onClick) {
    const box = el("div", {class: "changes-message"});
    box.append(el("p", {}, text));
    if (buttonText) {
      const b = el("button", {type: "button", class: "retry"}, buttonText);
      b.addEventListener("click", onClick);
      box.append(b);
    }
    groupsBox.replaceChildren(box);
  }

  function drawList() {
    const units = data.units
      .map((u) => ({u, items: u.items.filter((i) => area === "all" || i.area === area)}))
      .filter((x) => x.items.length);
    countBox.replaceChildren();
    if (units.length) {
      const n = units.reduce((s, x) => s + x.items.length, 0);
      countBox.append(el("p", {class: "caption"}, "반영 " + units.length + "번 · 항목 " + n + "개"));
    }
    // #skipped 줄은 #filter-empty에서도 남겨요(08 화면 정의).
    if (data.skipped) countBox.append(el("p", {class: "changes-note"}, "읽지 못한 내역 파일 " + data.skipped + "개는 빼고 보여요"));
    if (!units.length) {
      message("이 영역의 내역이 없어요", "전체 보기", () => { area = "all"; drawChips(false); drawList(); });
      return;
    }
    groupsBox.replaceChildren(...units.map((x) => unitBlock(x.u, x.items)));
  }

  function loading() {
    drawChips(false);
    const sk = el("div", {class: "changes-skeleton", "aria-hidden": "true"});
    for (let g = 0; g < 2; g++) {
      sk.append(el("span", {class: "s-head"}));
      for (let r = 0; r < (g ? 1 : 2); r++) sk.append(el("span", {class: "s-row"}));
    }
    groupsBox.replaceChildren(sk);
  }

  if (state === "loading") loading();
  else if (state === "error") {
    drawChips(true);
    message("잠깐 문제가 생겼어요. 다시 해 볼까요?", "다시 해 볼게요", () => {});
    root.setAttribute("aria-busy", "false");
  } else {
    data = window.MOCK_CHANGES[state] || window.MOCK_CHANGES.normal;
    root.setAttribute("aria-busy", "false");
    if (!data.units.length) {
      drawChips(true);
      // 파일이 있는데 모두 검사에 걸렸으면 #empty가 아니라 #unreadable이에요.
      message(data.skipped ? "내역 파일 " + data.skipped + "개를 읽지 못했어요" : "아직 적은 업데이트 내역이 없어요");
    } else {
      drawChips(false);
      drawList();
    }
  }

  // 제안(4-7): 처음 그릴 때 지금 탭이 탭 줄 밖이면 탭 줄만 밀어 보이게 해요. 흐림 표시는 지금 admin.js 식 그대로예요.
  const nav = document.querySelector(".admin-nav");
  const tabs = nav.querySelector(".admin-tabs");
  const cur = tabs.querySelector("[aria-current]");
  const over = cur.getBoundingClientRect().right - tabs.getBoundingClientRect().right;
  if (over > 0) tabs.scrollLeft += over;
  nav.dataset.overflow = String(tabs.scrollLeft + tabs.clientWidth < tabs.scrollWidth - 1);

  if (params.has("measure")) {
    const bad = [...document.querySelectorAll(".change-table td, .change-table th, .change-unit-head, .caption, .changes-chips")]
      .filter((n) => n.scrollWidth > n.clientWidth + 1).length;
    const tabRight = Math.max(...[...tabs.children].map((a) => a.getBoundingClientRect().right));
    const out = {
      state, innerWidth, scrollWidth: document.documentElement.scrollWidth,
      tabsFit: tabs.scrollWidth <= tabs.clientWidth, tabRight: Math.round(tabRight), tabsWidth: tabs.clientWidth,
      overflowingCells: bad, currentTabVisible: cur.getBoundingClientRect().right <= tabs.getBoundingClientRect().right + 1 && cur.getBoundingClientRect().left >= tabs.getBoundingClientRect().left - 1,
      chipRows: new Set([...chipsBox.querySelectorAll("button")].map((b) => Math.round(b.getBoundingClientRect().top))).size,
      cols: [...document.querySelectorAll(".change-table thead th")].slice(0, 6).map((t) => Math.round(t.getBoundingClientRect().width)),
      beforeWidth: Math.round((document.querySelector(".c-before") || {getBoundingClientRect: () => ({width: 0})}).getBoundingClientRect().width),
    };
    document.body.append(el("pre", {id: "measure"}, JSON.stringify(out)));
  }
})();
