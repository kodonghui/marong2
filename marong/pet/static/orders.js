import {action, api, button, currency, dateLabel, el, errorText, Failure, header, link, notice, page, show, showTabs, text} from './pet.js';
import {business} from './shop.js';

const ORDERS = '/me/orders';
const PRODUCT = {
  character_creation: '캐릭터 만들기', recharge_half: '반 채우기', recharge_full: '가득 채우기',
  subscription_month: '월 구독', item: '아이템',
};
const STATUS = {
  fulfilled: '지급됨', refunded: '환불됨', created: '처리 중', paid: '처리 중',
  refund_pending: '처리 중', failed: '결제 안 됨',
};
const wait = duration => new Promise(resolve => setTimeout(resolve, duration));

function orderName(order) {
  return order.itemName ?? PRODUCT[order.product];
}

function showOrder(order) {
  const result = el('div', {'aria-live': 'polite'});
  const card = el('article', {class: 'card stack'},
    el('div', {class: 'row'}, el('strong', {class: 'grow'}, orderName(order)),
      el('span', {}, `${currency.format(order.amountKrw)}원`)),
    text(`${dateLabel(order.createdAt)} · ${STATUS[order.status]}`),
    el('small', {}, order.orderNo));
  if (order.withdrawable) {
    const open = button('청약철회', () => modal.showModal(), 'plain');
    const confirm = button('청약철회', () => action(confirm, outcome, async () => {
      try {
        const updated = await api(`/api/orders/${order.id}/withdraw`, {method: 'POST'});
        const next = showOrder(updated);
        if (updated.status === 'refunded') next.append(text('결제를 취소했어요'));
        modal.close();
        card.replaceWith(next);
      } catch (error) {
        if (error.code !== 'withdrawal_not_allowed') throw error;
        modal.close();
        open.remove();
        errorText(error, result);
      }
    }), 'danger');
    const outcome = el('div', {'aria-live': 'polite'});
    const modal = el('dialog', {class: 'sheet stack'}, el('h2', {}, '청약철회'),
      text('철회하면 결제를 취소하고 보관함에서 빠져요'), outcome, confirm, button('닫기', () => modal.close()));
    card.append(open, modal);
  } else if (order.status === 'refund_pending') {
    card.append(text('처리 중이에요. 결제 대행의 취소를 기다리고 있어요.'));
  } else if (order.withdrawalNote) card.append(text(order.withdrawalNote, 'muted'));
  card.append(result);
  return card;
}

export async function orders() {
  header('주문 내역', {label: '내 정보', url: '/me'});
  showTabs(null);
  show(...Array.from({length: 4}, () => el('div', {class: 'skeleton', 'aria-hidden': 'true'})));
  page.setAttribute('aria-busy', 'true');
  const {items} = await api('/api/orders');
  show(...(items.length ? items.map(showOrder) : [notice('주문이 없어요.')]));
}

const price = amount => `${currency.format(amount)}원`;
const RECHARGE = {recharge_half: ['절반 채우기', 1500], recharge_full: ['가득 채우기', 2900]};

function purchaseControl(product, label, amount, member, render, blocked) {
  const buy = button(label, () => modal.showModal(), 'primary');
  buy.disabled = !member.paymentsEnabled;
  if (buy.disabled) return buy;
  const outcome = el('div', {'aria-live': 'polite'});
  const subscription = product === 'subscription_month';
  const key = crypto.randomUUID();
  const confirm = button('결제하기', () => action(confirm, outcome, async () => {
    try {
      const {pg, order} = await api('/api/orders', {method: 'POST', body: {product, idempotencyKey: key}});
      if (pg || order.status !== 'fulfilled') throw new Failure(503);
      modal.close();
      await render();
    } catch (error) {
      if (error.code === 'already_subscribed') {
        modal.close();
        await render();
      } else if (error.code === 'identity_required') {
        outcome.replaceChildren(notice('첫 결제 전에 본인인증을 한 번 해 주세요.', link('내 정보', '/me')));
      } else if (blocked && ['quota_full', 'recharge_limit', 'payments_off'].includes(error.code)) {
        modal.close();
        blocked(error);
      } else {
        throw error;
      }
    }
  }), 'primary');
  const modal = el('dialog', {class: 'sheet stack'}, el('h2', {}, label),
    text(subscription ? `하루 한도 2배 · 월 ${price(amount)}` : price(amount)),
    subscription ? text('한 달마다 갱신돼요. 한도와 구독 화면에서 해지할 수 있어요.') : null,
    text(subscription ? '결제 7일 안이고 늘어난 한도를 쓰지 않았으면 철회할 수 있어요'
      : '충전권은 사면 바로 채워져 철회할 수 없어요'),
    business(member), outcome, confirm, button('닫기', () => modal.close()));
  return el('div', {class: 'stack'}, buy, modal);
}

export async function rechargeSheet(pet, automatic = false) {
  if (pet.mode !== 'living' || pet.status !== 'active') return;
  const outlet = el('div', {class: 'stack', 'aria-busy': 'true'},
    el('div', {class: 'stack recharge-loading', 'aria-hidden': 'true'},
      el('div', {class: 'skeleton recharge-loading-gauge'}),
      el('div', {class: 'recharge-loading-options'},
        Array.from({length: 3}, () => el('div', {class: 'skeleton'})))));
  const close = button('괜찮아요', () => dialog.close(), 'plain');
  const dialog = el('dialog', {class: 'sheet stack', 'aria-label': '충전권'}, outlet, close);
  dialog.addEventListener('close', () => dialog.remove(), {once: true});
  document.querySelector('#page').append(dialog);
  dialog.showModal();
  try {
    const [member, quota, plan] = await Promise.all([
      api('/api/me'), api('/api/me/quota'), api('/api/subscription'),
    ]);
    if (!dialog.open) return;
    const status = el('div', {'aria-live': 'polite'});
    const controls = el('div', {class: 'row'});
    const charge = Object.entries(RECHARGE).map(([product, [label, amount]]) =>
      purchaseControl(product, `${label} · ${price(amount)}`, amount, member, () => location.reload(), error => {
        controls.querySelectorAll('button.primary').forEach(button => { button.disabled = true; });
        errorText(error, status);
      }));
    controls.append(...charge);
    const paid = plan.status === 'active' || plan.status === 'canceling';
    outlet.replaceChildren(
      el('h2', {}, automatic ? '오늘 한도를 다 썼어요. 새벽 4시에 다시 차요.'
        : `오늘 한도 ${quota.percent}% · 새벽 4시에 다시 차요`),
      el('progress', {max: 100, value: quota.percent, 'aria-label': '오늘 한도'}),
      text('글로는 계속 이야기할 수 있어요'),
      controls,
      paid ? text('구독 중이에요 · 하루 한도 2배') : el('div', {class: 'stack'},
        text(`구독하면 하루 한도가 2배예요 · 월 ${price(plan.priceKrw)}`),
        link('구독 알아보기', '/me/plan', 'plain')),
      status,
    );
    if (!member.paymentsEnabled) outlet.append(notice('결제는 곧 열려요.'));
  } catch (error) {
    errorText(error, outlet);
  } finally {
    outlet.removeAttribute('aria-busy');
  }
}

function planCard(plan, member, render) {
  const card = el('article', {class: 'card stack'}, el('h2', {}, '구독'));
  const outcome = el('div', {'aria-live': 'polite'});
  async function change(operation) {
    try { await api('/api/subscription/' + operation, {method: 'POST'}); }
    catch (error) { if (error.status !== 409) throw error; }
    await render();
  }
  if (plan.status === 'active') {
    const next = plan.nextChargeAt ? ` · 다음 결제 ${dateLabel(plan.nextChargeAt)}` : '';
    card.append(text(`구독 중${next} · ${price(plan.priceKrw)}`));
    const confirm = button('해지하기', () => action(confirm, outcome, () => change('cancel')), 'danger');
    const modal = el('dialog', {class: 'sheet stack'}, el('h2', {}, '구독 해지'),
      text(`${dateLabel(plan.periodEnd)}까지 하루 한도 2배예요. 그 뒤 끝나요.`),
      outcome, confirm, button('닫기', () => modal.close()));
    card.append(button('해지하기', () => modal.showModal(), 'plain'), modal);
    if (plan.newPrice) {
      const {priceKrw, from, agreed} = plan.newPrice;
      const priceNotice = `${dateLabel(from)}부터 월 ${price(priceKrw)}으로 바뀌어요. 동의하지 않으면 그날 끝나요.`;
      const response = el('div', {'aria-live': 'polite'});
      const agree = button('동의하기', () => action(agree, response, () => change('price-consent')), 'primary');
      card.prepend(notice(priceNotice, [agreed ? text('동의했어요') : agree, response]));
    }
  } else if (plan.status === 'canceling') {
    card.append(text(`${dateLabel(plan.periodEnd)}까지 하루 한도 2배예요. 그 뒤 끝나요.`));
  } else {
    card.append(text(`하루 한도 2배 · 월 ${price(plan.priceKrw)}`),
      purchaseControl('subscription_month', '구독하기', plan.priceKrw, member, render));
  }
  return card;
}

export async function plan() {
  header('한도와 구독', {label: '내 정보', url: '/me'});
  showTabs(null);
  show(...Array.from({length: 3}, () => el('div', {class: 'skeleton', 'aria-hidden': 'true'})));
  async function render() {
    const [member, quota, subscription] = await Promise.all([
      api('/api/me'), api('/api/me/quota'), api('/api/subscription'),
    ]);
    const gauge = el('progress', {max: 100, value: quota.percent, 'aria-label': '오늘 한도'});
    const heading = el('section', {class: 'card stack'}, el('h2', {}, '오늘 한도'), gauge,
      text(`${quota.percent}% · 새벽 4시에 다시 차요`));
    const recharge = el('section', {id: 'recharge', class: 'card stack'}, el('h2', {}, '충전권'),
      Object.entries(RECHARGE).map(([product, [label, amount]]) => el('div', {class: 'row'},
        el('span', {class: 'grow'}, price(amount)), purchaseControl(product, label, amount, member, render))));
    show(heading, !member.paymentsEnabled ? notice('결제는 곧 열려요.') : null,
      recharge, planCard(subscription, member, render));
  }
  await render();
}

function returnHref() {
  const saved = sessionStorage.getItem('pet_pay_return');
  if (!saved || !saved.startsWith('/') || saved.startsWith('//')) return '/';
  try {
    const url = new URL(saved, location.origin);
    if (url.origin === location.origin && /^\/(create|pets|shop|me)(?:\/|$)/.test(url.pathname)) {
      return url.pathname + url.search + url.hash;
    }
  } catch {}
  return '/';
}

async function recentOrder(id) {
  const {items} = await api('/api/orders');
  return items.find(row => row.id === id);
}

function receipt(order, back) {
  if (!order) return false;
  if (order.status === 'fulfilled') {
    const value = {
      character_creation: '그림 후보를 그리고 있어요',
      recharge_half: '오늘 한도를 반 채웠어요', recharge_full: '오늘 한도를 가득 채웠어요',
      subscription_month: '구독이 시작됐어요', item: `${orderName(order)}이(가) 보관함에 들어갔어요`,
    };
    show(notice('결제했어요', text(value[order.product])), back);
    return true;
  }
  if (order.status === 'failed') {
    show(notice('결제가 되지 않았어요. 돈은 나가지 않았어요.', back));
    return true;
  }
  return false;
}

export async function paymentReturn() {
  header('결제 확인');
  showTabs(null);
  const query = new URLSearchParams(location.search);
  history.replaceState(null, '', location.pathname);
  const back = link('돌아가기', returnHref());
  back.addEventListener('click', () => sessionStorage.removeItem('pet_pay_return'));
  if (query.get('canceled') === '1') {
    show(notice('결제를 취소했어요.', back));
    return;
  }
  const id = query.get('orderId');
  const paymentKey = query.get('paymentKey');
  const amount = query.get('amount');
  const orderLink = () => link('주문 내역', ORDERS);

  async function confirm() {
    show(notice('결제를 확인하고 있어요', el('span', {class: 'busy', 'aria-hidden': 'true', 'aria-busy': 'true'})));
    page.setAttribute('aria-busy', 'true');
    try {
      if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id || '')
          || !paymentKey || paymentKey.length > 200 || !/^\d{1,6}$/.test(amount || '') || Number(amount) > 100_000) {
        throw Error('invalid payment result');
      }
      let order;
      try {
        order = await api(`/api/orders/${id}/confirm`, {method: 'POST', body: {paymentKey, amount: Number(amount)}});
      } catch (error) {
        if (error.code !== 'wrong_state') throw error;
        order = await recentOrder(id);
      }
      if (receipt(order, back)) return;
      if (!order) {
        show(notice('찾을 수 없어요.', orderLink()));
        return;
      }
      if (order.status !== 'paid') throw Error('unexpected payment state');
      show(notice('결제는 됐어요. 받은 것을 넣고 있어요', orderLink()));
      const deadline = performance.now() + 60_000;
      while (performance.now() + 3000 <= deadline) {
        await wait(3000);
        if (performance.now() > deadline) break;
        if (receipt(await recentOrder(id), back)) return;
      }
    } catch (error) {
      if (error.status === 404) show(notice('찾을 수 없어요.', orderLink()));
      else show(notice('확인하지 못했어요. 결제는 주문 내역에서 볼 수 있어요.',
        el('div', {class: 'row'}, button('다시 확인하기', confirm, 'primary'), orderLink())));
    }
  }
  await confirm();
}
