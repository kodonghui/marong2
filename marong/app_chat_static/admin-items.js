'use strict';

(() => {
  const {node, button, request, signal} = Unified;
  const api = '/chat/admin/api/items';
  const screen = document.getElementById('item-admin');
  const list = document.getElementById('item-list');
  const error = document.getElementById('item-error');
  const state = {listed: '올림', unlisted: '내림', new: '새 아이템'};
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
    const action = button(listing ? '올리기' : '내리기', async () => {
      action.disabled = true;
      const result = await request(api + '/' + item.id + (listing ? '/list' : '/unlist'), undefined, 'POST');
      action.disabled = false;
      if (result.status === 200) card.replaceWith(render(result.body, itemSet));
      else signal(feedback, result.body?.missing?.join(', ') || '지금은 바꾸지 못했어요', result);
    }, 'btn2');
    action.disabled = listing ? item.missing.length > 0 : item.starter;
    const controls = node('td');
    controls.append(feedback, action);
    card.append(controls);
    return card;
  }

  async function load() {
    const result = await request(api);
    screen.setAttribute('aria-busy', 'false');
    if (result.status === 404) {
      signal(error);
      list.replaceChildren(node('p', '꾸미기가 꺼져 있어요', 'caption'));
      return;
    }
    if (result.status !== 200) {
      signal(error, '아이템을 불러오지 못했어요', result);
      list.replaceChildren(button('다시 보기', load, 'btn2'));
      return;
    }
    signal(error);
    if (!result.body.items.length) {
      list.replaceChildren(node('p', '아이템 목록 폴더가 비어 있어요(marong/decor/v1/items.json)', 'caption'));
      return;
    }
    const table = node('table');
    const header = node('tr');
    for (const label of ['썸네일', 'id', '종류', '이름', '상태', '받은 사람 수', '버튼']) header.append(node('th', label));
    const head = node('thead');
    head.append(header);
    const body = node('tbody');
    body.append(...result.body.items.map(item => render(item, result.body.set)));
    table.append(head, body);
    list.replaceChildren(table);
  }
  load();
})();
