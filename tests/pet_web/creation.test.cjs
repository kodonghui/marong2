/** TC-426: browser states and the photo-to-introduction flow against a synthetic API fixture. */
const {after, before, test} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const {once} = require('node:events');
const {readFile} = require('node:fs/promises');
const path = require('node:path');
const {chromium} = require('playwright');

const assets = path.resolve(__dirname, '../../marong/pet/static');
const creationId = '00000000-0000-4000-8000-000000000900';
const candidateId = '00000000-0000-4000-8000-000000000901';
const petId = '00000000-0000-4000-8000-000000000902';
const traits = {species: 'dog', breedGuess: '푸들', coatColors: ['갈색'], pattern: '단색',
  patternNotes: '', earShape: '늘어진 귀', eyeColor: '갈색', build: '작음', furLength: '곱슬', distinctive: ''};
const pet = {id: petId, name: '콩이', status: 'active', mode: 'living', shopEntry: true,
  sheet: {front: '/static/pet-icon.png'}};
const type = {'.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.webp': 'image/webp',
  '.webmanifest': 'application/manifest+json', '.html': 'text/html'};
let browser;

function json(response, value, status = 200) {
  response.writeHead(status, {'Content-Type': 'application/json', 'Cache-Control': 'no-store'});
  response.end(JSON.stringify(value));
}

async function body(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return Buffer.concat(chunks);
}

async function fixture(t, {signedIn = true, consent = true, invite = false, reportLimited = false} = {}) {
  let member = signedIn;
  let state;
  let selected = null;
  const writes = [];
  function job() {
    const preview = ['previewed', 'paid', 'candidates', 'chosen', 'sheet_ready', 'done'].includes(state);
    return {id: creationId, state, kind: 'living', traits, multiplePets: false,
      preview: preview ? '/static/pet-icon.png' : null, regenerationsLeft: 2,
      candidates: ['candidates', 'chosen'].includes(state) ? [{id: candidateId, url: '/static/pet-icon.png'}] : [],
      chosenId: selected, petId: state === 'done' ? petId : null, priceKrw: 5900, expiresAt: '2026-12-17T00:00:00Z'};
  }
  const server = http.createServer(async (req, res) => {
    const {pathname} = new URL(req.url, 'http://localhost');
    if (pathname === '/api/me') return json(res, member ? {
      overseasTransfer: consent, paymentsEnabled: false, freeTickets: 1,
      memberNo: 'AB12CD34', identityVerified: false, status: 'active',
    } : {code: 'unauthenticated'}, member ? 200 : 401);
    if (pathname === '/api/signup' && req.method === 'POST') {
      const data = JSON.parse(await body(req));
      writes.push(data);
      if (invite && !data.inviteCode) return json(res, {code: 'invite_required', detail: '지금은 초대받은 분만 가입할 수 있어요.'}, 403);
      member = true;
      return json(res, {}, 201);
    }
    if (pathname === '/api/me/quota') return json(res, {percent: 60});
    if (pathname === '/api/pets') return json(res, {items: state === 'done' ? [pet] : []});
    if (pathname === '/api/creations' && req.method === 'GET') return json(res, {items: state ? [job()] : []});
    if (pathname === '/api/creations' && req.method === 'POST') {
      assert.match(req.headers['content-type'], /^multipart\/form-data/);
      const upload = (await body(req)).toString('latin1');
      assert.match(upload, /name="kind"\r\n\r\nliving/);
      assert.match(upload, /name="photos"; filename="photo-1.jpg"/);
      state = 'traits';
      return json(res, job(), 202);
    }
    if (pathname.startsWith(`/api/creations/${creationId}`)) {
      const stage = pathname.split('/')[4];
      if (req.method === 'GET') return json(res, job());
      const data = JSON.parse(await body(req));
      writes.push(data);
      if (stage === 'confirm-traits') state = 'traits_confirmed';
      if (stage === 'preview') { state = 'previewed'; return json(res, {}, 202); }
      if (stage === 'checkout') {
        if (data.useFreeTicket !== true || !/^[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/i.test(data.idempotencyKey)) {
          return json(res, {code: 'invalid_input'}, 400);
        }
        state = 'candidates';
        return json(res, {pg: null});
      }
      if (stage === 'choose') {
        selected = data.candidateId;
        state = 'sheet_ready';
        return json(res, job(), 202);
      }
      if (stage === 'finish') { state = 'done'; return json(res, pet, 201); }
      return json(res, job());
    }
    if (pathname === `/api/media/${candidateId}`) {
      res.writeHead(200, {'Content-Type': 'image/png'});
      return res.end(await readFile(path.join(assets, 'pet-icon.png')));
    }
    if (pathname === '/api/reports' && req.method === 'POST') {
      writes.push(JSON.parse(await body(req)));
      if (reportLimited) return json(res, {code: 'rate_limited', detail: '오늘은 더 신고할 수 없어요. 내일 다시 해 주세요.'}, 429);
      return json(res, {jobId: candidateId}, 201);
    }
    if (pathname === `/api/pets/${petId}/messages`) return json(res, {items: [{
      id: candidateId, role: 'pet', kind: 'greeting', text: '누나, 나 왔어!',
    }], before: null});
    if (pathname === `/api/pets/${petId}`) return json(res, pet);
    if (pathname === `/api/pets/${petId}/events`) {
      res.writeHead(200, {'Content-Type': 'text/event-stream'});
      return res.end('event: ping\ndata: {}\n\n');
    }
    if (pathname === `/api/pets/${petId}/diary` || pathname === `/api/pets/${petId}/diary/2026-11-17`) {
      const entry = {date: '2026-11-17', title: '산책 간 날', weather: '맑음', status: 'ready', kind: 'day',
        body: '오늘은 공원에서 낙엽을 밟았어.', picture: '/static/pet-welcome.webp', redrawsLeft: 2, drawing: false};
      return json(res, pathname.endsWith('/diary') ? {items: [entry]} : entry);
    }
    if (pathname.startsWith('/api/')) return json(res, {code: 'not_found'}, 404);
    if (/^\/static\/legal\/(terms|privacy|overseas)\.html$/.test(pathname)) {
      res.writeHead(200, {'Content-Type': 'text/html; charset=utf-8'});
      return res.end('<!doctype html><html lang="ko"><title>시험 문서</title><p>화면 시험용 문서</p>');
    }
    const file = pathname.startsWith('/static/') || pathname === '/pet-worker.js' ? basename(pathname) : 'index.html';
    try {
      const bytes = await readFile(path.join(assets, file));
      res.writeHead(200, {'Content-Type': type[path.extname(file)]});
      res.end(bytes);
    } catch {
      res.writeHead(404); res.end();
    }
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  return {origin: `http://127.0.0.1:${server.address().port}`, writes};
}

const basename = name => name.split('/').at(-1);
async function visible(locator) { await locator.waitFor({state: 'visible'}); }

module.exports = {fixture};

if (require.main === module) {
  before(async () => { browser = await chromium.launch(); });
  after(async () => { await browser.close(); });

  for (const width of [360, 430]) {
    test(`SCR-140/142–147 at ${width}px: create, preview, free ticket, choose and name`, async t => {
      const {origin, writes} = await fixture(t);
      const page = await browser.newPage({viewport: {width, height: 820}});
      t.after(() => page.close());
      const errors = [];
      page.on('pageerror', error => errors.push(error));
      await page.goto(origin);
      await page.getByRole('link', {name: '아이 만들기'}).click();
      await page.getByText('함께 사는 아이', {exact: true}).click();
      await page.getByLabel('정면 얼굴', {exact: true}).setInputFiles(path.join(assets, 'pet-icon.png'));
      await page.getByRole('button', {name: '올리기'}).click();
      await visible(page.getByRole('heading', {name: '특징표 고치기'}));
      await page.getByLabel('품종 추정').fill('믹스');
      await page.getByRole('button', {name: '이대로 만들기'}).click();
      await page.getByRole('button', {name: '미리 보기 그리기'}).click();
      await visible(page.getByText('AI가 그린 미리 보기', {exact: true}));
      assert.equal(await page.getByRole('button', {name: '결제하고 만들기'}).isDisabled(), true);
      await page.getByRole('button', {name: /만들기권으로 만들기/}).click();
      await page.getByRole('radio', {name: 'AI가 그린 후보 AI가 그린 그림'}).check();
      await page.getByRole('button', {name: '이 그림으로 할게요'}).click();
      await page.getByLabel('이름', {exact: true}).fill('콩이');
      await page.getByLabel('나를 부르는 말').fill('누나');
      await page.getByRole('button', {name: '만나러 가기'}).click();
      await visible(page.getByText('누나, 나 왔어!', {exact: true}));
      assert.equal(await page.evaluate(() => document.body.scrollWidth <= innerWidth), true);
      assert.equal(writes.some(update => update.breedGuess === '믹스'), true);
      assert.equal(writes.some(update => update.candidateId === candidateId), true);
      assert.equal(writes.some(update => update.intro?.callMe === '누나'), true);
      assert.deepEqual(errors, []);
    });
  }

  test('SCR-140–141: login failure, mandatory consents and retained invite form', async t => {
    const {origin, writes} = await fixture(t, {signedIn: false, invite: true});
    const page = await browser.newPage({viewport: {width: 360, height: 780}});
    t.after(() => page.close());
    await page.goto(origin + '/?loginError=auth_provider');
    await visible(page.getByText('로그인을 마치지 못했어요. 다시 해 주세요.'));
    assert.equal(new URL(page.url()).search, '');
    assert.equal(await page.getByRole('link', {name: '구글로 시작'}).getAttribute('href'), '/api/auth/google/start');
    await page.goto(origin + '/signup');
    await page.getByLabel('년', {exact: true}).fill('2000');
    await page.getByLabel('월', {exact: true}).fill('3');
    await page.getByLabel('일', {exact: true}).fill('4');
    const submit = page.getByRole('button', {name: '가입하기'});
    assert.equal(await submit.isDisabled(), true);
    for (const label of ['이용약관', '개인정보 처리방침', 'AI 고지']) await page.getByRole('checkbox', {name: label}).check();
    assert.equal(await page.locator('input[type=checkbox][required]').count(), 3);
    await submit.click();
    await visible(page.getByLabel('초대 코드'));
    assert.equal(await page.getByLabel('년', {exact: true}).inputValue(), '2000');
    await page.getByLabel('초대 코드').fill('ABCD1234');
    await submit.click();
    await visible(page.getByRole('link', {name: '아이 만들기'}));
    assert.equal(writes[1].birthDate, '2000-03-04');
    assert.equal(writes[1].overseasTransfer, false);
  });

  test('SCR-142 displays consent state and waits for an explicit change', async t => {
    const {origin} = await fixture(t, {consent: false});
    const page = await browser.newPage();
    t.after(() => page.close());
    await page.goto(origin + '/create');
    await visible(page.getByRole('link', {name: '설정에서 바꾸기'}));
    assert.equal(await page.getByRole('button', {name: '올리기'}).count(), 0);
  });

  test('SCR-149–151 loads the approved diary layout and redraw controls', async t => {
    const {origin} = await fixture(t);
    const page = await browser.newPage({viewport: {width: 360, height: 790}});
    t.after(() => page.close());
    await page.goto(`${origin}/pets/${petId}/diary?month=2026-11`);
    await page.getByRole('link', {name: /산책 간 날/}).click();
    await visible(page.getByText('오늘은 공원에서 낙엽을 밟았어.'));
    await page.getByRole('button', {name: /새 그림으로 다시 그리기/}).click();
    await visible(page.getByRole('dialog').getByText('어떤 그림이면 좋을까요?'));
    assert.equal(await page.evaluate(() => document.body.scrollWidth <= innerWidth), true);
  });

  test('SCR-156 accepts a reason and retains input when the daily cap is reached', async t => {
    for (const reportLimited of [false, true]) {
      const {origin, writes} = await fixture(t, {reportLimited});
      const page = await browser.newPage({viewport: {width: 360, height: 760}});
      try {
        await page.goto(origin + '/pets/' + petId);
        await page.getByRole('button', {name: '신고', exact: true}).click();
        const modal = page.getByRole('dialog');
        const send = modal.getByRole('button', {name: '신고하기'});
        assert.equal(await modal.getByRole('radio').count(), 6);
        assert.equal(await send.isDisabled(), true);
        await modal.getByLabel('상처 주는 말').check();
        await modal.getByLabel('메모').fill('합성 시험');
        await send.click();
        assert.deepEqual(writes.at(-1), {targetType: 'message', targetId: candidateId,
          reason: 'hurtful', note: '합성 시험'});
        if (reportLimited) {
          await visible(modal.getByText('오늘은 더 신고할 수 없어요. 내일 다시 해 주세요.'));
          assert.equal(await modal.getByLabel('메모').inputValue(), '합성 시험');
          assert.equal(await modal.getByLabel('상처 주는 말').isChecked(), true);
        } else await visible(page.getByText('신고했어요. 확인해 볼게요.'));
      } finally { await page.close(); }
    }
  });
}
