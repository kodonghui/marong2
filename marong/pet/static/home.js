import {action, api, banner, button, CONSENT, dateLabel, DELETE_RECEIPT, el, errorText, header,
  link, notice, page, picture, resumeAfterSignIn, show, showTabs, text, today} from './pet.js';
import {creationPath, stageLabel} from './creation.js';

const LEGAL = '/static/legal/';
const signedOutNotice = 'AI가 만든 캐릭터와 이야기하는 서비스예요. 진짜 그 아이가 아니에요';

function signedOut() {
  const url = new URL(location.href);
  const loginError = url.searchParams.get('loginError');
  const hasLoginError = url.searchParams.has('loginError');
  if (hasLoginError) {
    url.searchParams.delete('loginError');
    history.replaceState(null, '', url);
  }
  const deleted = sessionStorage.getItem(DELETE_RECEIPT);
  sessionStorage.removeItem(DELETE_RECEIPT);
  show(deleted ? banner('24시간 안에 지워요') : null,
    hasLoginError ? banner(loginError === 'underage' ? '이 서비스는 만 19세 이상만 쓸 수 있어요.'
      : '로그인을 마치지 못했어요. 다시 해 주세요.') : null,
    picture('/static/pet-welcome.webp', '나란히 앉은 개와 고양이', 'hero'),
    el('section', {class: 'stack notice'},
      el('h2', {}, '우리 아이 사진으로 그림 캐릭터를 만들고 이야기해요'),
      text(signedOutNotice, 'muted')),
    el('div', {class: 'stack'}, link('카카오로 시작', '/api/auth/kakao/start', 'button kakao'),
      link('구글로 시작', '/api/auth/google/start', 'button google')),
    el('footer', {class: 'stack notice'}, text('만 19세 이상만 쓸 수 있어요', 'muted'),
      el('div', {class: 'row'}, link('이용약관', LEGAL + 'terms.html', 'plain'),
        link('개인정보 처리방침', LEGAL + 'privacy.html', 'plain'))));
}

function petCard(pet) {
  const archived = pet.status === 'archived';
  return el('a', {class: archived ? 'card pet archived' : 'card pet', href: `/pets/${pet.id}`},
    pet.sheet?.front ? picture(pet.sheet.front, '', 'thumb') : el('span', {class: 'thumb', 'aria-hidden': 'true'}),
    el('div', {class: 'grow'}, el('strong', {}, pet.name),
      pet.mode === 'memorial' ? el('small', {}, '❀ 추억') : null,
      pet.lastTalkAt ? text(dateLabel(pet.lastTalkAt), 'muted') : null),
    el('span', {'aria-hidden': 'true'}, '›'));
}

export function pendingCard(job) {
  return el('a', {class: 'card pet pending', href: creationPath(job)},
    el('span', {class: 'thumb', 'aria-hidden': 'true'}),
    el('div', {class: 'grow'}, el('strong', {}, stageLabel(job.state)), text('이어서', 'muted')),
    el('span', {'aria-hidden': 'true'}, '›'));
}

export async function home() {
  header('마롱이');
  showTabs(null);
  show(el('div', {class: 'skeleton', 'aria-hidden': 'true'}),
    el('div', {class: 'skeleton', 'aria-hidden': 'true'}),
    el('div', {class: 'skeleton home-action-placeholder', 'aria-hidden': 'true'}));
  page.setAttribute('aria-busy', 'true');
  let me;
  try { me = await api('/api/me', {auth: false}); }
  catch (error) {
    if (error.status !== 401) throw error;
    signedOut();
    return;
  }
  if (resumeAfterSignIn()) return;
  const [{items: pets}, {items: creations}, quota] = await Promise.all([
    api('/api/pets'), api('/api/creations'), api('/api/me/quota'),
  ]);
  const active = pets.filter(pet => pet.status === 'active');
  const archived = pets.filter(pet => pet.status === 'archived');
  showTabs('/', active.some(pet => pet.mode === 'living'));
  const quotaLine = el('div', {class: 'banner row'},
    el('strong', {}, `오늘 한도 ${quota.percent}%`), el('small', {}, '· 새벽 4시에 다시 차요'));
  const consent = me.overseasTransfer ? null : banner(CONSENT, link('설정에서 바꾸기', '/me#consents', 'plain'));
  const archive = archived.length ? el('details', {class: 'card stack'},
    el('summary', {}, `보관한 아이 ${archived.length}`), el('div', {class: 'stack'}, archived.map(petCard))) : null;
  const remaining = pets.length + creations.length < 5;
  const add = remaining ? link('아이 만들기', '/create', 'button primary')
    : el('div', {class: 'stack'}, el('button', {disabled: true}, '아이 만들기'), text('아이는 5마리까지 만들 수 있어요.', 'muted'));
  show(consent, quotaLine,
    !pets.length && !creations.length ? notice('아직 아이가 없어요. 사진 한 장으로 만들어 볼까요?') : null,
    ...active.map(petCard), ...creations.map(pendingCard), archive, add);
}

function field(label, name, max) {
  return el('label', {}, label, el('input', {name, inputmode: 'numeric', maxlength: max, required: true}));
}

function consentField(name, label, detail, href, required = true) {
  return el('div', {class: 'row'},
    el('label', {class: 'check grow'}, el('input', {name, type: 'checkbox', required}), label),
    href ? link('보기', href, 'plain') : el('details', {}, el('summary', {}, '보기'), text(detail, 'muted')));
}

function birthDate(values) {
  const [year, month, day] = ['year', 'month', 'day'].map(key => values.get(key));
  if (!/^\d{4}$/.test(year) || +year < 1 || !/^\d{1,2}$/.test(month) || !/^\d{1,2}$/.test(day)) return null;
  const value = `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`;
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(+date) || date.toISOString().slice(0, 10) !== value || value > today()) return null;
  return value;
}

export async function signup() {
  header('가입', {label: '홈', url: '/'});
  showTabs(null);
  const inviteError = el('div', {id: 'signup-invite-error', 'aria-live': 'polite'});
  const inviteInput = el('input', {name: 'inviteCode', maxlength: 8, autocapitalize: 'characters',
    'aria-describedby': inviteError.id});
  const invite = el('div', {class: 'stack', hidden: true}, el('label', {}, '초대 코드', inviteInput), inviteError);
  const outcome = el('div', {'aria-live': 'polite'});
  const dateError = el('div', {id: 'birth-date-error', 'aria-live': 'polite'});
  const consentError = el('div', {id: 'signup-consent-error', 'aria-live': 'polite'});
  const dateFields = el('fieldset', {'aria-describedby': dateError.id}, el('legend', {}, '생년월일'),
    el('div', {class: 'date-fields'}, field('년', 'year', 4), field('월', 'month', 2), field('일', 'day', 2)),
    dateError);
  const consentFields = el('fieldset', {'aria-describedby': consentError.id}, el('legend', {}, '필수 동의'),
    consentField('agreeTerms', '이용약관', '', LEGAL + 'terms.html'),
    consentField('agreePrivacy', '개인정보 처리방침', '', LEGAL + 'privacy.html'),
    consentField('aiNoticeConfirmed', 'AI 고지', 'AI가 만든 캐릭터이고 진짜 그 아이가 아니에요'), consentError);
  const submit = el('button', {type: 'submit', class: 'primary', disabled: true}, '가입하기');
  const form = el('form', {novalidate: true}, dateFields, consentFields,
    el('fieldset', {}, el('legend', {}, '선택 동의'),
      consentField('overseasTransfer', '국외 이전', '', LEGAL + 'overseas.html', false),
      text('동의하지 않으면 캐릭터 만들기와 대화를 할 수 없어요. 나중에 설정에서 바꿀 수 있어요', 'muted')),
    invite, outcome, submit);
  const required = ['agreeTerms', 'agreePrivacy', 'aiNoticeConfirmed'];
  const inviteCode = values => values.get('inviteCode').trim().toUpperCase();
  const validInvite = code => /^[A-Z0-9]{8}$/.test(code);
  const ready = (values = new FormData(form)) => navigator.onLine && birthDate(values) && required.every(name => values.has(name))
    && (invite.hidden || validInvite(inviteCode(values)));
  const refreshSubmit = values => {
    if (!submit.hasAttribute('aria-busy')) submit.disabled = !ready(values);
  };
  form.addEventListener('input', event => {
    const values = new FormData(form);
    if (dateFields.contains(event.target)) {
      const complete = ['year', 'month', 'day'].every(name => values.get(name));
      if (complete && !birthDate(values)) {
        dateFields.setAttribute('aria-invalid', 'true');
        dateError.replaceChildren(text('입력을 확인해 주세요.', 'error'));
      } else {
        dateFields.removeAttribute('aria-invalid');
        dateError.replaceChildren();
      }
    }
    if (consentFields.contains(event.target)) {
      consentFields.removeAttribute('aria-invalid');
      consentError.replaceChildren();
    }
    if (event.target === inviteInput) {
      const code = inviteCode(values);
      if (code && !validInvite(code)) {
        inviteInput.setAttribute('aria-invalid', 'true');
        inviteError.replaceChildren(text('입력을 확인해 주세요. 8자, 영문·숫자', 'error'));
      } else {
        inviteInput.removeAttribute('aria-invalid');
        inviteError.replaceChildren();
      }
    }
    refreshSubmit(values);
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (submit.hasAttribute('aria-busy') || !ready()) return;
    dateFields.removeAttribute('aria-invalid');
    consentFields.removeAttribute('aria-invalid');
    dateError.replaceChildren();
    consentError.replaceChildren();
    await action(submit, outcome, async () => {
      const values = new FormData(form);
      const data = {birthDate: birthDate(values)};
      for (const name of [...required, 'overseasTransfer']) data[name] = values.has(name);
      const code = inviteCode(values);
      if (code) data.inviteCode = code;
      try {
        await api('/api/signup', {method: 'POST', body: data, auth: false});
        location.replace('/');
      } catch (error) {
        if (error.code === 'invite_required') {
          invite.hidden = false;
          inviteInput.focus();
          errorText(error, outcome);
        } else if (error.code === 'underage') show(notice('이 서비스는 만 19세 이상만 쓸 수 있어요.', link('처음으로', '/')));
        else if (error.code === 'already_member') show(notice('이미 가입했어요.', link('홈으로', '/')));
        else if (error.status === 401) show(notice('가입 시간이 지났어요. 다시 로그인해 주세요.', link('처음으로', '/')));
        else if (error.code === 'invalid_input') {
          dateFields.setAttribute('aria-invalid', 'true');
          errorText(error, dateError);
        } else if (error.code === 'consents_missing') {
          consentFields.setAttribute('aria-invalid', 'true');
          consentError.replaceChildren(text('필수 항목에 동의해야 가입할 수 있어요.', 'error'));
        } else errorText(error, outcome);
      }
    });
    if (form.isConnected) refreshSubmit();
  });
  window.addEventListener('offline', () => refreshSubmit());
  show(form);
  return refreshSubmit;
}
