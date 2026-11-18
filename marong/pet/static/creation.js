import {action, AI_NOTICE, api, banner, button, CONSENT, currency, dateLabel, el, errorText, Failure, header,
  link, notice, page, picture, show, showTabs, signIn, text} from './pet.js';
import {pendingCard} from './home.js';
import {pushControl} from './push-control.js';
import {business} from './shop.js';

const stages = {
  photos: ['traits', '사진을 살펴보고 있어요'], traits: ['traits', '특징표 고치기'],
  rejected: ['traits', '사진 다시 고르기'], failed_traits: ['traits', '사진 다시 고르기'],
  traits_confirmed: ['preview', '미리 보기와 결제'], previewed: ['preview', '미리 보기와 결제'],
  expired: ['preview', '미리 보기와 결제'], paid: ['candidates', '그림 후보를 그리고 있어요'],
  candidates: ['candidates', '그림 후보 고르기'], chosen: ['candidates', '표정을 그리고 있어요'],
  failed_candidates: ['candidates', '그림 후보 고르기'], sheet_needs_operator: ['candidates', '표정을 그리고 있어요'],
  sheet_ready: ['name', '이름 짓기'],
};

export const stageLabel = state => stages[state]?.[1] || '아이 만들기';
export const creationPath = job => job.state === 'done' && job.petId ? `/pets/${job.petId}`
  : `/create/${job.id}/${stages[job.state]?.[0] ?? 'traits'}`;
const home = {label: '홈', url: '/'};
const consentNotice = () => banner(CONSENT, link('설정에서 바꾸기', '/me#consents', 'plain'));
const again = (message, label = '사진 다시 고르기') => notice(message, link(label, '/create', 'button primary'));
const output = () => el('div', {'aria-live': 'polite'});

async function changeCreation(job, operation, options, {refreshBusy = false} = {}) {
  const path = `/api/creations/${job.id}`;
  try { return await api(`${path}/${operation}`, options); }
  catch (error) {
    if (error.code !== 'wrong_state' && !(refreshBusy && error.code === 'busy')) throw error;
    const target = creationPath(await api(path));
    sessionStorage.setItem('pet:creation-refresh', target);
    location.replace(target);
    return null;
  }
}

function waitForUpdate(id, onData, interval = 2_000) {
  const began = Date.now();
  let timer;
  let fetching = false, stopped = false, suspended = false;
  function schedule(delay) {
    clearTimeout(timer);
    if (!stopped && !suspended && !document.hidden && !fetching) timer = setTimeout(tick, delay);
  }
  function stop() {
    stopped = true;
    clearTimeout(timer);
    document.removeEventListener('visibilitychange', visibility);
    window.removeEventListener('pagehide', hide);
    window.removeEventListener('pageshow', restore);
  }
  async function tick() {
    if (stopped || suspended || document.hidden || fetching) return;
    fetching = true;
    let delay = interval;
    try {
      const data = await api(`/api/creations/${id}`);
      if (stopped || suspended) return;
      if (onData(data)) stop();
      else if (Date.now() - began >= 30_000) delay = 5_000;
    } catch (error) {
      if (error.status === 401) stop();
      delay = 5_000;
    } finally {
      fetching = false;
      schedule(delay);
    }
  }
  function visibility() { schedule(0); }
  function hide(event) {
    if (!event.persisted) { stop(); return; }
    suspended = true;
    clearTimeout(timer);
  }
  function restore(event) {
    if (!event.persisted) return;
    suspended = false;
    visibility();
  }
  document.addEventListener('visibilitychange', visibility);
  window.addEventListener('pagehide', hide);
  window.addEventListener('pageshow', restore);
  schedule(interval);
  return stop;
}

async function uploadable(file) {
  let source, url;
  try {
    try { source = await createImageBitmap(file); }
    catch {
      url = URL.createObjectURL(file);
      source = new Image();
      source.src = url;
      await source.decode();
    }
    const scale = Math.min(1, 1600 / Math.max(source.width, source.height));
    const canvas = el('canvas');
    canvas.width = Math.max(1, Math.round(source.width * scale));
    canvas.height = Math.max(1, Math.round(source.height * scale));
    const context = canvas.getContext('2d', {alpha: false});
    context.fillStyle = '#fff';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(source, 0, 0, canvas.width, canvas.height);
    const jpeg = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', .9));
    if (!jpeg) throw new TypeError('photo');
    return jpeg;
  } finally {
    source?.close?.();
    if (url) URL.revokeObjectURL(url);
  }
}

function uploadPhotos(body, progress) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open('POST', '/api/creations');
    request.setRequestHeader('Accept', 'application/json');
    request.timeout = 60_000;
    request.responseType = 'json';
    request.upload.addEventListener('progress', event => {
      if (event.lengthComputable && event.total > 0) progress.value = event.loaded * 100 / event.total;
    });
    request.addEventListener('load', () => {
      if (request.status === 202 && request.response?.id) {
        resolve(request.response);
        return;
      }
      if (request.status === 401) signIn();
      reject(new Failure(request.status, request.response || {}));
    });
    const failed = () => reject(new Failure(0));
    for (const type of ['error', 'abort', 'timeout']) request.addEventListener(type, failed);
    request.send(body);
  });
}

async function photos(me) {
  const [{items: pets}, {items: jobs}] = await Promise.all([api('/api/pets'), api('/api/creations')]);
  const top = jobs.map(pendingCard);
  if (!me.overseasTransfer) { show(...top, consentNotice()); return; }
  if (pets.length + jobs.length >= 5 || jobs.length >= 3) {
    show(...top, notice(pets.length + jobs.length >= 5 ? '아이는 5마리까지 만들 수 있어요.'
      : '만들고 있는 아이가 있어요. 먼저 마치거나 지워 주세요.'));
    return;
  }
  const slots = Array.from({length: 3}, () => ({}));
  const chosen = el('div', {class: 'slots'});
  const kind = el('fieldset', {}, el('legend', {}, '누구를 만들까요?'),
    el('label', {class: 'check'}, el('input', {name: 'kind', type: 'radio', value: 'living'}), '함께 사는 아이'),
    el('label', {class: 'check'}, el('input', {name: 'kind', type: 'radio', value: 'memorial'}), '무지개다리를 건넌 아이'));
  const outcome = output();
  const submit = el('button', {type: 'submit', class: 'primary', disabled: true}, '올리기');
  const form = el('form', {}, kind, chosen,
    text('정면 얼굴, 귀와 무늬가 보이는 사진, 전신 한 장이면 가장 닮아요', 'muted'),
    text('사람이 함께 찍히면 얼굴은 회색으로 가려요', 'muted'), outcome, submit);
  let uploading = false;
  const update = () => { submit.disabled = uploading || !kind.querySelector('input:checked')
    || !slots.some(slot => slot.blob) || slots.some(slot => slot.loading || slot.invalid); };

  for (let index = 0; index < slots.length; index++) {
    const slot = slots[index];
    const label = ['정면 얼굴', '귀와 무늬', '전신'][index];
    const input = el('input', {type: 'file', accept: 'image/*,.heic,.heif', class: 'sr-only', 'aria-label': label});
    const preview = el('div', {class: 'picture'}, text(label, 'muted'));
    const warning = el('small', {'aria-live': 'polite', class: 'error'});
    slot.showError = message => {
      slot.invalid = Boolean(message);
      warning.textContent = message;
      if (message) preview.setAttribute('aria-invalid', 'true');
      else preview.removeAttribute('aria-invalid');
    };
    const clear = button('×', () => {
      if (slot.url) URL.revokeObjectURL(slot.url);
      Object.assign(slot, {url: null, blob: null, loading: false});
      preview.replaceChildren(text(label, 'muted'));
      slot.showError('');
      clear.hidden = true;
      input.value = '';
      update();
    }, 'plain');
    clear.setAttribute('aria-label', `${label} 사진 빼기`);
    clear.hidden = true;
    input.addEventListener('change', async () => {
      const file = input.files[0];
      if (!file) return;
      const invalidBefore = slot.invalid;
      slot.loading = true;
      input.disabled = true;
      slot.showError('');
      update();
      try {
        const blob = await uploadable(file);
        if (slot.url) URL.revokeObjectURL(slot.url);
        Object.assign(slot, {blob, url: URL.createObjectURL(blob)});
        preview.replaceChildren(el('img', {src: slot.url, alt: label}));
        clear.hidden = false;
      } catch {
        const message = /\.(heic|heif)$/i.test(file.name) ? '사진 앱에서 JPEG로 저장해 주세요'
          : `${index + 1}번째 사진을 열 수 없어요. JPEG나 PNG, 8MB 이하로 올려 주세요.`;
        if (invalidBefore) slot.showError(message);
        else warning.textContent = message;
      } finally {
        input.value = '';
        input.disabled = false;
        slot.loading = false;
        update();
      }
    });
    const pick = button('고르기', () => input.click(), 'plain');
    pick.setAttribute('aria-label', label + ' 고르기');
    chosen.append(el('div', {class: 'stack'}, preview, input, pick, clear, warning));
  }
  form.addEventListener('input', update);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (submit.disabled || uploading) return;
    await action(submit, outcome, async () => {
      const body = new FormData();
      const sent = slots.filter(slot => slot.blob);
      body.set('kind', new FormData(form).get('kind'));
      sent.forEach((slot, index) => body.append('photos', slot.blob, `photo-${index + 1}.jpg`));
      const progress = el('progress', {max: 100, 'aria-label': '사진을 올리고 있어요'});
      outcome.replaceChildren(text('사진을 올리고 있어요', 'muted'), progress);
      uploading = true;
      kind.disabled = true;
      chosen.inert = true;
      submit.textContent = '올리기';
      try {
        const data = await uploadPhotos(body, progress);
        location.assign(creationPath(data));
      } catch (error) {
        const invalid = sent[error.photo - 1];
        if (error.code === 'invalid_photo' && invalid) {
          outcome.replaceChildren();
          invalid.showError(error.message);
        } else if (error.code === 'photo_check_unavailable') {
          submit.textContent = '다시 올리기';
          throw error;
        } else if (error.code === 'consent_required') {
          show(...top, consentNotice());
        } else if (error.code === 'pet_limit' || error.code === 'too_many_creations') {
          const latest = await api('/api/creations').catch(() => ({items: jobs}));
          show(...latest.items.map(pendingCard), notice(error.message));
        } else throw error;
      } finally {
        uploading = false;
        kind.disabled = false;
        chosen.inert = false;
      }
    });
    update();
  });
  show(...top, form);
}

const choices = {
  species: {dog: '개', cat: '고양이'},
  pattern: ['단색', '얼룩', '줄무늬', '턱시도', '포인트', '삼색', '브린들'],
  earShape: ['선 귀', '접힌 귀', '늘어진 귀', '반쯤 선 귀'],
  eyeColor: ['갈색', '검은색', '파란색', '초록색', '노란색', '짝눈'],
  build: ['작음', '중간', '큼', '긴 몸', '통통함'],
  furLength: ['짧음', '중간', '긺', '곱슬'],
};
const colors = ['흰색', '검은색', '갈색', '크림', '회색', '황토', '주황', '은색'];
const profiles = ['활발함', '얌전함', '겁이 많음', '먹보', '애교 많음', '고집 셈', '호기심 많음', '느긋함'];

function selectField(label, name, value) {
  const entries = Array.isArray(choices[name]) ? choices[name].map(option => [option, option]) : Object.entries(choices[name]);
  return el('label', {}, label, el('select', {name}, entries.map(([id, text]) =>
    el('option', {value: id, selected: id === value}, text))));
}

function stringField(label, name, limit, value = '') {
  return el('label', {}, label, el('input', {name, maxlength: limit, value}));
}

function checks(label, name, options, initial = [], limit = 3) {
  const fields = options.map(value => el('input', {type: 'checkbox', name, value, checked: initial.includes(value)}));
  const group = el('fieldset', {}, el('legend', {}, label),
    el('div', {class: 'row'}, fields.map((element, index) => el('label', {class: 'check'}, element, options[index]))));
  function update() {
    const count = fields.filter(field => field.checked).length;
    fields.forEach(field => { field.disabled = !field.checked && count >= limit; });
  }
  group.addEventListener('change', update);
  update();
  return group;
}

function traits(job) {
  if (job.state === 'photos') {
    show(notice('사진을 살펴보고 있어요', text('30초쯤 걸려요.', 'muted')));
    waitForUpdate(job.id, next => {
      if (next.state === 'photos') return false;
      if (stages[next.state]?.[0] === 'traits') traits(next);
      else location.replace(creationPath(next));
      return true;
    });
    return;
  }
  if (job.state === 'rejected' || job.state === 'failed_traits') {
    const message = job.state === 'failed_traits' ? '특징표를 만들지 못했어요. 잠시 뒤 다시 해 주세요. 사진은 지웠어요.'
      : job.failure === 'not_dog_or_cat' ? '개나 고양이를 찾지 못했어요' : '아이가 잘 보이지 않아요';
    show(again(message));
    return;
  }
  const t = job.traits;
  const outlet = output();
  const submit = el('button', {type: 'submit', class: 'primary'}, '이대로 만들기');
  const fields = el('fieldset', {class: 'stack'}, selectField('종', 'species', t.species), stringField('품종 추정', 'breedGuess', 30, t.breedGuess),
    checks('털 색 (1~3개)', 'coatColors', colors, t.coatColors),
    selectField('무늬', 'pattern', t.pattern), stringField('무늬 설명', 'patternNotes', 60, t.patternNotes),
    text('사진에서 보는 방향으로 적어요', 'muted'),
    selectField('귀 모양', 'earShape', t.earShape), selectField('눈 색', 'eyeColor', t.eyeColor),
    selectField('체격', 'build', t.build), selectField('털 길이', 'furLength', t.furLength),
    stringField('특징', 'distinctive', 60, t.distinctive));
  const form = el('form', {}, fields, outlet, submit);
  const feedback = new Map();
  for (const input of fields.querySelectorAll('[name]')) {
    if (feedback.has(input.name)) continue;
    const status = el('div', {class: 'busy', 'aria-live': 'polite', hidden: true});
    const group = input.name === 'coatColors' ? input.closest('fieldset') : input.closest('label');
    group.after(status);
    feedback.set(input.name, status);
  }

  const modified = new Set();
  const acknowledged = {...t};
  let pending = Promise.resolve();
  let confirming = false, refreshing = false;
  const readField = (values, name) => name === 'coatColors' ? values.getAll(name) : values.get(name);
  const changed = (name, value) => name === 'coatColors'
    ? value.length !== acknowledged[name].length || value.some(color => !acknowledged[name].includes(color))
    : value !== acknowledged[name];

  async function save(name, value) {
    const status = feedback.get(name);
    status.replaceChildren();
    if (!changed(name, value)) {
      status.hidden = true;
      return;
    }
    status.hidden = false;
    status.setAttribute('aria-busy', 'true');
    try {
      if (name === 'coatColors' && !value.length) throw new Failure(400, {code: 'invalid_input'});
      const result = await changeCreation(job, 'traits', {method: 'PATCH', body: {[name]: value}});
      if (result === null) refreshing = true;
      else acknowledged[name] = value;
    } catch (error) {
      errorText(error, status);
      throw error;
    } finally {
      status.removeAttribute('aria-busy');
      status.hidden = !status.childElementCount;
    }
  }

  form.addEventListener('input', event => {
    if (feedback.has(event.target.name)) modified.add(event.target.name);
  });
  form.addEventListener('change', event => {
    const {name} = event.target;
    if (confirming || refreshing || !navigator.onLine || !feedback.has(name)) return;
    modified.add(name);
    const value = readField(new FormData(form), name);
    pending = pending.then(() => refreshing ? null : save(name, value)).catch(() => {});
  });
  form.addEventListener('submit', event => {
    event.preventDefault();
    action(submit, outlet, async () => {
      const values = new FormData(form);
      confirming = fields.disabled = true;
      try {
        await pending;
        for (const name of modified) {
          if (refreshing) return;
          try { await save(name, readField(values, name)); }
          catch { return; }
        }
        if (refreshing) return;
        const next = await changeCreation(job, 'confirm-traits', {method: 'POST', body: {}});
        if (next) location.assign(creationPath(next));
      } finally { confirming = fields.disabled = false; }
    });
  });
  show(job.multiplePets ? banner('사진에 여러 아이가 있어요. 한 아이만 나온 사진이면 더 닮아요', link('사진 다시 고르기', '/create', 'plain')) : null, form);
}

async function preview(job, me) {
  const drawingKey = `pet:preview-request:${job.id}`;
  if (job.state !== 'traits_confirmed' || job.preview || job.failure) sessionStorage.removeItem(drawingKey);
  if (job.state === 'expired') { show(again('30일이 지나 미리 보기와 사진을 지웠어요.', '새로 만들기')); return; }
  function drawInProgress() {
    show(el('div', {class: 'picture', role: 'status'},
      el('div', {class: 'stack'}, el('span', {class: 'busy', 'aria-busy': 'true', 'aria-hidden': 'true'}),
        text('그리고 있어요'), text('1분쯤 걸려요.', 'muted'))));
    waitForUpdate(job.id, next => {
      if (!next.preview && !next.failure && next.state === 'traits_confirmed') return false;
      sessionStorage.removeItem(drawingKey);
      if (stages[next.state]?.[0] === 'preview') preview(next, me);
      else location.replace(creationPath(next));
      return true;
    });
  }
  if (sessionStorage.getItem(drawingKey)) { drawInProgress(); return; }
  const outlet = output();
  if (!job.preview) {
    let paused = false;
    const draw = button(job.failure === 'preview_failed' ? '다시 그리기' : '미리 보기 그리기', async () => {
      await action(draw, outlet, async () => {
        try {
          if (await changeCreation(job, 'preview', {method: 'POST', body: {}}) === null) return;
          sessionStorage.setItem(drawingKey, '1');
        } catch (error) {
          if (['preview_limit', 'budget_paused', 'consent_required'].includes(error.code)) {
            paused = true;
            outlet.replaceChildren(error.code === 'consent_required' ? consentNotice() : banner(error.message));
            return;
          }
          if (error.code !== 'busy') throw error;
        }
        drawInProgress();
      });
      if (paused) draw.disabled = true;
    }, 'primary');
    show(picture(null, ''), text(job.failure === 'preview_failed' ? '미리 보기를 그리지 못했어요. 횟수는 세지 않았어요.'
      : '미리 보기는 무료예요. 하루 3장까지 그려요'), outlet, draw);
    return;
  }
  const destination = `/create/${job.id}/candidates`;
  const price = `${currency.format(job.priceKrw)}원`;
  const paymentState = output();
  const paid = button('결제하고 만들기', () => dialog.showModal(), 'primary');
  paid.disabled = !me.paymentsEnabled;
  const paymentOff = () => paymentState.replaceChildren(text('결제는 곧 열려요.', 'muted'));
  if (paid.disabled) paymentOff();
  let checkingOut = false;
  async function checkout(useFreeTicket, resultOutlet) {
    if (checkingOut) return;
    checkingOut = true;
    const key = `pet:${useFreeTicket ? 'free' : 'paid'}-checkout:${job.id}`;
    const idempotencyKey = sessionStorage.getItem(key) || crypto.randomUUID();
    sessionStorage.setItem(key, idempotencyKey);
    try {
      const result = await changeCreation(job, 'checkout', {method: 'POST', body: {useFreeTicket, idempotencyKey}});
      if (result === null) return;
      if (result.order.status === 'fulfilled') {
        sessionStorage.removeItem(key);
        location.assign(destination);
        return;
      }
      if (!useFreeTicket && result.pg) sessionStorage.setItem('pet_pay_return', destination);
      if (result.order.status === 'paid') {
        resultOutlet.replaceChildren(notice('결제는 됐어요. 받은 것을 넣고 있어요', link('주문 내역', '/me/orders')));
        return;
      }
      // The payment provider's checkout window is connected when its SDK is selected.
      throw new Failure(503);
    } catch (error) {
      if (error.code === 'payments_off') {
        paid.disabled = true;
        dialog.close();
        paymentOff();
      } else if (error.code === 'identity_required') {
        resultOutlet.replaceChildren(notice('첫 결제 전에 본인인증을 한 번 해 주세요.', link('내 정보', '/me')));
      } else if (error.code === 'consent_required') {
        resultOutlet.replaceChildren(consentNotice());
      } else throw error;
    } finally {
      checkingOut = false;
    }
  }
  const orderOutlet = output();
  const confirm = button('결제하기', () => action(confirm, orderOutlet, () => checkout(false, orderOutlet)), 'primary');
  const ticket = button(`만들기권으로 만들기(${me.freeTickets}장 있어요)`, () =>
    action(ticket, outlet, () => checkout(true, outlet)));
  const dialog = el('dialog', {class: 'sheet stack'}, el('h2', {}, '캐릭터 만들기'), text(`${price}, 부가세 포함`),
    text('후보를 그리기 시작하면 철회할 수 없어요'), business(me), orderOutlet, confirm,
    button('닫기', () => dialog.close()));
  show(picture(job.preview, 'AI가 그린 미리 보기'), el('small', {}, 'AI가 그린 미리 보기'),
    text('결제하면 이 모습을 바탕으로 그림 후보 4장을 그려요'), el('strong', {}, `${price}(부가세 포함)`),
    text('후보를 그리기 시작하면 철회할 수 없어요', 'muted'),
    paymentState, paid,
    me.freeTickets > 0 ? ticket : null, outlet, text(`${dateLabel(job.expiresAt)}까지 결제하지 않으면 지워요`, 'muted'), dialog);
}

function candidates(job, me) {
  if (job.state === 'failed_candidates') {
    show(notice('그림을 그리지 못했어요. 결제는 자동으로 취소했어요.', link('주문 내역 보기', '/me/orders')), link('새로 만들기', '/create'));
    return;
  }
  if (job.state === 'sheet_needs_operator') {
    show(job.chosenId ? picture(`/api/media/${job.chosenId}`, '고른 그림') : null,
      notice('조금 더 걸려요. 다 되면 알려 드릴게요.'));
    return;
  }
  const alerts = job.kind === 'living' && ['paid', 'chosen'].includes(job.state)
    ? pushControl(me, {waiting: true}) : null;
  if (job.state === 'chosen') {
    show(picture(`/api/media/${job.chosenId}`, '고른 그림'),
      el('small', {}, 'AI가 그린 그림'),
      notice('표정을 그리고 있어요. 다 되면 이름을 지어 줘요'), alerts);
  } else {
    const drawing = job.state === 'paid';
    const currentRound = 2 - job.regenerationsLeft;
    const visibleCandidates = drawing
      ? job.candidates.filter(item => item.round < currentRound)
      : job.candidates;
    const completedInRound = drawing ? job.candidates.filter(item => item.round === currentRound) : [];
    const drawingGrid = drawing ? el('div', {class: 'grid', 'aria-busy': 'true'},
      Array.from({length: 4}, (_, index) => {
        const completed = completedInRound[index];
        return completed ? picture(completed.url, 'AI가 그린 후보')
          : el('div', {class: 'picture skeleton', 'aria-hidden': 'true'});
      })) : null;
    let selected;
    const outlet = output();
    const choiceGroup = el('fieldset', {class: 'grid', 'aria-label': '그림 후보'});
    const choose = button('이 그림으로 할게요', () => action(choose, outlet, async () => {
      choiceGroup.disabled = true;
      try {
        const next = await changeCreation(job, 'choose',
          {method: 'POST', body: {candidateId: selected}}, {refreshBusy: true});
        if (next?.state) location.replace(creationPath(next));
      } finally { choiceGroup.disabled = false; }
    }), 'primary');
    choose.disabled = true;
    const zoom = el('dialog', {class: 'sheet stack', 'aria-label': '그림 크게 보기'});
    const cards = visibleCandidates.map(item => {
      const control = el('input', {type: 'radio', name: 'candidate', value: item.id, disabled: job.state !== 'candidates',
        onchange: () => { selected = item.id; choose.disabled = false; }});
      const card = el('label', {class: 'candidate-option stack'}, control, picture(item.url, 'AI가 그린 후보'),
        el('small', {}, 'AI가 그린 그림'), el('span', {class: 'candidate-check', 'aria-hidden': 'true'}, '✓'));
      function enlarge(event) {
        if (choiceGroup.disabled || selected !== item.id || event.target.closest('button')) return;
        event.preventDefault();
        zoom.replaceChildren(picture(item.url, '크게 본 후보 그림'), button('닫기', () => zoom.close()));
        zoom.showModal();
      }
      card.addEventListener('click', enlarge);
      control.addEventListener('keydown', event => { if (event.key === 'Enter') enlarge(event); });
      return card;
    });
    choiceGroup.append(...cards);
    const note = el('textarea', {maxlength: 100, rows: 3});
    const remakeOutlet = output();
    const limit = text('다시 그리기를 다 썼어요.', 'muted');
    limit.hidden = Boolean(job.regenerationsLeft);
    const retry = button('다시 그리기', () => action(retry, remakeOutlet, async () => {
      try {
        const next = await changeCreation(job, 'regenerate',
          {method: 'POST', body: {note: note.value.trim()}}, {refreshBusy: true});
        if (next) location.replace(creationPath(next));
      } catch (error) {
        if (error.code !== 'regenerate_limit') throw error;
        sheet.close();
        redraw.disabled = true;
        limit.hidden = false;
      }
    }), 'primary');
    const sheet = el('dialog', {class: 'sheet stack'}, el('label', {}, '어떻게 바꿀까요?', note), remakeOutlet,
      retry, button('닫기', () => sheet.close()));
    const redraw = button(`다시 그려 주세요 · ${job.regenerationsLeft}번 남음`, () => sheet.showModal());
    redraw.disabled = !job.regenerationsLeft;
    show(visibleCandidates.length ? choiceGroup : null, drawingGrid,
      drawing ? notice('그림 후보 4장을 그리고 있어요. 몇 분 걸려요. 화면을 닫아도 돼요',
        el('span', {class: 'busy', 'aria-busy': 'true', 'aria-hidden': 'true'})) : null,
      job.state === 'candidates' ? choose : null,
      job.state === 'candidates' ? redraw : null,
      job.state === 'candidates' ? limit : null,
      alerts, outlet, sheet, zoom);
  }
  if (job.state === 'paid' || job.state === 'chosen') {
    waitForUpdate(job.id, next => {
      if (next.state === job.state && next.candidates.length === job.candidates.length) return false;
      if (stages[next.state]?.[0] === 'candidates') candidates(next, me);
      else location.replace(creationPath(next));
      return true;
    }, 5_000);
  }
}

function namePet(job) {
  const outlet = output();
  const greeting = el('p', {class: 'muted', role: 'status', hidden: true}, '첫 인사를 준비하고 있어요');
  const submit = el('button', {type: 'submit', class: 'primary', disabled: true}, '만나러 가기');
  const form = el('form', {}, stringField('이름', 'name', 12), checks('성격 (최대 3개)', 'personality', profiles),
    stringField('좋아하는 것', 'likes', 60), stringField('싫어하는 것', 'dislikes', 60),
    stringField('나를 부르는 말', 'callMe', 10), greeting, outlet, submit);
  const rules = [
    {key: 'name', limit: 12, required: true, pattern: /^[가-힣A-Za-z0-9 -]+$/,
      hint: '1~12자, 한글·영문·숫자·공백·하이픈'},
    {key: 'likes', limit: 60, hint: '60자 이하'},
    {key: 'dislikes', limit: 60, hint: '60자 이하'},
    {key: 'callMe', limit: 10, required: true, hint: '1~10자'},
  ];
  for (const rule of rules) {
    rule.control = form.elements.namedItem(rule.key);
    rule.message = el('small', {id: `pet-profile-${rule.key}-error`, class: 'error',
      'aria-live': 'polite', hidden: true}, `입력을 확인해 주세요. ${rule.hint}`);
    rule.control.closest('label').after(rule.message);
    rule.control.setAttribute('aria-describedby', rule.message.id);
  }
  const key = `pet:profile:${job.id}`;
  const restored = sessionStorage.getItem(key);
  if (restored) {
    try {
      const draft = JSON.parse(restored);
      for (const input of form.querySelectorAll('input[name]')) {
        if (input.type === 'checkbox') input.checked = draft.personality?.includes(input.value) === true;
        else if (typeof draft[input.name] === 'string') input.value = draft[input.name];
      }
      form.querySelector('input[type="checkbox"]')?.dispatchEvent(new Event('change', {bubbles: true}));
    } catch {}
  }
  function draft() {
    const values = new FormData(form);
    return {...Object.fromEntries(values), personality: values.getAll('personality')};
  }
  function update(showMissing = false) {
    const data = draft();
    let valid = true;
    for (const rule of rules) {
      const original = data[rule.key];
      const trimmed = original.trim();
      const invalid = (rule.required && !trimmed) || [...trimmed].length > rule.limit
        || /[\x00-\x1f\ud800-\udfff]/u.test(original) || (rule.pattern && !rule.pattern.test(trimmed));
      if (invalid) valid = false;
      const showError = invalid && (showMissing || Boolean(original));
      rule.message.hidden = !showError;
      if (showError) rule.control.setAttribute('aria-invalid', 'true');
      else rule.control.removeAttribute('aria-invalid');
    }
    if (!submit.hasAttribute('aria-busy')) submit.disabled = !valid;
    return valid;
  }
  update();
  form.addEventListener('input', () => { sessionStorage.setItem(key, JSON.stringify(draft())); update(); });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (submit.hasAttribute('aria-busy') || !update(true)) return;
    await action(submit, outlet, async () => {
      const {name, ...intro} = draft();
      greeting.hidden = false;
      try {
        const pet = await changeCreation(job, 'finish', {method: 'POST', body: {name: name.trim(), intro}});
        if (!pet) return;
        sessionStorage.removeItem(key);
        location.assign(`/pets/${pet.id}`);
      } finally { greeting.hidden = true; }
    });
    update();
  });
  show(banner(AI_NOTICE), picture(`/api/media/${job.chosenId}`, '고른 정면 그림'), el('small', {}, 'AI가 그린 그림'),
    job.kind === 'memorial' ? el('small', {}, '❀ 추억') : null, el('h2', {}, '이름을 지어 주세요'), form);
}

function creationLoading(stage) {
  const placeholder = (style = '') => el('div', {class: `skeleton ${style}`});
  const squares = count => Array.from({length: count}, () => placeholder('picture'));
  const lines = count => Array.from({length: count}, () => placeholder('label-placeholder'));
  let contents;
  switch (stage) {
    case 'photos':
      contents = [el('div', {class: 'row'}, placeholder('label-placeholder grow'), placeholder('label-placeholder grow')),
        el('div', {class: 'slots'}, squares(3))];
      break;
    case 'traits':
      contents = lines(9);
      break;
    case 'preview':
      contents = [...squares(1), placeholder('home-action-placeholder')];
      break;
    case 'candidates':
      contents = [el('div', {class: 'grid'}, squares(4))];
      break;
    case 'name':
      contents = [...squares(1), ...lines(5)];
      break;
    default:
      return;
  }
  show(el('section', {class: 'stack creation-loading', 'aria-hidden': 'true'}, contents));
  page.setAttribute('aria-busy', 'true');
}

export async function creation(path) {
  showTabs(null);
  if (path === '/create') {
    header('아이 만들기', home);
    creationLoading('photos');
    await photos(await api('/api/me'));
    return;
  }
  const [, , id, stage] = path.split('/');
  header({traits: '특징표 고치기', preview: '미리 보기와 결제', candidates: '그림 후보 고르기', name: '이름 짓기'}[stage]
    || '아이 만들기', home);
  creationLoading(stage);
  const me = await api('/api/me');
  const job = await api(`/api/creations/${id}`);
  if (path !== creationPath(job)) { location.replace(creationPath(job)); return; }
  if (stage === 'traits') traits(job);
  else if (stage === 'preview') await preview(job, me);
  else if (stage === 'candidates') candidates(job, me);
  else if (stage === 'name') namePet(job);
}
