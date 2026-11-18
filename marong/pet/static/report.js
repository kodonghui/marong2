import {action, api, banner, button, el, errorText, page, picture, signIn, text} from './pet.js';

export const REPORT_DRAFT = 'pet:report-draft';

const reasons = [
  ['strange', '이상한 말'], ['hurtful', '상처 주는 말'], ['sexual', '성적인 말'],
  ['dangerous', '위험한 말'], ['bad_picture', '그림이 이상함'], ['other', '그 밖'],
];

export function mediaId(url) {
  return typeof url === 'string' ? /^\/api\/media\/([0-9a-f-]{36})$/i.exec(url)?.[1] : null;
}

export function reportControl(target, label, outcome, surface) {
  const path = location.pathname + location.search + location.hash;

  function open(draft) {
    if (page.querySelector('dialog[open]')) return;
    const choices = reasons.map(([value, reason]) => el('label', {class: 'choice'},
      el('input', {type: 'radio', name: 'reason', value}), reason));
    const memo = el('textarea', {rows: 2, maxlength: 200});
    const error = el('div', {'aria-live': 'polite'});
    const submit = el('button', {type: 'submit', class: 'primary', disabled: true}, '신고하기');
    const heading = el('legend', {id: 'report-title'}, '무엇이 문제인가요?');
    const form = el('form', {class: 'stack'}, target.targetType === 'message'
      ? text(target.preview, 'report-source')
      : picture(target.preview, '신고할 그림', 'thumb'),
      el('fieldset', {class: 'report-choices'}, heading, choices),
      el('label', {}, '메모', memo), error, submit);
    const modal = el('dialog', {class: 'sheet stack', 'aria-labelledby': 'report-title'},
      form, button('닫기', () => modal.close()));
    if (draft) {
      form.elements.reason.value = draft.reason;
      memo.value = draft.note;
      submit.disabled = !form.elements.reason.value;
    }
    form.addEventListener('change', () => {
      if (!submit.hasAttribute('aria-busy')) submit.disabled = !form.elements.reason.value;
    });
    form.addEventListener('submit', event => {
      event.preventDefault();
      const reason = form.elements.reason.value;
      if (!reason) return;
      void action(submit, error, async () => {
        const {targetType, targetId} = target;
        const payload = {targetType, targetId, reason, note: memo.value};
        try {
          await api('/api/reports', {method: 'POST', body: payload, auth: false});
        } catch (failure) {
          if (failure.status === 401) {
            sessionStorage.setItem(REPORT_DRAFT, JSON.stringify({...payload, path}));
            signIn(path);
            return;
          }
          if (failure.status !== 0 && failure.status < 500) throw failure;
          errorText(failure, error);
          error.append(button('다시 해 보기', () => form.requestSubmit(), 'plain'));
          return;
        }
        modal.close();
        outcome.replaceChildren(banner('신고했어요. 확인해 볼게요.'));
      });
    });
    modal.addEventListener('close', () => { modal.remove(); trigger.focus(); }, {once: true});
    page.append(modal);
    modal.showModal();
  }

  const trigger = button(label, () => open(), 'plain');
  if (sessionStorage.getItem(REPORT_DRAFT)) {
    requestAnimationFrame(() => {
      if (!trigger.isConnected || page.querySelector('dialog[open]')) return;
      let draft;
      try { draft = JSON.parse(sessionStorage.getItem(REPORT_DRAFT)); }
      catch { sessionStorage.removeItem(REPORT_DRAFT); return; }
      if (draft?.path !== path || draft.targetType !== target.targetType || draft.targetId !== target.targetId) return;
      open(draft);
      sessionStorage.removeItem(REPORT_DRAFT);
    });
  }
  if (surface) {
    let timer, start;
    const clear = () => { clearTimeout(timer); start = null; };
    surface.addEventListener('pointerdown', event => {
      clear();
      if (event.pointerType !== 'touch') return;
      start = [event.clientX, event.clientY];
      timer = setTimeout(open, 550);
    });
    surface.addEventListener('pointermove', event => {
      if (start && Math.hypot(event.clientX - start[0], event.clientY - start[1]) > 10) clear();
    });
    for (const type of ['pointerup', 'pointercancel', 'pointerleave']) surface.addEventListener(type, clear);
  }
  return trigger;
}
