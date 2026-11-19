'use strict';

(() => {
  const {node, button, request, signal} = Unified;
  const screen = document.getElementById('friends');
  const identity = document.getElementById('friend-identity');
  const groups = document.getElementById('friend-groups');
  const notice = document.getElementById('friend-notice');
  const error = document.getElementById('friend-error');
  const path = '/chat/api/friends';
  const valid = /^[A-HJ-NP-Za-hj-np-z2-9]{6}$/;
  const errors = {
    invalid_input: '친구 코드는 글자와 숫자 6자야. 다시 확인해 줄래?',
    self_request: '이건 내 코드야. 친구의 코드를 넣어 줘',
    code_not_found: '이 코드를 가진 친구를 찾지 못했어. 코드를 다시 확인해 줄래?',
    already_friends: '이미 친구야!',
    request_exists: '이미 요청이 오가는 중이야. 받은 요청이나 보낸 요청을 봐 줘',
    request_limit: '오늘은 요청을 많이 보냈어(하루 10번). 내일 다시 해 줘',
    cross_site: '이 화면에서 다시 해 줘',
  };
  let profile, data, loading = false, currentEdit = null, codeWaitUntil = 0;

  function sayName(name, batchim, open) {
    const char = name.charCodeAt(name.length - 1);
    return name + (char >= 0xac00 && char <= 0xd7a3 && (char - 0xac00) % 28 ? batchim : open);
  }

  function problem(result, target = error) {
    if (result.status === 401) {
      try { sessionStorage.setItem('marong.session.return', location.pathname); } catch {}
      location.replace('/chat/login?expired=1');
      return;
    }
    signal(target, errors[result.body?.code] || '잠깐 문제가 생겼어. 다시 해 볼래?', result);
  }

  function switchControl(text, checked, change) {
    const label = node('label', '', 'row');
    const input = node('input');
    input.type = 'checkbox';
    input.role = 'switch';
    input.checked = checked;
    input.addEventListener('change', async () => {
      input.disabled = true;
      await change(input.checked, input);
      input.disabled = false;
    });
    label.append(input, node('span', text));
    return label;
  }

  function drawIdentity(value = '') {
    const own = node('div', '', 'card');
    const code = node('p', profile.friendCode, 'code');
    const copy = button('복사', async () => {
      try { await navigator.clipboard.writeText(profile.friendCode); copy.textContent = '복사했어'; }
      catch {
        const selection = getSelection(), range = document.createRange();
        range.selectNodeContents(code);
        selection.removeAllRanges();
        selection.addRange(range);
      }
    }, 'btn2');
    own.append(node('h2', '내 친구 코드'), code, copy);
    const form = node('form', '', 'card');
    const label = node('label', '친구 코드로 요청 보내기', 'field-label');
    const input = node('input');
    input.value = value;
    input.maxLength = 6;
    input.autocapitalize = 'characters';
    input.autocomplete = 'off';
    label.append(input);
    const warning = node('p', '', 'err');
    warning.hidden = true;
    const send = node('button', '보내기', 'btn');
    send.type = 'submit';
    send.disabled = codeWaitUntil > Date.now();
    form.append(label, warning, send);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (send.disabled) return;
      signal(warning);
      if (!valid.test(input.value)) { signal(warning, errors.invalid_input); return; }
      send.disabled = input.disabled = true;
      const result = await request(path + '/requests', {friendCode: input.value});
      send.disabled = input.disabled = false;
      if (result.status === 201) {
        input.value = '';
        await load();
      } else {
        problem(result, warning);
        if (result.status === 429) {
          codeWaitUntil = Date.now() + Math.max(1, result.retryAfter) * 1000;
          send.disabled = true;
          setTimeout(() => { send.disabled = false; }, codeWaitUntil - Date.now());
        }
      }
    });
    identity.replaceChildren(own, form);
  }

  function peer(row) {
    const item = node('li', '', 'card');
    item.append(node('p', row.name));
    item.append(switchControl('가까운 사이', row.closeMine, async (checked, input) => {
      const reply = await request(path + '/' + row.friendId, {close: checked}, 'PATCH');
      if (reply.status === 200) {
        row.closeMine = reply.body.closeMine;
        row.close = reply.body.close;
        drawLists();
      } else {
        input.checked = row.closeMine;
        problem(reply);
      }
    }));
    if (row.close) item.append(node('p', '가까운 사이 · 요즘 지내는 얘기까지 나눠', 'caption'));
    else if (row.closeMine) item.append(node('p', '나는 켰어. ' + row.name + '도 켜면 가까운 사이가 돼', 'caption'));
    const disconnect = button('친구 끊기', () => {
      currentEdit = row.friendId;
      const confirmation = node('div', '', 'stack');
      const confirm = button('끊기', async () => {
        confirm.disabled = true;
        const result = await request(path + '/' + row.friendId, undefined, 'DELETE');
        confirm.disabled = false;
        if (result.status === 204) {
          currentEdit = null;
          await load();
          signal(notice, '친구를 끊었어');
        } else problem(result);
      }, 'btn2 danger');
      confirmation.append(node('p', sayName(row.name, '이랑', '랑') + ' 친구를 끊을까? ' +
        sayName(profile.botName, '이가', '가') + ' 더는 서로의 얘기를 하지 않아'),
        confirm, button('그만두기', () => { currentEdit = null; confirmation.replaceWith(disconnect); }, 'btnt'));
      disconnect.replaceWith(confirmation);
    }, 'btnt danger');
    item.append(disconnect);
    return item;
  }

  function incoming(row) {
    const item = node('li', '', 'card');
    item.append(node('p', sayName(row.name, '이가', '가') + ' 친구 요청을 보냈어'));
    const buttons = node('div', '', 'row');
    for (const [action, label] of [['accept', '수락'], ['decline', '거절']]) {
      buttons.append(button(label, async () => {
        for (const control of buttons.children) control.disabled = true;
        const reply = await request(path + '/requests/' + row.friendId, {action});
        for (const control of buttons.children) control.disabled = false;
        if (reply.status === 200 || reply.status === 404) {
          await load();
          const text = action === 'accept' ? sayName(row.name, '이랑', '랑') + ' 친구가 됐어! 이제 ' +
            sayName(profile.botName, '이가', '가') + ' 둘 다 아는 친구로 얘기해' : '거절했어';
          signal(notice, reply.status === 404 ? '이 요청은 이제 없어' : text);
        } else problem(reply);
      }, action === 'accept' ? 'btn2' : 'btnt'));
    }
    item.append(buttons);
    return item;
  }

  function drawLists() {
    groups.replaceChildren();
    const definitions = [
      ['받은 요청', data.incoming, incoming],
      ['친구', data.friends, peer],
      ['보낸 요청', data.outgoing, row => node('li', row.name + '한테 요청을 보냈어. 수락을 기다리는 중이야', 'card')],
    ];
    for (const [title, entries, render] of definitions) {
      if (!entries.length) continue;
      const list = node('ul', '', 'stack records');
      list.append(...entries.map(render));
      groups.append(node('h2', title), list);
    }
    if (!groups.children.length) groups.append(node('p',
      '아직 친구가 없어. 친구 코드를 서로 알려 주면 ' + sayName(profile.botName, '이가', '가') + ' 둘 다 아는 친구가 돼'));
    const share = node('div', '', 'card');
    share.append(switchControl('내 얘기 나누기', profile.share, async (checked, input) => {
      const reply = await request('/chat/api/profile', {share: checked}, 'PATCH');
      if (reply.status === 200) { profile = reply.body; drawLists(); }
      else { input.checked = profile.share; problem(reply); }
    }), node('p', sayName(profile.botName, '이가', '가') + ' 친구들한테 내 가벼운 근황을 얘기해도 돼', 'caption'));
    groups.append(share);
    if (!profile.share) groups.prepend(node('p', '지금은 내 얘기를 친구들한테 하지 않아', 'caption'));
  }

  async function load() {
    if (loading) return;
    loading = true;
    const [me, list] = await Promise.all([request('/chat/api/profile'), request(path)]);
    loading = false;
    screen.setAttribute('aria-busy', 'false');
    if (me.status !== 200 || list.status !== 200) {
      problem(me.status === 200 ? list : me);
      if (!profile) groups.replaceChildren(button('다시 해 볼게', load, 'btnt'));
      return;
    }
    const draft = identity.querySelector('input')?.value || '';
    profile = me.body;
    data = list.body;
    signal(error);
    drawIdentity(draft);
    if (currentEdit === null) drawLists();
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') load();
  });
  load();
})();
