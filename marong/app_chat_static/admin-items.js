'use strict';

(() => {
  const {node, button, request, signal} = Unified;
  const api = '/chat/admin/api/items';
  const screen = document.getElementById('item-admin');
  const list = document.getElementById('item-list');
  const error = document.getElementById('item-error');
  const state = {listed: '올림', unlisted: '내림', new: '새 아이템'};
  const tabs = document.querySelector('.admin-tabs');
  if (tabs) {
    const markOverflow = () => {
      tabs.parentElement.dataset.overflow = String(tabs.scrollLeft + tabs.clientWidth < tabs.scrollWidth - 1);
    };
    new ResizeObserver(markOverflow).observe(tabs);
    tabs.addEventListener('scroll', markOverflow, {passive: true});
  }

  function render(item) {
    const card = node('li', '', 'card');
    card.append(node('h2', item.name || item.id), node('p', state[item.state] + ' · 받은 친구 ' + item.owners + '명', 'caption'));
    const feedback = node('p', '', 'err');
    if (item.missing.length) signal(feedback, '확인할 항목 ' + item.missing.join(', '));
    else feedback.hidden = true;
    const listing = item.state !== 'listed';
    const action = button(listing ? '올리기' : '내리기', async () => {
      action.disabled = true;
      const result = await request(api + '/' + item.id + (listing ? '/list' : '/unlist'), undefined, 'POST');
      action.disabled = false;
      if (result.status === 200) card.replaceWith(render(result.body));
      else signal(feedback, result.body?.missing?.join(', ') || '지금은 바꾸지 못했어요', result);
    }, 'btn2');
    action.disabled = listing ? item.missing.length > 0 : item.starter;
    card.append(feedback, action);
    return card;
  }

  async function load() {
    const result = await request(api);
    screen.setAttribute('aria-busy', 'false');
    if (result.status === 404) {
      signal(error);
      list.replaceChildren(node('li', '꾸미기가 꺼져 있어요', 'caption'));
      return;
    }
    if (result.status !== 200) {
      signal(error, '아이템을 불러오지 못했어요', result);
      list.replaceChildren(button('다시 보기', load, 'btn2'));
      return;
    }
    signal(error);
    list.replaceChildren(...result.body.items.map(render));
    if (!result.body.items.length) list.append(node('li', '등록할 아이템이 없어요', 'caption'));
  }
  load();
})();
