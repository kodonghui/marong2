'use strict';

(() => {
  const {node, button, request, signal, shortDate} = Unified;
  const base = '/chat/admin/api';
  const screen = document.getElementById('admin');
  const controls = document.getElementById('invite-controls');
  const invites = document.getElementById('invites');
  const members = document.getElementById('members');
  const error = document.getElementById('admin-error');
  const notice = document.getElementById('admin-notice');
  const defaultLimits = document.getElementById('default-limits');
  const kinds = {join: '새 사람', link: '기존 계정 연결', relogin: '다시 로그인'};
  const states = {open: '열림', expired: '기간 지남', revoked: '거둠', used: '씀'};
  const limitModes = {unlimited: '무제한', default: '기본 한도', custom: '직접 정하기'};
  const invalidNumbers = '숫자를 확인해 주세요(하루 1~100000, 통화 월 0.01~1000)';
  const dayMs = 86_400_000;
  let data, loading = false;
  const rowEditors = new Map();

  function fail(target, reply, retry, slot) {
    const message = reply.body?.code === 'cross_site' ? '이 화면에서 다시 해 주세요' :
      '잠깐 문제가 생겼어요. 다시 해 볼까요?';
    signal(target, message, reply);
    if (retry && !slot.querySelector('[data-retry]')) {
      const again = button('다시 해 볼게', () => { again.remove(); retry(); }, 'btnt');
      again.dataset.retry = '';
      slot.append(again);
    }
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
      node('p', '만료 ' + shortDate(body.expiresAt) + '(' + daysUntil(body.expiresAt) + '일 뒤)', 'caption'), copy,
      button('닫기', resetControls, 'btnt'));
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

  function inviteForm() {
    const card = node('form', '', 'card');
    const kind = node('select');
    for (const [value, label] of Object.entries(kinds)) {
      const option = node('option', label);
      option.value = value;
      kind.append(option);
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
      person.hidden = kind.value === 'join';
      people.replaceChildren();
      const empty = node('option', '사람 고르기');
      empty.value = '';
      people.append(empty);
      const source = kind.value === 'link' ? [...data.unlinked, ...data.members] : data.members;
      for (const item of source) {
        const option = node('option', item.name);
        option.value = item.friendId;
        people.append(option);
      }
    }
    kind.addEventListener('change', fill);
    fill();
    const close = button('닫기', resetControls, 'btnt');
    card.append(labeled('종류', kind), person, labeled('메모', note), feedback, submit, close);
    card.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (submit.disabled) return;
      signal(feedback);
      const payload = {kind: kind.value, note: note.value};
      if (kind.value !== 'join') {
        if (!people.value) { signal(feedback, '입력을 확인해 주세요'); return; }
        payload.friendId = Number(people.value);
      }
      for (const control of [submit, kind, people, note, close]) control.disabled = true;
      const reply = await request(base + '/invites', payload);
      for (const control of [submit, kind, people, note, close]) control.disabled = false;
      if (reply.status === 201) {
        showCreated(reply.body);
        await refresh();
      } else if (reply.status === 400) signal(feedback, '입력을 확인해 주세요');
      else if (reply.status === 404) {
        signal(feedback, '그 사람을 찾을 수 없어요. 목록을 다시 불러올게요');
        await refresh();
        fill();
      } else fail(feedback, reply, () => card.requestSubmit(), card);
    });
    controls.replaceChildren(card);
  }

  function resetControls() {
    controls.replaceChildren(button('새 링크 만들기', inviteForm));
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
      rowEditors.delete(member.friendId);
    }, 'btnt');
    setting.append(feedback, confirm, cancel);
    setting.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (confirm.disabled) return;
      signal(feedback);
      const add = Number(value.value);
      if (!revoke && (!Number.isInteger(add) || add < 1 || add > 1000)) {
        signal(feedback, '1부터 1000까지 넣어 주세요');
        return;
      }
      confirm.disabled = value.disabled = cancel.disabled = true;
      const reply = await request(base + '/members/' + member.friendId + '/' + mode,
        revoke ? undefined : {add}, 'POST');
      confirm.disabled = value.disabled = cancel.disabled = false;
      if (reply.status === (revoke ? 204 : 200)) {
        rowEditors.delete(member.friendId);
        if (revoke) member.sessions = 0;
        else member.tickets = reply.body.tickets;
        showMembers();
        signal(notice, revoke ? '로그인을 끊었어요' : '티켓을 넣었어요');
      } else if (!revoke && reply.status === 400) signal(feedback, '1부터 1000까지 넣어 주세요');
      else fail(feedback, reply, () => setting.requestSubmit(), setting);
    });
    editor.replaceChildren(setting);
    rowEditors.set(member.friendId, editor);
  }

  function showMembers() {
    members.replaceChildren(...data.members.map((m) => {
      const entry = node('li', '', 'card');
      const actions = node('div', '', 'row');
      const editor = rowEditors.get(m.friendId) || node('div');
      actions.append(button('한도 바꾸기', () => editLimits(m, editor), 'btnt'),
        button('로그인 끊기', () => editMember(m, editor, 'revoke'), 'btnt danger'),
        button('티켓 넣기', () => editMember(m, editor, 'tickets'), 'btnt'));
      const usage = m.usageToday;
      entry.append(node('p', m.name + ' · ' + m.botName),
        node('p', '로그인 ' + m.sessions + ' · 마지막 사용 ' + shortDate(m.lastSeenAt), 'caption'),
        node('p', '오늘 ' + usage.units + ' · 대화 ' + usage.chatTurns + ' · 통화 ' + usage.callSeconds
          + '초 · 그림 ' + usage.images + ' · 티켓 ' + m.tickets, 'caption'),
        node('p', memberLimits(m), 'caption'),
        node('p', '이번 달 통화 ' + (m.callMonthUsd == null ? '—' : '$' + m.callMonthUsd), 'caption'),
        actions, editor);
      return entry;
    }));
    if (!data.members.length) members.append(node('li', '아직 가입한 사람이 없어요', 'caption'));
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
      rowEditors.delete(member.friendId);
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
    form.append(modes, fields, feedback, save, cancel);
    sync();
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (save.disabled) return;
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
      const reply = await request(base + '/members/' + member.friendId + '/limits', payload, 'PUT');
      saving = false;
      sync();
      if (reply.status === 200) {
        rowEditors.delete(member.friendId);
        const row = data.members.find(item => item.friendId === member.friendId);
        if (row) Object.assign(row, reply.body);
        showMembers();
        signal(notice, '한도를 바꿨어요');
      } else if (reply.status === 400) {
        signal(feedback, invalidNumbers);
      } else if (reply.status === 404) {
        rowEditors.delete(member.friendId);
        editor.replaceChildren();
        signal(notice, '그 사람을 찾을 수 없어요. 목록을 다시 불러올게요');
        await refresh();
      } else {
        fail(feedback, reply, () => form.requestSubmit(), form);
      }
    });
    editor.replaceChildren(form);
    rowEditors.set(member.friendId, editor);
  }

  async function refresh() {
    if (loading) return;
    loading = true;
    const [inviteReply, memberReply] = await Promise.all([request(base + '/invites'), request(base + '/members')]);
    screen.setAttribute('aria-busy', 'false');
    loading = false;
    if (inviteReply.status !== 200 || memberReply.status !== 200) {
      fail(error, inviteReply.status !== 200 ? inviteReply : memberReply, refresh, screen);
      return;
    }
    signal(error);
    const first = !data;
    data = memberReply.body;
    signal(defaultLimits, '기본 한도 · ' + amounts(data.defaults, '없음'));
    if (first) resetControls();
    invites.replaceChildren(...inviteReply.body.invites.map((inv) => {
      const item = node('li', '', ['expired', 'revoked'].includes(inv.state) ? 'card caption' : 'card');
      const used = inv.usedBy ? '(' + inv.usedBy.name + ')' : '';
      item.append(node('p', kinds[inv.kind] + (inv.note ? ' · ' + inv.note : '')),
        node('p', states[inv.state] + used, 'caption'),
        node('p', inviteDates(inv), 'caption'));
      return item;
    }));
    if (!inviteReply.body.invites.length) invites.append(node('li', '만든 초대 링크가 없어요', 'caption'));
    showMembers();
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') refresh();
  });
  refresh();
})();
