import {action, api, banner, button, CONSENT, dateLabel, el, errorText, header, link, notice, picture,
  show, showTabs, text, today} from './pet.js';

const PERSONALITY = ['활발함', '얌전함', '겁이 많음', '먹보', '애교 많음', '고집 셈', '호기심 많음', '느긋함'];
const deadline = new Intl.DateTimeFormat('ko-KR', {timeZone: 'Asia/Seoul', month: 'long', day: 'numeric',
  hour: 'numeric', minute: 'numeric'});

function confirmation(trigger, confirmText, content, task, {danger = false, enabled = () => true} = {}) {
  const outcome = el('div', {'aria-live': 'polite'});
  const confirm = button(confirmText, () => {
    if (enabled()) void action(confirm, outcome, async () => { await task(); dialog.close(); });
  }, danger ? 'danger' : 'primary');
  const dialog = el('dialog', {class: 'sheet stack'}, content, outcome, confirm,
    button('아니에요', () => dialog.close()));
  dialog.addEventListener('input', () => { confirm.disabled = !enabled(); });
  const open = button(trigger, () => {
    confirm.disabled = !enabled();
    outcome.replaceChildren();
    dialog.showModal();
  }, danger ? 'plain danger' : 'plain');
  return el('div', {class: 'stack'}, open, dialog);
}

function profile(pet, url) {
  const field = (label, name, size, value) => el('label', {}, label,
    el('input', {name, maxlength: size, value, required: name === 'name' || name === 'callMe'}));
  const intro = pet.intro || {};
  const personality = PERSONALITY.map(value => el('input', {type: 'checkbox', name: 'personality', value,
    checked: intro.personality?.includes(value)}));
  const outcome = el('div', {'aria-live': 'polite'});
  const submit = el('button', {type: 'submit', class: 'primary'}, '저장');
  const form = el('form', {class: 'card stack'}, field('이름', 'name', 12, pet.name),
    el('fieldset', {}, el('legend', {}, '성격 (최대 3개)'),
      el('div', {class: 'row'}, personality.map((input, index) => el('label', {class: 'check'}, input, PERSONALITY[index])))),
    field('좋아하는 것', 'likes', 60, intro.likes), field('싫어하는 것', 'dislikes', 60, intro.dislikes),
    field('나를 부르는 말', 'callMe', 10, intro.callMe), outcome, submit);
  function limit() {
    const checked = personality.filter(input => input.checked).length;
    for (const input of personality) input.disabled = checked >= 3 && !input.checked;
  }
  form.addEventListener('change', limit);
  limit();
  form.addEventListener('submit', event => {
    event.preventDefault();
    void action(submit, outcome, async () => {
      const data = new FormData(form);
      const {name, likes, dislikes, callMe} = Object.fromEntries(data);
      await api(url, {method: 'PATCH', body: {name, intro: {likes, dislikes, callMe, personality: data.getAll('personality')}}});
      location.reload();
    });
  });
  return form;
}

function exportsPanel(id, url) {
  const root = el('div', {class: 'card stack'});
  const key = `pet:export:${id}`;
  const outcome = el('div', {'aria-live': 'polite'});
  const saved = sessionStorage.getItem(key);
  let timer;
  function retry(error) {
    if (error?.code === 'export_limit') {
      const blocked = el('button', {type: 'button', disabled: true}, '기록 내보내기');
      root.replaceChildren(text('오늘은 이미 내보냈어요.'), blocked);
      return;
    }
    root.replaceChildren(text('내보내지 못했어요. 횟수는 세지 않았어요.'), startButton('다시 하기'), outcome);
  }
  function display(job) {
    if (job.status === 'done') {
      const expires = new Date(job.readyUntil);
      if (job.readyUntil && expires.getTime() > Date.now()) {
        root.replaceChildren(link(`받기 · ${deadline.format(expires)}까지`, `/api/exports/${job.id}/download`));
      } else {
        sessionStorage.removeItem(key);
        root.replaceChildren(startButton(), outcome);
      }
    } else if (job.status === 'failed' || job.status === 'expired') {
      sessionStorage.removeItem(key);
      retry();
    } else {
      root.replaceChildren(text('만들고 있어요', 'muted'));
      timer = setTimeout(() => void poll(job.id), 5_000);
    }
  }
  async function poll(jobId) {
    if (!root.isConnected) return;
    try { display(await api(`/api/exports/${jobId}`)); }
    catch (error) {
      if (error.status === 404) {
        sessionStorage.removeItem(key);
        root.replaceChildren(startButton(), outcome);
      } else {
        const notice = el('div', {'aria-live': 'polite'});
        errorText(error, notice);
        root.replaceChildren(notice, button('다시 하기', () => void poll(jobId)));
      }
    }
  }
  function startButton(label = '기록 내보내기') {
    const start = button(label, () => action(start, outcome, async () => {
      try {
        const job = await api(url + '/export', {method: 'POST'});
        sessionStorage.setItem(key, job.id);
        display(job);
      } catch (error) {
        if (error.code !== 'export_limit') throw error;
        retry(error);
      }
    }));
    return start;
  }
  root.replaceChildren(startButton(), outcome);
  if (saved) queueMicrotask(() => void poll(saved));
  window.addEventListener('pagehide', () => clearTimeout(timer), {once: true});
  return root;
}

export async function settings(id) {
  const url = `/api/pets/${id}`;
  const screen = `/pets/${id}`;
  header('아이 설정', {label: '돌아가기', url: screen});
  showTabs(null);
  show(...Array.from({length: 6}, () => el('div', {class: 'skeleton', 'aria-hidden': 'true'})));
  const pet = await api(url);
  const archived = pet.status === 'archived';
  const memorial = pet.mode === 'memorial';
  const post = (endpoint, body) => api(url + endpoint, {method: 'POST', body});
  async function change(endpoint, body) {
    await post(endpoint, body);
    location.reload();
  }
  const date = el('input', {type: 'date', max: today()});
  const name = el('input', {maxlength: 12});
  const mode = confirmation('무지개다리를 건넜어요', '추억 모드로 바꾸기',
    el('section', {class: 'stack'}, el('h2', {}, '추억 모드로 바꾸면'),
      el('ul', {}, ['먼저 말 걸지 않아요', '일기 알림이 멈춰요', '상점과 충전 안내가 보이지 않아요',
        '7일 안에 되돌릴 수 있어요'].map(value => el('li', {}, value))),
      el('label', {}, '무지개다리를 건넌 날', date)),
    () => change('/mode', {mode: 'memorial', ...(date.value ? {passedOn: date.value} : {})}));
  const archive = confirmation('보관하기', '보관하기',
    text('보관하면 먼저 말 걸지 않고 일기와 그림만 볼 수 있어요'), () => change('/archive'));
  const restore = confirmation(`함께 사는 아이로 되돌리기 · ${pet.revertUntil ? dateLabel(pet.revertUntil) : ''}까지`,
    '함께 사는 아이로 되돌리기', text('함께 사는 아이로 되돌리기'), () => change('/mode', {mode: 'living'}));
  const deletion = confirmation('아이 지우기', '지우기', el('section', {class: 'stack'},
    text(`${pet.name}의 그림·대화·기억·일기·꾸밈을 모두 지워요. 되돌릴 수 없어요. 주문 기록은 남아요`),
    el('label', {}, '아이 이름', name)), async () => {
    await api(url, {method: 'DELETE', body: {confirm: name.value}});
    location.replace('/');
  }, {danger: true, enabled: () => name.value === pet.name});
  const unarchiveOutcome = el('div', {'aria-live': 'polite'});
  const unarchive = button('꺼내기', () => action(unarchive, unarchiveOutcome, () => change('/unarchive')));
  show(el('h2', {}, memorial ? `❀ ${pet.name}` : pet.name),
    archived ? notice('보관한 아이예요', unarchive) : profile(pet, url),
    archived ? unarchiveOutcome : null,
    !memorial && !archived ? mode : null,
    !archived && memorial && Date.parse(pet.revertUntil) > Date.now() ? restore : null,
    !archived && memorial && !pet.farewellDone ? link('작별 의식', screen + '/farewell') : null,
    !archived && memorial ? archive : null, exportsPanel(id, url), deletion);
}

export async function farewell(id) {
  const screen = `/pets/${id}`;
  const url = `/api${screen}`;
  header('작별 의식', {label: '돌아가기', url: screen + '/settings'});
  showTabs(null);
  const [pet, me] = await Promise.all([api(url), api('/api/me')]);
  const back = link('돌아가기', screen + '/settings');
  const already = () => show(notice('작별 의식은 한 번만 할 수 있어요.',
    link('마지막 장 보기', screen + '/diary')));
  if (pet.mode !== 'memorial') { show(notice('추억 모드에서만 할 수 있어요.', back)); return; }
  if (!me.overseasTransfer) { show(banner(CONSENT, link('설정에서 바꾸기', '/me#consents')), back); return; }
  if (pet.farewellDone) { already(); return; }
  const choices = [['letter', '마지막 편지 받기'], ['picture', '함께한 장면 한 장']];
  const outcome = el('div', {'aria-live': 'polite'});
  const note = el('textarea', {maxlength: 100, rows: 3});
  const scene = el('label', {hidden: true}, '함께한 장면', note);
  const start = el('button', {type: 'submit', class: 'primary', disabled: true}, '시작하기');
  const form = el('form', {class: 'card stack'}, choices.map(([value, copy]) => el('label', {class: 'check'},
    el('input', {type: 'radio', name: 'kind', value}), copy)), scene, outcome, start);
  form.addEventListener('change', () => {
    const kind = form.elements.kind.value;
    scene.hidden = kind !== 'picture';
    start.disabled = !kind;
  });
  const headline = text(`작별 의식은 한 번만 할 수 있어요. ${pet.name}가 남기는 마지막 장은 일기장에 남아요`);
  async function write() {
    const kind = form.elements.kind.value;
    if (!kind) return;
    show(notice(`${pet.name}가 쓰고 있어요`));
    try {
      const entry = await api(url + '/farewell', {method: 'POST', body: {
        kind, ...(kind === 'picture' ? {sceneNote: note.value} : {}),
      }, timeout: kind === 'picture' ? 100_000 : 70_000});
      const archiveResult = el('div', {'aria-live': 'polite'});
      const archive = button('보관하기', () => action(archive, archiveResult, async () => {
        await api(url + '/archive', {method: 'POST'});
        location.replace('/');
      }));
      show(el('article', {class: 'card stack'}, entry.picture ? picture(entry.picture, 'AI가 그린 그림') : text(entry.body),
        entry.picture ? el('small', {}, 'AI가 그린 그림') : null),
        link('일기장 마지막 장에 남겼어요', screen + '/diary/' + entry.date, 'plain'),
        notice('보관할까요? 보관하면 먼저 말 걸지 않고 일기와 그림만 볼 수 있어요',
          el('div', {class: 'row'}, archive, link('그대로 두기', screen), archiveResult)));
    } catch (error) {
      if (error.code === 'farewell_done') { already(); return; }
      show(headline, form);
      if (error.code === 'budget_paused') {
        outcome.replaceChildren(banner('오늘은 새 그림과 통화가 쉬어요. 글로는 계속 이야기할 수 있어요.',
          text('편지는 지금 받을 수 있어요')));
      } else if (error.code === 'farewell_failed') {
        outcome.replaceChildren(text('지금은 쓰지 못했어요. 잠시 뒤 다시 해 주세요.'));
        start.textContent = '다시 하기';
      } else errorText(error, outcome);
    }
  }
  form.addEventListener('submit', event => { event.preventDefault(); void write(); });
  show(headline, form);
}
