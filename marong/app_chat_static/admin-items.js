'use strict';

(() => {
  const {node, button, request, signal} = Unified;
  const api = '/chat/admin/api/items';
  const screen = document.getElementById('item-admin');
  const list = document.getElementById('item-list');
  const error = document.getElementById('item-error');
  const state = {listed: '올림', unlisted: '내림', new: '새 아이템'};
  let selected = 'all';
  let items = [];
  let itemSet = '';
  Unified.fitAdminTabs(document.querySelector('.admin-tabs'));

  function render(item, itemSet) {
    const card = node('tr');
    const thumbnail = node('img');
    thumbnail.src = '/chat/decor/' + encodeURIComponent(itemSet) + '/' + encodeURIComponent(item.id) + '/' + (item.kind === 'sticker' ? 'sticker.webp' : 'thumb.webp');
    thumbnail.alt = '';
    thumbnail.width = 48;
    thumbnail.height = 48;
    const imageCell = node('td');
    imageCell.append(thumbnail);
    card.append(imageCell, node('td', item.id), node('td', item.kind), node('td', item.name || item.id),
      node('td', state[item.state]), node('td', String(item.owners)));
    const feedback = node('p', '', 'err');
    if (item.missing.length) signal(feedback, '확인할 항목 ' + item.missing.join(', '));
    else feedback.hidden = true;
    const listing = item.state !== 'listed';
    const controls = node('td');
    controls.append(feedback);
    function forbidden(result) {
      if (result.status !== 403 || result.body?.code === 'cross_site') return false;
      const main = document.querySelector('main');
      const message = node('p', '관리자만 볼 수 있어요');
      message.setAttribute('role', 'status');
      main.replaceChildren(message);
      return true;
    }
    async function change(action, actionButton) {
      actionButton.disabled = true;
      const result = await request(api + '/' + encodeURIComponent(item.id) + '/' + action, undefined, 'POST');
      actionButton.disabled = false;
      if (result.status === 200) {
        items = items.map(current => current.id === item.id ? result.body : current);
        showItems();
      } else if (!forbidden(result)) {
        if (result.status === 409 && result.body?.missing?.length) {
          item.missing = result.body.missing;
          card.replaceWith(render(item, itemSet));
        } else signal(feedback, result.body?.missing?.join(', ') || '지금은 바꾸지 못했어요', result);
      }
    }
    if (listing && !item.missing.length) {
      const action = button('올리기', () => change('list', action), 'btn2');
      controls.append(action);
    } else if (!listing && !item.starter) {
      const action = button('내리기', () => {
        const prompt = node('p', '상점에서 내릴까요? 받은 사람은 계속 써요');
        const confirm = button('확인', () => change('unlist', confirm), 'btn2');
        const cancel = button('취소', () => controls.replaceChildren(feedback, action), 'btn2');
        controls.replaceChildren(feedback, prompt, confirm, cancel);
        cancel.focus();
      }, 'btn2');
      controls.append(action);
    }
    card.append(controls);
    return card;
  }

  async function load() {
    const result = await request(api);
    screen.setAttribute('aria-busy', 'false');
    if (result.status === 403 && result.body?.code !== 'cross_site') {
      const message = node('p', '관리자만 볼 수 있어요');
      message.setAttribute('role', 'status');
      document.querySelector('main').replaceChildren(message);
      return;
    }
    if (result.status === 404) {
      signal(error);
      list.replaceChildren(node('p', '꾸미기가 꺼져 있어요', 'caption'));
      return;
    }
    if (result.status !== 200) {
      signal(error, '잠깐 문제가 생겼어요. 다시 해 볼까요?', result);
      list.replaceChildren(button('다시 해 볼게요', load, 'btn2'));
      return;
    }
    signal(error);
    items = result.body.items;
    itemSet = result.body.set;
    showItems();
  }

  function showItems() {
    if (!items.length) {
      list.replaceChildren(node('p', '아이템 목록 폴더가 비어 있어요(marong/decor/v1/items.json)', 'caption'));
      return;
    }
    const filters = node('div');
    filters.setAttribute('aria-label', '상태 거르개');
    for (const [key, label] of [['all', '전체'], ['new', '새것'], ['listed', '올림'], ['unlisted', '내림']]) {
      const filter = button(label, () => { selected = key; showItems(); }, 'btn2');
      filter.setAttribute('aria-pressed', String(selected === key));
      filters.append(filter);
    }
    const table = node('table');
    const header = node('tr');
    for (const label of ['썸네일', 'id', '종류', '이름', '상태', '받은 사람 수', '버튼']) header.append(node('th', label));
    const head = node('thead');
    head.append(header);
    const body = node('tbody');
    body.append(...items.filter(item => selected === 'all' || item.state === selected).map(item => render(item, itemSet)));
    table.append(head, body);
    list.replaceChildren(filters, table);
  }

  load();
})();
