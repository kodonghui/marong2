'use strict';

(() => {
  const {node, button, request, signal, date} = Unified;
  const base = '/chat/admin/api';
  const screen = document.getElementById('admin');
  const controls = document.getElementById('invite-controls');
  const invites = document.getElementById('invites');
  const members = document.getElementById('members');
  const error = document.getElementById('admin-error');
  const notice = document.getElementById('admin-notice');
  const kinds = {join: '새 사람', link: '기존 계정 연결', relogin: '다시 로그인'};
  const states = {open: '열림', expired: '기간 지남', revoked: '거둠', used: '씀'};
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
      node('p', date(body.expiresAt), 'caption'), copy,
      button('닫기', resetControls, 'btnt'));
    controls.replaceChildren(panel);
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
      actions.append(button('로그인 끊기', () => editMember(m, editor, 'revoke'), 'btnt danger'),
        button('티켓 넣기', () => editMember(m, editor, 'tickets'), 'btnt'));
      const usage = m.usageToday;
      entry.append(node('p', m.name + ' · ' + m.botName),
        node('p', '로그인 ' + m.sessions + ' · 마지막 사용 ' + date(m.lastSeenAt), 'caption'),
        node('p', '오늘 ' + usage.units + ' · 대화 ' + usage.chatTurns + ' · 통화 ' + usage.callSeconds
          + '초 · 그림 ' + usage.images + ' · 티켓 ' + m.tickets, 'caption'),
        actions, editor);
      return entry;
    }));
    if (!data.members.length) members.append(node('li', '아직 가입한 사람이 없어요', 'caption'));
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
    if (first) resetControls();
    invites.replaceChildren(...inviteReply.body.invites.map((inv) => {
      const item = node('li', '', 'card');
      const used = inv.usedBy ? ' (' + inv.usedBy.name + ')' : '';
      item.append(node('p', kinds[inv.kind] + (inv.note ? ' · ' + inv.note : '')),
        node('p', states[inv.state] + used + ' · ' + date(inv.expiresAt), 'caption'));
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
