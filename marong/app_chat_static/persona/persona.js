'use strict';
const $ = id => document.getElementById(id);
const page = document.querySelector('.persona-page').dataset.page;
const KOREA = 'Asia/Seoul';
const API = '/chat/persona/api';
const DRAFT = 'marong.persona.instruction-draft';
const FIELDS = [
  ['support', '힘들 때 나한테 제일 바라는 건?', [['listen', '그냥 들어주기'], ['side', '내 편'], ['solve', '같이 방법 찾기'],
    ['distract', '기분 전환'], ['chat', '그냥 수다'], ['ask', '그때그때 물어봐']]],
  ['advice', '조언은 언제 해 줄까?', [['asked', '물어볼 때만'], ['sometimes', '괜찮아 보이면 가끔'], ['any', '언제든']]],
  ['honesty', '내가 좀 아닌 것 같을 때는?', [['gentle', '부드럽게'], ['direct', '솔직하게'], ['let_go', '그냥 넘어가 줘']]],
  ['lead', '이야기는 누가 이끌까?', [['follow', '따라갈게'], ['lead', '네가 이끌어 줘']]],
];
const PROACTIVE = [['normal', '보통'], ['less', '적게(하루 1번)'], ['off', '끔']];
const RULES = [['no_vocative', '이렇게 부르지 마', 1, 4], ['avoid_topic', '이 얘기는 꺼내지 마', 2, 20],
  ['call_me', '이렇게 불러 줘', 1, 4]];
const SOURCES = {questions: '첫 질문으로', draft: '대화를 보고', draft_silent: '초안 그대로',
  default: '기본으로', proposal: '바꾸기 제안으로', talk: '대화에서', screen: '여기서', admin: '동희가'};
const ERRORS = {
  invalid_request: '뭔가 잘못 보냈나 봐. 다시 해 볼게', feature_off: '이건 아직 준비 중이야',
  not_allowed: '이 계정으로는 열 수 없어', cross_site: '이 화면에서 다시 해 줘',
  needs_owner: '선톡을 늘리는 건 동희가 정해. 대화에서 말해 주면 동희한테 남겨 둘게',
  not_found: '찾지 못했어. 새로 보여 줄게', rule_limit: '너무 많아서 하나 빼 줄래?',
  too_many_requests: '너무 빨라! 조금 있다가 해 줘', ai_unavailable: '지금 잘 못 읽었어, 조금 뒤에 다시 말해 줄래?',
  db_unavailable: '잠깐 문제가 생겼어. 조금 있다가 다시 해 줘',
};
const FAILED = '잠깐 문제가 생겼어. 다시 해 볼래?';
let card, chose, instruction, busy = false, limitedUntil = 0;
let started = false;
let retryTimer = null, retryDelay = 5000;

function element(tag, text = '', className = '') {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}
function button(label, act, className = '') {
  const node = element('button', label, className);
  node.type = 'button';
  node.addEventListener('click', act);
  return node;
}
function note(text = '') { $('feedback').textContent = text; }
function stamp(value) {
  return new Intl.DateTimeFormat('ko-KR', {timeZone: KOREA, month: 'long', day: 'numeric'}).format(new Date(value));
}
function theme() {
  const hour = Number(new Intl.DateTimeFormat('en-GB', {timeZone: KOREA, hour: 'numeric', hourCycle: 'h23'}).format(new Date()));
  document.documentElement.dataset.theme = hour >= 8 && hour < 20 ? 'chestnut' : 'night';
}
function rememberDraft() {
  if (page !== 'instructions' || !instruction) return;
  try {
    if ($('instruction').value !== (instruction.text || '')) sessionStorage.setItem(DRAFT, $('instruction').value);
    else sessionStorage.removeItem(DRAFT);
  } catch {}
}
async function request(path, method = 'GET', body, headers = {}) {
  try {
    const response = await fetch(API + path, {method, credentials: 'same-origin', cache: 'no-store',
      redirect: 'manual', signal: AbortSignal.timeout(15_000), headers: {...(body ? {'Content-Type': 'application/json'} : {}), ...headers},
      body: body && JSON.stringify(body)});
    if (response.status === 401 || response.type === 'opaqueredirect') {
      rememberDraft();
      if (!sessionStorage.getItem('marong.persona.login')) {
        sessionStorage.setItem('marong.persona.login', '1');
        location.reload();
      }
      return {status: 401, data: {code: 'unauthenticated'}};
    }
    const data = response.status === 204 ? null : await response.json();
    return {status: response.status, data, retry: Number(response.headers.get('Retry-After')) || 0};
  } catch { return {status: 0, data: null}; }
}
function error(r) {
  const msg = r.status === 401 ? '다시 들어와 줘' : ERRORS[r.data?.code] || FAILED;
  note(msg);
}
function retryLoad(r) {
  error(r);
  $('reload').hidden = r.status === 401 || r.status === 403;
    if (!retryTimer && (r.status === 0 || r.status >= 500)) {
      retryTimer = setTimeout(() => {
        retryTimer = null;
        retryDelay = Math.min(30_000, retryDelay * 2);
        void load();
      }, retryDelay);
    }
}
function renderGroup(label, entries, selected, act, locked = () => false) {
  const section = element('section');
  if (label) section.append(element('h3', label));
  const group = element('div', '', 'persona-card-group');
  group.setAttribute('role', 'radiogroup');
  group.setAttribute('aria-label', label || '선톡');
  for (const [key, name] of entries) {
    const item = button(name, () => act(key));
    item.disabled = busy || locked(key);
    item.setAttribute('role', 'radio');
    item.setAttribute('aria-checked', String(key === selected));
    group.append(item);
  }
  section.append(group);
  return section;
}
function renderCard() {
  const patch = card.state === 'set';
  $('promise-label').textContent = card.state === 'draft' ? '내가 본 너는 이래' : '마롱이 약속';
  $('sentence').textContent = card.sentence || (card.state === 'asking'
    ? '글 대화에서 고르던 걸 여기서 마저 골라도 돼'
    : '마롱이가 너를 어떻게 대하면 좋을지 골라 줘. 1분이면 돼');
  $('source').textContent = card.setAt && SOURCES[card.source] ? `${stamp(card.setAt)} · ${SOURCES[card.source]} 정함` : '';
  const current = FIELDS[0][2].find(([value]) => value === card.want?.value);
  $('want').hidden = !current;
  if (current) {
    const until = new Intl.DateTimeFormat('ko-KR', {timeZone: KOREA, hour: 'numeric', minute: 'numeric'})
      .format(new Date(card.want.until));
    $('want').textContent = `지금은 '${current[1]}'로 할게 · ${stamp(card.want.until)} ${until}까지`;
  }
  $('choices').replaceChildren(...FIELDS.map(([field, label, entries]) =>
    renderGroup(label, entries, chose[field], value => {
      if (value === chose[field]) return;
      if (patch) void update({[field]: value}, '바꿨어');
      else { chose[field] = value; renderCard(); }
    })));
  $('make').hidden = patch;
  $('make').disabled = busy || !chose.support || !chose.advice || !chose.honesty;
  $('make').textContent = card.state === 'draft' ? '이대로 정하기' : '약속 만들기';
  $('call-first').textContent = card.callFirst ? '켜져 있어' : '꺼져 있어';
  const order = PROACTIVE.map(([key]) => key);
  $('proactive').replaceChildren(renderGroup('', PROACTIVE, card.proactive, value => {
    if (patch && value !== card.proactive) void update({proactive: value}, value === 'off' ? '선톡을 껐어' : '선톡을 적게로 바꿨어');
  }, value => !patch || order.indexOf(value) < order.indexOf(card.proactive)));
}
function setCard(data) {
  card = data; chose = {...data.values}; renderCard(); renderRules();
}
async function update(changes, message) {
  if (busy) return;
  busy = true; renderCard(); note();
  const r = await request('/card', 'PATCH', changes);
  busy = false;
  if (r.status === 200) { setCard(r.data); note(message); }
  else { renderCard(); error(r); }
}
function renderRules() {
  $('rules').replaceChildren(...RULES.map(([kind, label, min, max]) => {
    const box = element('div', '', 'persona-rules');
    box.append(element('h3', label));
    const rules = card.rules.filter(rule => rule.kind === kind);
    if (!rules.length) box.append(element('p', '아직 없어', 'hint'));
    const list = element('ul');
    for (const rule of rules) {
      const remove = button(`${rule.text} ×`, async () => {
        remove.disabled = true;
        const r = await request(`/rules/${rule.id}`, 'DELETE');
        if (r.status === 204) { card.rules = card.rules.filter(item => item.id !== rule.id); renderRules(); note('뺐어'); }
        else { remove.disabled = false; error(r); }
      }, 'text-button');
      remove.setAttribute('aria-label', `${rule.text} 규칙 지우기`);
      const line = element('li'); line.append(remove); list.append(line);
    }
    box.append(list);
    const form = element('form');
    form.hidden = true;
    const input = element('input'); input.maxLength = max;
    input.setAttribute('aria-label', label);
    const submit = element('button', '넣기', 'text-button'); submit.type = 'submit';
    const add = button('더하기', () => { form.hidden = false; add.hidden = true; input.focus(); }, 'text-button');
    const cancel = button('그만', () => { form.hidden = true; add.hidden = false; input.value = ''; }, 'text-button');
    form.append(input, submit, cancel);
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const text = input.value.trim();
      if (text.length < min || text.length > max) { note(`${min}~${max}자로 써 줘`); return; }
      submit.disabled = true;
      const r = await request('/rules', 'POST', {kind, text});
      submit.disabled = false;
      if (r.status === 200) { note('이미 있어'); return; }
      if (r.status !== 201) { error(r); return; }
      if (kind === 'call_me') card.rules = card.rules.filter(row => row.kind !== kind);
      card.rules.push(r.data);
      renderRules();
    });
    box.append(add, form);
    return box;
  }));
}
function syncInstruction() {
  const input = $('instruction');
  $('count').textContent = `${input.value.length}/500`;
  const left = Math.max(0, Math.ceil((limitedUntil - Date.now()) / 1000));
  $('save').disabled = busy || left > 0 || !input.value.trim() || input.value.trim() === (instruction?.text || '');
  $('save').textContent = busy ? '읽는 중…' : left ? `${left}초 뒤에` : '저장';
  input.readOnly = busy;
}
function setInstruction(data, copy = true) {
  instruction = data;
  if (copy) $('instruction').value = data.text || '';
  $('understood-box').hidden = !data.understood;
  $('understood').textContent = data.understood || '';
  $('updated').textContent = data.updatedAt ? `${stamp(data.updatedAt)}에 고침` : '';
  $('remove').hidden = !data.text;
  $('moved').replaceChildren();
  syncInstruction();
}
async function save() {
  if ($('save').disabled) return;
  const text = $('instruction').value.trim();
  busy = true; syncInstruction(); note('마롱이가 읽고 있어');
  const r = await request('/instructions', 'PUT', {text});
  busy = false;
  if (r.status !== 200) {
    if (r.status === 429) limitedUntil = Date.now() + Math.max(1, r.retry) * 1000;
    syncInstruction(); error(r); return;
  }
  setInstruction(r.data.instructions);
  rememberDraft();
  for (const rule of r.data.moved.rules) {
    const link = element('a', `꼭 지킬 것에 넣었어: '${rule.text}'`);
    link.href = '/chat/persona/'; $('moved').append(link);
  }
  if (r.data.moved.proactive) $('moved').append(element('p', r.data.moved.proactive === 'off' ? '선톡을 껐어' : '선톡을 적게로 바꿨어'));
  if (r.data.ownerAsked) $('moved').append(element('p', '선톡 늘리는 건 동희한테 남겨 뒀어'));
  if (r.data.cannot) $('moved').append(element('p', r.data.cannot));
  note('적었어');
  $('understood-box').scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
}
async function clear() {
  $('approve').disabled = true;
  const r = await request('/instructions', 'DELETE');
  $('approve').disabled = false;
  if (r.status !== 204) { error(r); return; }
  $('confirm').hidden = true;
  setInstruction({text: null});
  rememberDraft();
  note('지웠어');
}
const CHANNELS = {discord_dm: '디스코드 DM', app: '앱', kakao_dm: '카톡',
  kakao_group: '카톡 단체방', discord_server: '디스코드 서버', call: '통화'};
const MEMORY_GROUPS = [['fact', '사실'], ['preference', '좋아하는 것'], ['event', '일·계획'],
  ['relation', '사람'], ['hard', '힘든 일']];
const memory = {items: [], loops: [], more: false, loading: false, selected: null, quotes: new Set()};

function byDay(value) {
  const [year, month, day] = value.split('-');
  return stamp(year + '-' + month + '-' + day + 'T12:00:00+09:00');
}

function memoryRow(row, type) {
  const key = type + ':' + row.id;
  const selected = memory.selected?.key === key ? memory.selected : null;
  const article = element('article', '', 'persona-box memory-row');
  const line = element('div', '', 'memory-line');
  const details = element('div');
  details.append(element('p', row.text));
  const date = stamp(row.heardAt);
  const source = CHANNELS[row.channel] || '';
  const timing = type === 'loop'
    ? [row.due && byDay(row.due) + '까지', date + ' ' + source]
    : [date, source, row.validUntil && byDay(row.validUntil) + '까지'];
  details.append(element('p', timing.filter(Boolean).join(' · '), 'hint'));
  const tags = [row.sensitive && '둘만 아는 얘기', row.scope === 'group' && '단체방에서만'].filter(Boolean);
  if (tags.length) details.append(element('p', tags.join(' · '), 'hint'));
  const reveal = row.quote && button('들은 말 보기', () => {
    const shown = !memory.quotes.has(key);
    if (shown) memory.quotes.add(key); else memory.quotes.delete(key);
    quote.hidden = !shown;
    reveal.setAttribute('aria-expanded', String(shown));
  }, 'text-button');
  if (reveal) {
    reveal.disabled = Boolean(selected?.sending);
    reveal.setAttribute('aria-expanded', String(memory.quotes.has(key)));
    reveal.setAttribute('aria-controls', 'memory-quote-' + type + '-' + row.id);
    details.append(reveal);
  }
  const forget = button('잊기', () => {
    memory.selected = {type, id: row.id, key};
    renderMemory();
    $('memory-confirm')?.focus();
  }, 'text-button');
  forget.disabled = Boolean(memory.selected?.sending);
  line.append(details, forget);
  article.append(line);
  const quote = element('blockquote', row.quote || '');
  if (row.quote) {
    quote.id = 'memory-quote-' + type + '-' + row.id;
    quote.hidden = !memory.quotes.has(key);
    article.append(quote);
  }
  if (selected) {
    const box = element('section', '', 'memory-confirm');
    box.id = 'memory-confirm';
    box.tabIndex = -1;
    box.append(element('p', '이걸 잊을까? 같은 말에서 나온 기억도 같이 잊어'));
    const confirm = button(selected.sending ? '잊는 중…' : selected.retry ? '다시 해 볼게' : '잊기',
      () => void submitForget(selected), 'primary');
    const cancel = button('그만', () => { memory.selected = null; renderMemory(); }, 'text-button');
    confirm.disabled = cancel.disabled = Boolean(selected.sending);
    box.append(confirm, cancel);
    if (selected.message) {
      const detail = element('p', selected.message, 'hint');
      detail.setAttribute('role', 'status');
      box.append(detail);
    }
    article.append(box);
  }
  return article;
}

function renderMemory() {
  const target = $('memory-list');
  target.replaceChildren();
  const groups = [['기다리는 얘기', memory.loops, 'loop'],
    ...MEMORY_GROUPS.map(([kind, label]) => [label, memory.items.filter(item => item.kind === kind), 'item'])];
  for (const [label, rows, type] of groups) {
    if (!rows.length) continue;
    const section = element('section', '', 'memory-group');
    section.append(element('h2', label), ...rows.map(row => memoryRow(row, type)));
    target.append(section);
  }
  $('memory-empty').hidden = Boolean(memory.items.length || memory.loops.length);
  $('memory-more').hidden = !memory.more;
}

function accessNotice(r) {
  $('content').hidden = true;
  $('memory-list').replaceChildren();
  memory.items = []; memory.loops = []; memory.quotes.clear(); memory.selected = null;
  const allowed = r.data?.code === 'feature_off';
  if (r.status === 403) {
    const path = $('memory-back');
    path.textContent = allowed ? '친구 약속으로' : '글 대화로';
    path.href = allowed ? '/chat/persona/' : '/chat/';
    path.hidden = false;
  }
}

async function loadMemory({more = false, keepNotice = false} = {}) {
  if (memory.loading || memory.selected?.sending) return;
  memory.loading = true;
  const control = $('memory-more');
  control.disabled = true;
  const cursor = more && memory.items.at(-1)?.id;
  const r = await request('/memories' + (cursor ? '?before=' + cursor : ''));
  memory.loading = false;
  control.disabled = false;
  $('memory-skeleton').hidden = true;
  if (r.status !== 200) {
    if (r.status === 401 || r.status === 403) accessNotice(r);
    retryLoad(r);
    $('memory-trace').textContent = r.data?.traceId || '';
    return;
  }
  if (!keepNotice) note();
  $('memory-trace').textContent = '';
  $('memory-back').hidden = true;
  $('reload').hidden = true;
  clearTimeout(retryTimer); retryTimer = null; retryDelay = 5000;
  try { sessionStorage.removeItem('marong.persona.login'); } catch {}
  if (cursor) memory.items.push(...r.data.items);
  else {
    memory.items = r.data.items;
    memory.loops = r.data.loops;
    memory.quotes.clear();
  }
  memory.more = r.data.hasMore;
  $('content').hidden = false;
  started = true;
  renderMemory();
}

async function submitForget(selected) {
  if (selected.sending || memory.selected !== selected || memory.loading) return;
  selected.requestKey ||= crypto.randomUUID();
  selected.sending = true;
  renderMemory();
  const r = await request('/forgets', 'POST', {type: selected.type, id: selected.id},
    {'Idempotency-Key': selected.requestKey});
  selected.sending = false;
  if ([200, 400, 404].includes(r.status)) {
    memory.selected = null;
    if (r.status === 200) {
      note('잊었어 · 기억 ' + r.data.forgot + '개, 들은 말 ' + r.data.messages + '개');
      $('content').hidden = true;
    } else error(r);
    renderMemory();
    await loadMemory({keepNotice: true});
  } else if (r.status === 401 || (r.status === 403 && r.data?.code !== 'cross_site')) {
    accessNotice(r);
    error(r);
  } else {
    selected.retry = r.status === 0;
    selected.message = r.status ? ERRORS[r.data?.code] || FAILED : '';
    renderMemory();
  }
}

async function load() {
  theme();
  if (page === 'memory') return loadMemory();
  const r = await request(page === 'card' ? '/card' : '/instructions');
  if (r.status !== 200) { retryLoad(r); return; }
  clearTimeout(retryTimer); retryTimer = null; retryDelay = 5000;
  try { sessionStorage.removeItem('marong.persona.login'); } catch {}
  $('content').hidden = false;
  $('reload').hidden = true;
  if (page === 'card') {
    setCard(r.data);
    const preview = await request('/instructions');
    $('instruction-preview').textContent = preview.status === 200
      ? preview.data.understood?.split(/(?<=[.!?])\s/)[0] || '아직 없어' : '못 불러왔어';
  } else {
    const dirty = started && $('instruction').value !== (instruction?.text || '');
    const changed = dirty && r.data.version !== instruction?.version;
    if (!dirty) setInstruction(r.data);
    if (!started) {
      try { $('instruction').value = sessionStorage.getItem(DRAFT) ?? $('instruction').value; } catch {}
      syncInstruction();
    }
    if (changed) {
      note('대화에서 바뀐 지침이 있어. 저장하면 지금 쓴 글로 바뀌어');
      const show = button('바뀐 글 보기', () => {
        $('understood-box').hidden = !r.data.understood;
        $('understood').textContent = r.data.understood || '';
      }, 'text-button');
      $('feedback').append(show);
    }
  }
  started = true;
}
if (page === 'card') {
  $('make').addEventListener('click', () => { void update(chose, '약속 정했어'); });
} else if (page === 'memory') {
  $('memory-more').addEventListener('click', () => void loadMemory({more: true}));
} else {
  $('instruction').addEventListener('input', syncInstruction);
  $('save').addEventListener('click', save);
  $('remove').addEventListener('click', () => { $('confirm').hidden = false; });
  $('cancel').addEventListener('click', () => { $('confirm').hidden = true; });
  $('approve').addEventListener('click', clear);
  addEventListener('pagehide', rememberDraft);
  setInterval(syncInstruction, 500);
}
$('reload').addEventListener('click', load);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && started && !busy && (page !== 'memory' || !memory.selected)) { void load(); }
});
setInterval(theme, 30_000);
void load();
