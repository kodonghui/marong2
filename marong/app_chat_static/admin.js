'use strict';

(() => {
  const {node, button, link, request: sendRequest, signal, shortDate} = Unified;
  const root = '/chat/admin';
  const base = root + '/api';
  const screen = document.getElementById('admin');
  const nav = document.querySelector('.admin-nav');
  const tabs = document.querySelector('.admin-tabs');
  const refreshBar = document.querySelector('.admin-refresh');
  const content = node('div');
  const notice = node('p', '', 'caption');
  const page = location.pathname.slice(root.length).split('/')[1] || 'overview';
  const friendId = location.pathname.slice(root.length).split('/')[2]?.replace(/^0+(?=\d)/, '');
  const kinds = {join: '새 사람', link: '기존 계정 연결', relogin: '다시 로그인'};
  const states = {open: '열림', expired: '기간 지남', revoked: '거둠', used: '씀'};
  const limitModes = {unlimited: '무제한', default: '기본 한도', custom: '직접 정하기'};
  const invalidNumbers = '숫자를 확인해 주세요(하루 1~100000, 통화 월 0.01~1000)';
  const dayMs = 86_400_000;
  const unavailable = '지금 못 불러왔어요';
  const phoneEmpty = '90일 안에 보고한 폰이 없어요';
  let data, controls, invites, inviteRows, inviteFilter = 'open', currentMember, memberContent;
  let loading = false, writing = false, hiddenAt = null;
  let pendingRequest = Promise.resolve();
  notice.hidden = true;
  notice.setAttribute('role', 'status');
  screen.append(notice, content);

  function request(url, ...args) {
    pendingRequest = pendingRequest.then(() => sendRequest(url, ...args));
    return pendingRequest;
  }

  function fail(target, reply, retry, slot) {
    signal(target, '잠깐 문제가 생겼어요. 다시 해 볼까요?', reply);
    if (retry && !slot.querySelector('[data-retry]')) {
      const again = button('다시 해 볼게요', () => { again.remove(); retry(); }, 'btnt');
      again.dataset.retry = '';
      slot.append(again);
    }
  }

  function forbidden(reply) {
    if (reply.status !== 403 || reply.body?.code === 'cross_site') return false;
    nav?.remove();
    const message = node('p', '관리자만 볼 수 있어요');
    message.setAttribute('role', 'status');
    screen.replaceChildren(message);
    return true;
  }

  function failure(slot, reply, retry = load) {
    if (forbidden(reply)) return;
    const error = node('p', '', 'err');
    error.setAttribute('role', 'status');
    const heading = slot.firstElementChild;
    slot.replaceChildren(...(heading?.tagName === 'H2' ? [heading, error] : [error]));
    fail(error, reply, retry, slot);
  }

  async function write(path, payload, method = 'POST') {
    writing = true;
    try {
      return await request(base + path, payload, method);
    } finally {
      writing = false;
    }
  }

  function group(title, ...children) {
    const panel = node('section', '', 'stack');
    if (title) panel.append(node('h2', title));
    panel.append(...children);
    return panel;
  }

  function grid(name, ...children) {
    const box = node('div', '', 'admin-grid admin-' + name);
    box.append(...children);
    return box;
  }

  function loadingRows(count) {
    return Array.from({length: count}, () => node('div', '', 'admin-placeholder'));
  }

  const caption = text => node('p', text, 'caption');
  const memberPath = id => root + '/members/' + id;
  const invitePath = (kind, id) => root + '/invites?kind=' + kind + '&friend=' + id;
  const money = amount => amount === null ? '—' : '$' + amount;
  const monthName = month => (month || '').replace(/^(\d{4})-0?(\d+)$/, '$1년 $2월');
  const minutes = seconds => Math.floor(seconds / 60);
  const severity = call => call.state === 'ok' ? '' : call.state === 'warn' ? 'admin-warn' : 'danger';

  function progress(call) {
    const bar = node('progress', '', 'progress ' + severity(call));
    bar.max = 100;
    bar.value = Math.min(100, call.percent);
    bar.setAttribute('aria-label', '통화 월 예산 사용률 ' + call.percent + '%');
    return bar;
  }

  function usageLine(usage) {
    return '글 ' + usage.chatTurns + ' · 통화 ' + minutes(usage.callSeconds) + '분 · 그림 ' + usage.images;
  }

  const attentionMessages = {
    call_budget: (n, danger) => danger ? '통화 월 예산을 넘었어요(' + n + '%) · 새 통화가 막혀요'
      : '통화 월 예산 ' + n + '% 썼어요',
    image_budget: (n, danger) => danger ? '다 쓴 그림 예산이 있어요(' + n + '%) · 비용에서 종류를 봐요'
      : '그림 예산 ' + n + '% 썼어요',
    app_paused: () => '앱 업데이트를 멈춰 둔 상태예요',
    app_behind: (n, danger) => danger ? '설치가 멈춘 폰 ' + n + '대 · 확인 창 기다림이나 실패'
      : '새 버전을 아직 받지 못한 폰 ' + n + '대',
    invite_expiring: n => '24시간 안에 끝나는 초대 링크 ' + n + '개',
    unlinked_friend: n => '아직 잇지 않은 기존 친구 ' + n + '명',
  };

  function overview(data) {
    const attention = group('손볼 일');
    const now = group('지금');
    const cards = node('div', '', 'stack admin-cards');
    now.append(cards);
    if (!data) {
      attention.append(...loadingRows(1));
      cards.append(...loadingRows(5));
    } else {
      for (const item of data.attention) {
        if (!Object.hasOwn(attentionMessages, item.kind)) continue;
        const urgent = item.level === 'danger';
        const row = link('', item.target, 'card admin-record' + (urgent ? ' admin-alert-danger' : ''));
        const label = node('span');
        const dot = node('span', '●', 'admin-alert-dot ' + (urgent ? 'danger' : 'admin-warn'));
        dot.setAttribute('aria-hidden', 'true');
        label.append(dot, attentionMessages[item.kind](item.value, urgent));
        row.append(label);
        attention.append(row);
      }
      if (attention.children.length === 1) attention.append(caption('지금 손볼 일 없어요'));
      const {members, usageToday: usage, callMonth: call, images, app} = data;
      const appLine = app && (app.latest ? '최신 ' + app.latest.versionName + ' · 폰 ' + app.devices +
        '대 중 ' + app.behind + '대 뒤처짐' : '아직 올린 버전이 없어요');
      const rows = [
        ['회원', 'members', members.count + '명 · 잇지 않은 친구 ' + members.unlinked + '명'],
        ['오늘', 'members', usage && '단위 ' + usage.units + ' · ' + usageLine(usage)],
        ['통화', 'costs', call && monthName(call.month) + '(UTC) ' + money(call.spentUsd) + ' / ' +
          money(call.budgetUsd) + ' · ' + call.percent + '%'],
        ['그림', 'costs', images && monthName(images.month) + ' ' + money(images.totalUsd) +
          (images.budgetPercent === null ? '' : ' · 예산 ' + images.budgetPercent + '%')],
        ['앱', 'app', appLine],
      ];
      for (const [title, target, value] of rows) {
        const card = link('', root + '/' + target, 'card admin-record');
        card.append(node('h2', title), caption(value || unavailable));
        if (title === '통화' && call) card.append(progress(call));
        if (title === '앱' && app?.paused) card.append(node('p', '업데이트 멈춤 중', 'admin-warn'));
        cards.append(card);
      }
    }
    content.replaceChildren(grid('overview', attention, now));
  }

  function labeled(label, control) {
    const item = node('label', label, 'field-label');
    item.append(control);
    return item;
  }

  function showCreated(body) {
    const panel = node('div', '', 'card');
    const address = node('p', body.url, 'invite-url');
    const copy = button('복사', async () => {
      try {
        await navigator.clipboard.writeText(body.url);
        copy.textContent = '복사했어요';
      } catch {
        const range = document.createRange();
        range.selectNodeContents(address);
        const selection = getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
      }
    }, 'btn2');
    panel.append(address, node('p', '이 주소는 지금만 보여요. 복사해서 직접 전해 주세요', 'caption'),
      node('p', '만료 ' + shortDate(body.expiresAt) + '(' + daysUntil(body.expiresAt) + '일 뒤)', 'caption'),
      actions(copy, button('닫기', resetControls, 'btnt')));
    controls.replaceChildren(panel);
  }

  const daysUntil = iso => Math.max(0, Math.ceil((Date.parse(iso) - Date.now()) / dayMs));

  function inviteDates(invite) {
    const created = '만든 때 ' + shortDate(invite.createdAt);
    if (invite.state === 'used') return created + ' · 쓴 때 ' + shortDate(invite.usedAt);
    if (invite.state === 'revoked') return created + ' · 거둔 때 ' + shortDate(invite.revokedAt);
    if (invite.state === 'expired') return created + ' · 만료됨 ' + shortDate(invite.expiresAt);
    const days = daysUntil(invite.expiresAt);
    const left = Date.parse(invite.expiresAt) - Date.now() < dayMs ? '오늘 끝나요' : days + '일 남음';
    return created + ' · 만료 ' + shortDate(invite.expiresAt) + '(' + left + ')';
  }

  function inviteForm(kind = 'join', friend = '') {
    const card = node('form', '', 'card stack');
    const choices = node('div', '', 'row');
    choices.setAttribute('role', 'group');
    choices.setAttribute('aria-label', '종류');
    for (const [value, label] of Object.entries(kinds)) {
      const chip = button(label, () => { kind = value; fill(); }, 'btn2');
      chip.dataset.kind = value;
      choices.append(chip);
    }
    const people = node('select');
    const person = labeled('사람 고르기', people);
    const note = node('input');
    note.maxLength = 40;
    const feedback = node('p', '', 'err');
    feedback.setAttribute('role', 'status');
    const submit = node('button', '만들기', 'btn');
    submit.type = 'submit';
    function fill() {
      person.hidden = kind === 'join';
      for (const chip of choices.children) {
        const selected = chip.dataset.kind === kind;
        chip.setAttribute('aria-pressed', String(selected));
        chip.className = selected ? 'btn' : 'btn2';
      }
      people.replaceChildren();
      const empty = node('option', '사람 고르기');
      empty.value = '';
      people.append(empty);
      const source = invitePeople(kind);
      for (const item of source) {
        const option = node('option', item.name);
        option.value = item.friendId;
        people.append(option);
      }
    }
    fill();
    people.value = friend;
    const close = button('닫기', resetControls, 'btnt');
    card.append(choices, person, labeled('메모', note), feedback, actions(submit, close));
    card.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (submit.disabled || writing || loading) return;
      signal(feedback);
      const payload = {kind, note: note.value};
      if (kind !== 'join') {
        if (!people.value) { signal(feedback, '입력을 확인해 주세요'); return; }
        payload.friendId = Number(people.value);
      }
      const inputs = [submit, ...choices.children, people, note, close];
      for (const control of inputs) control.disabled = true;
      const reply = await write('/invites', payload);
      for (const control of inputs) control.disabled = false;
      if (reply.status === 201) {
        showCreated(reply.body);
        await refreshInvites();
      } else if (reply.status === 400) signal(feedback, '입력을 확인해 주세요');
      else if (reply.status === 404) {
        signal(feedback, '그 사람을 찾을 수 없어요. 목록을 다시 불러올게요');
        const members = await request(base + '/members');
        if (members.status === 200) data = members.body;
        fill();
      } else if (!forbidden(reply)) fail(feedback, reply, () => card.requestSubmit(), card);
    });
    controls.replaceChildren(card);
  }

  function resetControls() {
    controls.replaceChildren(actions(button('새 링크 만들기', () => inviteForm())));
  }

  function actions(...children) {
    const row = node('div', '', 'admin-actions');
    row.append(...children);
    return row;
  }

  function invitePeople(kind) {
    return kind === 'link' ? [...data.unlinked, ...data.members] : data.members;
  }

  function showInvites() {
    const chips = actions(...[['open', '열림'], ['all', '전체']].map(([value, label]) => {
      const selected = inviteFilter === value;
      const chip = button(label, () => {
        inviteFilter = value;
        showInvites();
        invites.querySelector('[aria-pressed="true"]')?.focus();
      }, selected ? 'btn' : 'btn2');
      chip.setAttribute('aria-pressed', String(selected));
      return chip;
    }));
    const list = node('ul', '', 'stack records');
    for (const invite of inviteRows) {
      if (inviteFilter === 'open' && invite.state !== 'open') continue;
      const item = node('li', '', ['expired', 'revoked'].includes(invite.state) ? 'card caption' : 'card');
      const used = invite.usedBy ? '(' + invite.usedBy.name + ')' : '';
      item.append(node('p', kinds[invite.kind] + (invite.note ? ' · ' + invite.note : '')),
        caption(states[invite.state] + used), caption(inviteDates(invite)));
      if (invite.state === 'open') {
        const revoke = button('거두기', () => confirmInviteRevoke(invite, controls), 'btn2 danger');
        const controls = actions(revoke);
        item.append(controls);
      }
      list.append(item);
    }
    if (!list.children.length) {
      const empty = node('li');
      empty.append(caption(inviteFilter === 'open' ? '열린 초대 링크가 없어요' : '만든 초대 링크가 없어요'));
      if (inviteFilter === 'open') empty.append(button('전체 보기', () => chips.lastElementChild.click(), 'btnt'));
      list.append(empty);
    }
    invites.replaceChildren(notice, chips, list);
  }

  async function refreshInvites() {
    const reply = await request(base + '/invites');
    if (reply.status === 200) {
      inviteRows = reply.body.invites;
      showInvites();
    } else failure(invites, reply, refreshInvites);
  }

  function confirmInviteRevoke(invite, slot) {
    const error = node('p', '', 'err');
    error.setAttribute('role', 'status');
    const confirm = button('거두기', async () => {
      if (confirm.disabled || loading || writing) return;
      confirm.disabled = cancel.disabled = true;
      const reply = await write('/invites/' + invite.id + '/revoke');
      if (reply.status === 200) {
        inviteRows = inviteRows.map(row => row.id === invite.id ? reply.body.invite : row);
        signal(notice, '링크를 거뒀어요');
        showInvites();
      } else if (reply.status === 409) {
        signal(notice, '이미 쓰였거나 기간이 지난 링크예요');
        await refreshInvites();
      } else if (reply.status === 404) {
        signal(notice, '그 링크를 찾을 수 없어요');
        await refreshInvites();
      } else if (!forbidden(reply)) {
        confirm.disabled = cancel.disabled = false;
        fail(error, reply, () => confirm.click(), slot);
      }
    }, 'btn2 danger');
    const cancel = button('그만두기', () => {
      slot.replaceChildren(original);
      original.focus();
    }, 'btnt');
    const original = slot.firstElementChild;
    slot.replaceChildren(node('p', '이 링크를 거둬요. 받은 사람이 열어도 쓸 수 없어요'),
      actions(confirm, cancel), error);
    cancel.focus();
  }

  async function invitePage(initial) {
    if (initial) {
      controls = group('', ...loadingRows(1));
      invites = group('', ...loadingRows(3));
      content.replaceChildren(grid('invites', controls, invites));
    }
    const inviteReply = await request(base + '/invites');
    if (inviteReply.status !== 200) failure(content, inviteReply);
    const memberReply = await request(base + '/members');
    if (inviteReply.status !== 200) return;
    if (memberReply.status !== 200) { failure(content, memberReply); return; }
    data = memberReply.body;
    inviteRows = inviteReply.body.invites;
    if (initial) {
      const query = new URLSearchParams(location.search);
      const kind = query.get('kind'), friend = query.get('friend');
      if (['link', 'relogin'].includes(kind) && invitePeople(kind).some(member => String(member.friendId) === friend)) {
        inviteForm(kind, friend);
      } else resetControls();
    }
    showInvites();
  }

  function editMember(member, editor, mode) {
    const setting = node('form', '', 'card');
    const feedback = node('p', '', 'err');
    feedback.setAttribute('role', 'status');
    const revoke = mode === 'revoke';
    const value = node('input');
    const confirm = node('button', revoke ? '끊기' : '넣기', revoke ? 'btn2 danger' : 'btn');
    confirm.type = 'submit';
    if (revoke) {
      setting.append(node('p', '이 사람의 모든 기기 로그인을 끊어요. 다시 들어오려면 다시 로그인 링크가 필요해요'));
    } else {
      value.inputMode = 'numeric';
      setting.append(labeled('티켓', value));
    }
    const cancel = button('그만두기', () => {
      editor.replaceChildren();
    }, 'btnt');
    setting.append(feedback, actions(confirm, cancel));
    setting.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (confirm.disabled || writing || loading) return;
      signal(feedback);
      const add = Number(value.value);
      if (!revoke && (!Number.isInteger(add) || add < 1 || add > 1000)) {
        signal(feedback, '1부터 1000까지 넣어 주세요');
        return;
      }
      confirm.disabled = value.disabled = cancel.disabled = true;
      const reply = await write('/members/' + member.friendId + '/' + mode, revoke ? undefined : {add});
      confirm.disabled = value.disabled = cancel.disabled = false;
      if (reply.status === (revoke ? 204 : 200)) {
        if (revoke) member.sessions = 0;
        else member.tickets = reply.body.tickets;
        showMember(member, false);
        signal(notice, revoke ? '로그인을 끊었어요' : '티켓을 넣었어요');
      } else if (!revoke && reply.status === 400) signal(feedback, '1부터 1000까지 넣어 주세요');
      else if (!revoke && reply.status === 404) showMember(null, false);
      else if (!forbidden(reply)) fail(feedback, reply, () => setting.requestSubmit(), setting);
    });
    editor.replaceChildren(setting);
  }

  function memberRows(members, current = null) {
    const list = node('ul', '', 'stack records');
    for (const member of members) {
      const row = link('', memberPath(member.friendId), 'card admin-record');
      if (current && current.friendId === member.friendId) row.setAttribute('aria-current', 'page');
      row.append(node('p', member.name + ' · ' + member.botName + ' ›'), caption(memberLimits(member)),
        caption('오늘 ' + member.usageToday.units + '단위 · 티켓 ' + member.tickets + '장 · 마지막 ' +
          shortDate(member.lastSeenAt)));
      const item = node('li');
      item.append(row);
      list.append(item);
    }
    return list;
  }

  async function membersPage(initial) {
    if (initial) {
      const defaults = node('div', '', 'admin-default');
      defaults.append(...loadingRows(1));
      const joined = group('가입한 사람', ...loadingRows(3));
      joined.classList.add('admin-joined');
      content.replaceChildren(grid('members', defaults, joined));
    }
    const reply = await request(base + '/members');
    if (reply.status !== 200) { failure(content, reply); return; }
    const {members, unlinked, defaults} = reply.body;
    const defaultLine = node('p', '기본 한도 · ' + amounts(defaults, '없음'), 'caption admin-default');
    const joined = group('가입한 사람', members.length ? memberRows(members) : caption('아직 가입한 사람이 없어요'));
    joined.classList.add('admin-joined');
    const older = group('아직 잇지 않은 기존 친구');
    older.classList.add('admin-unlinked');
    for (const member of unlinked) {
      const row = node('div', '', 'card stack');
      row.append(node('p', member.name), actions(link('잇기 링크 만들기', invitePath('link', member.friendId), 'btn2')));
      older.append(row);
    }
    const body = grid('members', defaultLine, joined);
    if (unlinked.length) body.append(older);
    content.replaceChildren(body);
  }

  function phoneLine(phone) {
    return '폰 ' + phone.phone + ' · ' + phone.appVersion + (phone.behind ? ' · 뒤처짐' : '') +
      ' · 마지막 보고 ' + shortDate(phone.seenAt);
  }

  function memberPhones(member, app) {
    const panel = group('이 사람의 폰');
    if (app === undefined) panel.append(...loadingRows(1));
    else if (!app) panel.append(caption(unavailable));
    else {
      const phones = app.devices.filter(device => device.friendId === member.friendId);
      panel.append(...phones.map(phone => caption(phoneLine(phone))));
      if (phones.length === 20) panel.append(caption('최근 보고한 20대만 보여요'));
      if (app.devices.length === 200) panel.append(caption('폰이 많아 일부만 보여요'));
      else if (!phones.length) panel.append(caption(phoneEmpty));
    }
    panel.append(actions(link('앱 버전에서 보기', root + '/app#friend=' + member.friendId, 'btnt')));
    return panel;
  }

  function showMember(member, loadingPhones) {
    currentMember = member;
    const people = group('회원', memberRows(data.members, member));
    people.classList.add('admin-member-list');
    const heading = group('', actions(link('‹ 회원', root + '/members', 'btnt')));
    heading.classList.add('admin-member-heading');
    if (!member) {
      heading.append(node('p', '그 사람을 찾을 수 없어요'),
        actions(link('회원 목록으로', root + '/members', 'btn2')));
      content.replaceChildren(grid('member', people, heading));
      return;
    }
    heading.append(node('h2', member.name + ' · ' + member.botName), notice);
    const limitEditor = node('div'), ticketEditor = node('div'), loginEditor = node('div');
    const limits = group('한도', caption(memberLimits(member)),
      caption('유효 · ' + amounts(member.effective, '없음')), caption('이번 달 통화 ' + money(member.callMonthUsd)),
      actions(button('한도 바꾸기', () => editLimits(member, limitEditor), 'btn2')), limitEditor);
    const today = group('오늘', caption(member.usageToday.units + '단위 · ' + usageLine(member.usageToday)),
      caption('티켓 ' + member.tickets + '장'),
      actions(button('티켓 넣기', () => editMember(member, ticketEditor, 'tickets'), 'btn2')), ticketEditor);
    const login = group('로그인', caption('로그인 ' + member.sessions + '개 · 마지막 ' + shortDate(member.lastSeenAt)),
      actions(link('다시 로그인 링크 만들기', invitePath('relogin', member.friendId), 'btnt'),
        button('로그인 끊기', () => editMember(member, loginEditor, 'revoke'), 'btn2 danger')), loginEditor);
    const app = memberContent?.app ?? null;
    const phonePanel = memberPhones(member, loadingPhones ? undefined : app);
    memberContent = {app, phonePanel};
    content.replaceChildren(grid('member', people, grid('member-content', heading, limits, today, login, phonePanel)));
  }

  async function memberPage(initial) {
    if (initial) {
      const people = group('회원', ...loadingRows(3));
      people.classList.add('admin-member-list');
      const heading = group('', ...loadingRows(1));
      heading.classList.add('admin-member-heading');
      content.replaceChildren(grid('member', people, grid('member-content', heading,
        ...Array.from({length: 4}, () => group('', ...loadingRows(1))))));
    }
    const members = await request(base + '/members');
    if (members.status === 200) {
      data = members.body;
      showMember(data.members.find(member => String(member.friendId) === friendId), true);
    } else failure(content, members);
    const app = await request(base + '/app-versions');
    if (members.status === 200 && currentMember) {
      const phoneData = app.status === 200 ? app.body : null;
      const phones = memberPhones(currentMember, phoneData);
      memberContent.phonePanel.replaceWith(phones);
      memberContent.phonePanel = phones;
      memberContent.app = phoneData;
    }
  }

  function amounts(values, missing) {
    const monthly = values.callMonthlyUsd == null ? missing : '$' + values.callMonthlyUsd;
    return '하루 ' + (values.dailyUnits ?? missing) + ' · 통화 월 ' + monthly;
  }

  function memberLimits(member) {
    if (member.limits.mode === 'unlimited') return '한도 · 무제한';
    if (member.limits.mode === 'default') return '한도 · 기본(' + amounts(member.effective, '없음') + ')';
    return '한도 · 직접(' + amounts(member.limits, '기본 따름') + ')';
  }

  function editLimits(member, editor) {
    const form = node('form', '', 'card stack');
    const modes = node('div', '', 'row');
    const fields = node('div', '', 'stack');
    const daily = node('input');
    daily.inputMode = 'numeric';
    daily.value = member.limits.dailyUnits ?? '';
    const monthly = node('input');
    monthly.inputMode = 'decimal';
    monthly.value = member.limits.callMonthlyUsd ?? '';
    const feedback = node('p', '', 'err');
    feedback.setAttribute('role', 'status');
    feedback.hidden = true;
    const save = node('button', '저장', 'btn');
    save.type = 'submit';
    const cancel = button('그만두기', () => {
      editor.replaceChildren();
    }, 'btnt');
    let mode = member.limits.mode;
    let saving = false;
    const chips = Object.entries(limitModes).map(([value, label]) => {
      const chip = button(label, () => {
        mode = value;
        signal(feedback);
        sync();
      }, 'btn2');
      chip.dataset.mode = value;
      return chip;
    });

    function sync() {
      for (const chip of chips) {
        const selected = chip.dataset.mode === mode;
        chip.setAttribute('aria-pressed', String(selected));
        chip.className = selected ? 'btn' : 'btn2';
        chip.disabled = saving;
      }
      fields.hidden = mode !== 'custom';
      daily.disabled = monthly.disabled = cancel.disabled = saving;
      save.disabled = saving || (mode === 'custom' && !daily.value.trim() && !monthly.value.trim());
    }

    form.addEventListener('input', sync);
    modes.append(...chips);
    fields.append(labeled('하루 사용 단위', daily), labeled('통화 월 달러', monthly),
      node('p', '비운 칸은 기본 한도를 따라요', 'caption'));
    form.append(modes, fields, feedback, actions(save, cancel));
    sync();
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (save.disabled || writing || loading) return;
      const payload = {mode};
      if (mode === 'custom') {
        const count = daily.value.trim();
        const dollars = monthly.value.trim();
        if (count && !/^[0-9]{1,6}$/.test(count)) {
          signal(feedback, invalidNumbers);
          return;
        }
        if (count) payload.dailyUnits = Number(count);
        if (dollars) payload.callMonthlyUsd = dollars;
      }
      saving = true;
      signal(feedback);
      sync();
      const reply = await write('/members/' + member.friendId + '/limits', payload, 'PUT');
      saving = false;
      sync();
      if (reply.status === 200) {
        Object.assign(member, reply.body);
        showMember(member, false);
        signal(notice, '한도를 바꿨어요');
      } else if (reply.status === 400) {
        signal(feedback, invalidNumbers);
      } else if (reply.status === 404) {
        showMember(null, false);
      } else if (!forbidden(reply)) {
        fail(feedback, reply, () => form.requestSubmit(), form);
      }
    });
    editor.replaceChildren(form);
  }

  const eventStates = {
    downloaded: '받음',
    waiting_quiet: '조용할 때 기다림',
    needs_confirm: '확인 창 기다림 · 앱을 열어 지금 설치를 눌러야 해요',
    failed: '설치 실패',
  };

  function updateEvent(event, versions) {
    const version = versions.get(event.versionCode);
    const versionLabel = (version || '') + '(' + event.versionCode + ')';
    let text = event.kind;
    switch (event.kind) {
      case 'pushed': text = '보냄 ' + versionLabel + ' · ' + event.attempt + '번째'; break;
      case 'push_failed': text = '보내기 실패(' + event.status + ') · ' + event.attempt + '번째'; break;
      case 'state':
        text = Object.hasOwn(eventStates, event.state) ? eventStates[event.state] : event.state;
        if (event.state === 'failed') text += '(' + event.status + ')';
        break;
      case 'installed': text = '설치됨 ' + event.appVersion; break;
      case 'fetched': text = '받아 감 ' + versionLabel; break;
    }
    return text + ' · ' + shortDate(event.at);
  }

  function newest(rows) {
    return [...rows].sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
  }

  function appLayout(latest, phones, releases) {
    latest.classList.add('admin-latest');
    content.replaceChildren(grid('app', latest, phones, releases));
  }

  async function appPage(initial) {
    if (initial) appLayout(group('', ...loadingRows(1)), group('폰', ...loadingRows(2)),
      group('버전 기록', ...loadingRows(3)));
    const reply = await request(base + '/app-versions');
    if (reply.status !== 200) { failure(content, reply); return; }
    const {latest, paused, devices, releases, fetches} = reply.body;
    const current = group('', node('h2', latest ? '최신 ' + latest.versionName + '(' + latest.versionCode +
      ') · ' + shortDate(latest.publishedAt) + '에 올림' : '아직 올린 버전이 없어요'));
    if (paused) current.append(node('p', '업데이트 멈춤 중 · 폰이 새로 받지 않아요', 'card admin-warn'));
    const phones = group('폰'), history = group('버전 기록');
    if (!devices.length) phones.append(caption(phoneEmpty));
    if (devices.length === 200) phones.append(caption('폰이 많아 200대까지만 보여요'));
    if (fetches.length === 100) phones.append(caption('받아 간 사람이 많아 100명까지만 보여요'));

    const versions = new Map(releases.filter(release => release.kind === 'published')
      .map(release => [release.versionCode, release.versionName]));
    if (latest) versions.set(latest.versionCode, latest.versionName);
    const friendsByName = new Map(), counts = new Map(), shown = new Map();
    for (const phone of devices) {
      if (!friendsByName.has(phone.friend)) friendsByName.set(phone.friend, new Set());
      friendsByName.get(phone.friend).add(phone.friendId);
      counts.set(phone.friendId, (counts.get(phone.friendId) || 0) + 1);
    }
    const fetchedByFriend = new Map(fetches.map(row => [row.friendId, row.items]));
    const sorted = [...devices].sort((a, b) => Number(b.behind) - Number(a.behind));
    const openFriends = new Set([...content.querySelectorAll('details[open]')].map(item => item.dataset.phone));
    const hashFriend = /^#friend=([1-9][0-9]*)$/.exec(location.hash)?.[1];
    let highlight;
    for (const phone of sorted) {
      const name = phone.friend + (friendsByName.get(phone.friend).size > 1 ? '(' + phone.friendId + ')' : '');
      const row = node('details', '', 'card admin-device');
      row.dataset.phone = phone.friendId + ':' + phone.phone;
      row.open = openFriends.has(row.dataset.phone);
      const summary = node('summary');
      const version = caption(phone.appVersion);
      if (phone.behind) version.append(node('span', ' · 뒤처짐', 'danger'));
      const notifications = phone.notifications === 'denied' ? ' · 알림 꺼짐' : '';
      summary.append(node('span', name + ' · 폰 ' + phone.phone), version,
        caption('마지막 보고 ' + shortDate(phone.seenAt) + notifications));
      row.append(summary);
      const log = node('ul', '', 'stack records');
      const events = newest([...phone.events, ...(fetchedByFriend.get(phone.friendId) || []).map(event =>
        ({...event, kind: 'fetched'}))]);
      const lastState = events.find(event => event.kind === 'state');
      for (const event of events) {
        const line = node('li', '', 'caption');
        line.append(node(event === lastState && event.state === 'needs_confirm' ? 'strong' : 'span',
          updateEvent(event, versions)));
        log.append(line);
      }
      row.append(log);
      phones.append(row);
      if (String(phone.friendId) === hashFriend && !highlight) highlight = row;
      const count = (shown.get(phone.friendId) || 0) + 1;
      shown.set(phone.friendId, count);
      if (count === 20 && counts.get(phone.friendId) === 20) {
        phones.append(caption('이 사람은 최근 보고한 20대만 보여요'));
      }
    }
    for (const release of newest(releases)) {
      const row = node('div', '', 'card stack');
      const label = release.kind === 'published' ? release.versionName + '(' + release.versionCode + ') 올림'
        : release.kind === 'paused' ? '멈춤' : release.kind === 'resumed' ? '다시 켬' : release.kind;
      row.append(node('p', label + ' · ' + shortDate(release.at)));
      if (release.kind === 'published') {
        if (release.backfilled) row.append(caption('기록에서 채움'));
        if (release.notes) row.append(node('p', release.notes, 'caption admin-note'));
        if (release.size != null) row.append(caption(release.size.toLocaleString() + '바이트'));
        if (release.sha256) row.append(caption('SHA-256 ' + release.sha256));
      }
      history.append(row);
    }
    appLayout(current, phones, history);
    if (initial && highlight) {
      highlight.open = true;
      highlight.scrollIntoView();
    }
  }

  const callStates = {ok: '정상', warn: '80% 넘음', exhausted: '다 씀', hard_stop: '120% 넘음'};
  const pictureKinds = {diary: '일기', topic: '화두', reaction: '반응', character: '캐릭터'};

  async function costsPage(initial) {
    const call = group('통화', ...loadingRows(1));
    const people = group('사람마다 통화', ...loadingRows(1));
    const images = group('그림', ...loadingRows(1));
    const layout = grid('costs', call, people, images);
    if (initial) content.replaceChildren(layout);
    const overviewReply = await request(base + '/overview');
    const membersReply = await request(base + '/members');
    const imageReply = await request(base + '/image-costs');
    const denied = [overviewReply, membersReply, imageReply].find(reply => reply.status === 403);
    if (denied && forbidden(denied)) return;
    content.replaceChildren(layout);

    if (overviewReply.status !== 200) failure(call, overviewReply);
    else if (!overviewReply.body.callMonth) call.replaceChildren(node('h2', '통화'), caption(unavailable));
    else {
      const month = overviewReply.body.callMonth;
      call.replaceChildren(node('h2', '통화 · ' + monthName(month.month) + '(UTC)'),
        node('p', money(month.spentUsd) + ' / ' + money(month.budgetUsd) + ' · ' + month.percent + '%', severity(month)),
        progress(month), caption(callStates[month.state]));
      if (month.percent >= 100) call.append(node('p', '새 통화가 막혀요', 'caption danger'));
    }
    if (membersReply.status !== 200) failure(people, membersReply);
    else {
      const sorted = [...membersReply.body.members].sort((a, b) =>
        (b.callMonthUsd === null ? -1 : Number(b.callMonthUsd)) - (a.callMonthUsd === null ? -1 : Number(a.callMonthUsd)));
      people.replaceChildren(node('h2', '사람마다 통화'), ...sorted.map(member =>
        link(member.name + ' · ' + money(member.callMonthUsd), memberPath(member.friendId), 'card admin-record')));
    }
    if (imageReply.status !== 200) failure(images, imageReply);
    else {
      const {month, byKind, budgets} = imageReply.body;
      images.replaceChildren(node('h2', '그림 · ' + monthName(month)));
      for (const [kind, label] of Object.entries(pictureKinds)) {
        const budget = budgets[kind];
        const amount = budget ? money(budget.usedUsd.toFixed(2)) + ' / ' + money(budget.limitUsd.toFixed(2)) +
          ' · ' + Math.floor(budget.ratio * 100) + '%' : money(byKind[kind].toFixed(2));
        images.append(caption(label + ' ' + amount));
      }
    }
  }

  async function overviewPage(initial) {
    if (initial) overview();
    const reply = await request(base + '/overview');
    if (reply.status === 200) overview(reply.body);
    else failure(content, reply);
  }

  const loaders = {overview: overviewPage, members: friendId ? memberPage : membersPage,
    invites: invitePage, app: appPage, costs: costsPage};

  async function load(stale = false) {
    if (loading || writing) return;
    loading = true;
    screen.setAttribute('aria-busy', 'true');
    refreshBar.hidden = !stale;
    try {
      await loaders[page](!stale);
    } finally {
      loading = false;
      refreshBar.hidden = true;
      screen.setAttribute('aria-busy', 'false');
    }
  }

  if (tabs) {
    const markOverflow = () => { nav.dataset.overflow = String(tabs.scrollLeft + tabs.clientWidth < tabs.scrollWidth - 1); };
    new ResizeObserver(markOverflow).observe(tabs);
    tabs.addEventListener('scroll', markOverflow, {passive: true});
  }
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') hiddenAt = Date.now();
    else {
      const stale = hiddenAt !== null && Date.now() - hiddenAt > 60_000;
      hiddenAt = null;
      if (stale) load(true);
    }
  });
  load();
})();
