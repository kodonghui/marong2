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
const orderId = '00000000-0000-4000-8000-000000000920';
const petId = '00000000-0000-4000-8000-000000000902';
const garmentId = '00000000-0000-4000-8000-000000000942';
const themeId = '00000000-0000-4000-8000-000000000943';
const stickerPackId = '00000000-0000-4000-8000-000000000944';
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

async function fixture(t, {signedIn = true, consent = true, invite = false, reportLimited = false, payment = 'fulfilled',
  closetMode, paymentsEnabled = false, layerFailure = false, outfitFailure = false, orderRetry = false,
  diaryDecor = false, subscription, exhaustedRedraw = false, diaryDays = false, chatNotices = [],
  creationState, pushKey = null, holdTraits, holdFinish, chooseBusy = false,
  wearingFixture = false, quotaPercent = 60} = {}) {
  let member = signedIn;
  let state = creationState;
  let selected = creationState === 'sheet_ready' ? candidateId : null;
  let currentTraits = {...traits};
  let memberPet = {...pet, intro: {personality: ['느긋함'], likes: '산책', dislikes: '', callMe: '누나'}};
  if (diaryDays) memberPet = {...memberPet, template: 'dog_small',
    sheet: {...memberPet.sheet, smile: '/static/pet-welcome.webp'}};
  if (closetMode) memberPet = {...memberPet, mode: closetMode === 'memorial' ? 'memorial' : 'living',
    status: closetMode === 'archived' ? 'archived' : 'active', shopEntry: closetMode === 'living',
    template: 'dog_small', outfit: {head: null, body: null, neck: null}};
  if (wearingFixture) memberPet.outfit = {...memberPet.outfit, head: garmentId};
  let needsConfirmation = true;
  let ownsGarment = false;
  let diaryStickers = [];
  let redrawAttempts = 0;
  let plan = subscription || {status: 'none', priceKrw: 9900, periodEnd: null, nextChargeAt: null, newPrice: null};
  const writes = [];
  let callStarts = 0;
  const order = {id: orderId, orderNo: 'P20261117-ABC123', product: 'item', itemName: '털모자',
    amountKrw: 1200, vatKrw: 109, status: 'fulfilled', createdAt: '2026-11-17T06:40:00Z',
    withdrawable: true, withdrawalNote: '한 번 입히면 철회할 수 없어요.'};
  function job() {
    const preview = ['previewed', 'paid', 'candidates', 'chosen', 'sheet_ready', 'done'].includes(state);
    return {id: creationId, state, kind: 'living', traits: currentTraits, multiplePets: false,
      preview: preview ? '/static/pet-icon.png' : null, regenerationsLeft: 2,
      candidates: ['candidates', 'chosen'].includes(state) ? [{id: candidateId, url: '/static/pet-icon.png'}] : [],
      chosenId: selected, petId: state === 'done' ? petId : null, priceKrw: 5900, expiresAt: '2026-12-17T00:00:00Z'};
  }
  const server = http.createServer(async (req, res) => {
    const {pathname, searchParams} = new URL(req.url, 'http://localhost');
    if (pathname === '/api/me') return json(res, member ? {
      overseasTransfer: consent, paymentsEnabled, freeTickets: 1,
      memberNo: 'AB12CD34', identityVerified: false, status: 'active',
      business: paymentsEnabled ? {'상호': '시험 상점'} : null,
    } : {code: 'unauthenticated'}, member ? 200 : 401);
    if (pathname === '/static/push-key.json') return json(res, {publicKey: pushKey});
    if (pathname === '/api/me/push' && req.method === 'POST') {
      writes.push(JSON.parse(await body(req)));
      return json(res, {jobId: orderId}, 201);
    }
    if (pathname === `/api/me/push/${orderId}` && req.method === 'DELETE') {
      writes.push('remove-push');
      res.writeHead(204);
      return res.end();
    }
    if (pathname === '/api/signup' && req.method === 'POST') {
      const data = JSON.parse(await body(req));
      writes.push(data);
      if (invite && !data.inviteCode) return json(res, {code: 'invite_required', detail: '지금은 초대받은 분만 가입할 수 있어요.'}, 403);
      member = true;
      return json(res, {}, 201);
    }
    if (pathname === '/api/me/quota') return json(res, {percent: quotaPercent});
    if (pathname === '/api/me/consents') return json(res, {items: [{kind: 'overseas_transfer', value: consent}]});
    if (pathname === '/api/subscription') return json(res, plan);
    if (pathname === '/api/subscription/cancel' && req.method === 'POST') {
      writes.push('cancel');
      plan = {...plan, status: 'canceling', nextChargeAt: null, newPrice: null};
      return json(res, plan);
    }
    if (pathname === '/api/subscription/price-consent' && req.method === 'POST') {
      writes.push('price-consent');
      plan = {...plan, newPrice: {...plan.newPrice, agreed: true}};
      return json(res, plan);
    }
    if (pathname === '/api/pets') return json(res, {items: state === 'done' ? [pet] : closetMode ? [memberPet] : []});
    if (pathname === '/api/me/inventory') {
      const items = [{itemId: garmentId, kind: 'wear', name: '털모자', slot: 'head', source: 'order',
        wornBy: [], contents: [], withdrawableUntil: needsConfirmation ? '2026-12-17T00:00:00Z' : null}];
      if (diaryDecor) items.push(
        {itemId: themeId, kind: 'theme', name: '군밤 테마', withdrawableUntil: '2026-12-17T00:00:00Z'},
        {itemId: stickerPackId, kind: 'sticker_pack', name: '별 스티커', contents: ['star-small']},
      );
      return json(res, {items});
    }
    if (pathname === '/api/shop') return json(res, {items: [null, 'wear'].includes(searchParams.get('kind')) ? [{
      id: garmentId, kind: 'wear', name: '털모자', priceKrw: 1200, slot: 'head',
      limited: true, saleEndsAt: '2026-11-30T00:00:00Z', owned: ownsGarment, purchasable: paymentsEnabled, contents: [],
    }] : []});
    if (pathname === `/api/items/${garmentId}/layer`) {
      assert.equal(searchParams.get('template'), 'dog_small');
      if (layerFailure) return json(res, {code: 'server_error'}, 500);
      res.writeHead(200, {'Content-Type': 'image/png'});
      return res.end(await readFile(path.join(assets, 'pet-icon.png')));
    }
    if (pathname === `/api/pets/${petId}/outfit` && req.method === 'PUT') {
      const outfit = JSON.parse(await body(req));
      writes.push(outfit);
      if (outfitFailure) return json(res, {code: 'wrong_slot'}, 400);
      needsConfirmation = false;
      memberPet = {...memberPet, outfit};
      return json(res, memberPet);
    }
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
      if (stage === 'traits' || stage === 'confirm-traits') {
        if (stage === 'traits') await holdTraits?.(data);
        if (state !== 'traits') return json(res, {code: 'wrong_state'}, 409);
        if (stage === 'traits') {
          if (data.breedGuess === '거절 입력') return json(res, {code: 'invalid_input'}, 400);
          currentTraits = {...currentTraits, ...data};
        } else state = 'traits_confirmed';
      }
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
        if (chooseBusy) {
          state = 'chosen';
          return json(res, {code: 'busy'}, 409);
        }
        state = 'sheet_ready';
        return json(res, job(), 202);
      }
      if (stage === 'finish') {
        await holdFinish?.();
        state = 'done';
        return json(res, pet, 201);
      }
      return json(res, job());
    }
    if (pathname === `/api/media/${candidateId}`) {
      res.writeHead(200, {'Content-Type': 'image/png'});
      return res.end(await readFile(path.join(assets, 'pet-icon.png')));
    }
    if (pathname === '/api/orders' && req.method === 'POST') {
      writes.push(JSON.parse(await body(req)));
      if (orderRetry && writes.length === 1) return json(res, {code: 'server_error'}, 500);
      ownsGarment = true;
      return json(res, {pg: null, order}, 201);
    }
    if (pathname === '/api/orders') return json(res, {items: payment === 'empty' ? [] : [order]});
    if (pathname === `/api/orders/${orderId}/confirm`) {
      writes.push(JSON.parse(await body(req)));
      if (payment === 'already') return json(res, {code: 'wrong_state'}, 409);
      return json(res, {...order, status: payment});
    }
    if (pathname === `/api/orders/${orderId}/withdraw`) return json(res, {...order, status: 'refunded', withdrawable: false});
    if (pathname === '/api/reports' && req.method === 'POST') {
      writes.push(JSON.parse(await body(req)));
      if (reportLimited) return json(res, {code: 'rate_limited', detail: '오늘은 더 신고할 수 없어요. 내일 다시 해 주세요.'}, 429);
      return json(res, {jobId: candidateId}, 201);
    }
    if (pathname === `/api/pets/${petId}/messages`) return json(res, {items: [...chatNotices, {
      id: candidateId, role: 'pet', kind: 'greeting', text: '누나, 나 왔어!',
    }], before: null});
    if (pathname === `/api/pets/${petId}/calls` && req.method === 'POST') {
      callStarts += 1;
      return json(res, {token: 'synthetic-call-token', wsUrl: 'ws://' + req.headers.host + '/pet-call'}, 201);
    }
    if (pathname === `/api/pets/${petId}`) return json(res, memberPet);
    if (pathname === `/api/pets/${petId}/mode`) {
      const payload = JSON.parse(await body(req));
      writes.push(payload);
      memberPet = {...memberPet, mode: payload.mode, revertUntil: new Date(Date.now() + 86400000).toISOString()};
      return json(res, memberPet);
    }
    if (pathname === `/api/pets/${petId}/farewell`) {
      const payload = JSON.parse(await body(req));
      writes.push(payload);
      return json(res, {date: '2026-11-17', body: '같이 산책한 날이 정말 좋았어.', kind: 'farewell'});
    }
    if (pathname === `/api/pets/${petId}/export`) return json(res, {id: orderId, status: 'queued'}, 202);
    if (pathname === `/api/exports/${orderId}`) return json(res, {id: orderId, status: 'done',
      readyUntil: new Date(Date.now() + 86400000).toISOString()});
    if (pathname === `/api/pets/${petId}/events`) {
      res.writeHead(200, {'Content-Type': 'text/event-stream'});
      return res.end('event: ping\ndata: {}\n\n');
    }
    if (pathname === `/api/pets/${petId}/diary-style` && req.method === 'PUT') {
      const diaryStyle = JSON.parse(await body(req));
      writes.push(diaryStyle);
      memberPet = {...memberPet, diaryStyle};
      return json(res, memberPet);
    }
    const diaryPath = `/api/pets/${petId}/diary`;
    if (pathname === diaryPath || pathname.startsWith(diaryPath + '/2026-11-')) {
      if (pathname.endsWith('/redraw') && req.method === 'POST' && exhaustedRedraw) {
        redrawAttempts++;
        return json(res, {code: 'quota_exhausted', detail: '오늘 한도를 다 썼어요.',
          prompt: redrawAttempts === 1 ? 'recharge' : 'brief'}, 409);
      }
      if (pathname.endsWith('/stickers') && req.method === 'PUT') {
        diaryStickers = JSON.parse(await body(req));
        writes.push(diaryStickers);
      }
      const entry = {date: '2026-11-17', title: '산책 간 날', weather: '맑음', status: 'ready', kind: 'day',
        body: '오늘은 공원에서 낙엽을 밟았어.', picture: '/static/pet-welcome.webp', redrawsLeft: 2, drawing: false,
        stickers: diaryStickers};
      if (diaryDays) {
        entry.picture = null;
        entry.composite = {backgroundId: 'park', expression: 'smile', outfit: {head: garmentId}};
      }
      const past = {...entry, date: '2026-11-16', title: '지난 일기'};
      const skipped = {...entry, date: '2026-11-18', status: 'skipped'};
      if (pathname === diaryPath) return json(res, {items: diaryDays ? [skipped, entry, past] : [entry]});
      return json(res, pathname.endsWith('/2026-11-16') ? past : entry);
    }
    if (pathname.startsWith('/api/')) return json(res, {code: 'not_found'}, 404);
    if (/^\/static\/legal\/(terms|privacy|overseas)\.html$/.test(pathname)) {
      res.writeHead(200, {'Content-Type': 'text/html; charset=utf-8'});
      return res.end('<!doctype html><html lang="ko"><title>시험 문서</title><p>화면 시험용 문서</p>');
    }
    if (pathname === '/static/backgrounds/stages.json') return json(res, {width: 1536, height: 1024,
      stages: {home_livingroom: {centerX: 768, floorY: 876, height: 708},
        park: {centerX: 768, floorY: 888, height: 681}, rainbow_meadow: {centerX: 766, floorY: 886, height: 680}}});
    if (pathname === `/static/items/${garmentId}/thumb.webp` || pathname.startsWith('/static/backgrounds/')
      || pathname === `/static/items/${themeId}/background.webp`
      || pathname === `/static/items/${stickerPackId}/stickers/star-small.webp`) {
      res.writeHead(200, {'Content-Type': 'image/webp'});
      return res.end(await readFile(path.join(assets, 'pet-welcome.webp')));
    }
    const file = pathname.startsWith('/static/') || pathname === '/pet-worker.js' ? basename(pathname) : 'index.html';
    try {
      const worklets = {'call-playback.js': 'playback.js', 'call-capture.js': 'capture.js'};
      const filename = Object.hasOwn(worklets, file)
        ? path.resolve(__dirname, '../../tools/vertex_live/static', worklets[file]) : path.join(assets, file);
      const bytes = await readFile(filename);
      res.writeHead(200, {'Content-Type': type[path.extname(file)]});
      res.end(bytes);
    } catch {
      res.writeHead(404); res.end();
    }
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  return {origin: `http://127.0.0.1:${server.address().port}`, writes, get callStarts() { return callStarts; }};
}

const basename = name => name.split('/').at(-1);
async function visible(locator) { await locator.waitFor({state: 'visible'}); }

module.exports = {fixture};

if (require.main === module) {
  before(async () => { browser = await chromium.launch({
    args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'],
  }); });
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

  test('SCR-147 links approved numbers only from separate system notices', async t => {
    const {origin} = await fixture(t, {chatNotices: [
      {id: 'emergency', role: 'system', kind: 'crisis_notice', text: '이미 다쳤으면 119'},
      {id: 'guidance', role: 'system', kind: 'crisis_notice', text: '자살예방상담전화 109 · 24시간'},
      {id: 'message', role: 'member', kind: 'chat', text: '109번 이야기를 들었어.'},
    ]});
    const page = await browser.newPage({viewport: {width: 360, height: 820}});
    t.after(() => page.close());
    await page.goto(`${origin}/pets/${petId}`);
    const messages = page.getByRole('log', {name: '메시지'});
    const links = messages.locator('.bubble.system a');
    await visible(messages.getByRole('link', {name: '이미 다쳤으면 119'}));
    assert.deepEqual(await links.evaluateAll(items => items.map(item => item.getAttribute('href'))), ['tel:109', 'tel:119']);
    assert.equal(await messages.getByText('109번 이야기를 들었어.').evaluate(item => item.tagName), 'P');
  });

  test('SCR-147 shows the current outfit and draws a proactive picture from its saved composition', async t => {
    const {origin} = await fixture(t, {closetMode: 'living', diaryDays: true, wearingFixture: true,
      chatNotices: [{id: 'synthetic-proactive', role: 'pet', kind: 'proactive', text: '산책 가고 싶었어.',
        composite: {backgroundId: 'park', expression: 'smile', outfit: {head: null, neck: null, body: null}}}]});
    const page = await browser.newPage({viewport: {width: 360, height: 820}});
    t.after(() => page.close());
    await page.goto(`${origin}/pets/${petId}`);
    const portrait = page.locator('.portrait .outfit-stage[data-aligned="true"]');
    await visible(portrait);
    assert.equal(await portrait.locator('.outfit-background').getAttribute('src'), '/static/backgrounds/home_livingroom.webp');
    assert.equal(await portrait.locator('[data-slot=head]').getAttribute('src'),
      `/api/items/${garmentId}/layer?template=dog_small`);
    const picture = page.locator('.chat-log .outfit-stage[data-aligned="true"]');
    await visible(picture);
    assert.equal(await picture.locator('.outfit-background').getAttribute('src'), '/static/backgrounds/park.webp');
    assert.equal(await picture.locator('img[alt="콩이"]').getAttribute('src'), '/static/pet-welcome.webp');
    assert.equal(await picture.locator('[data-slot]').count(), 0);
    assert.equal(await page.evaluate(() => document.body.scrollWidth <= innerWidth), true);
  });

  test('SCR-147 uses the memorial scene and keeps text chat available after quota exhaustion', async t => {
    const {origin} = await fixture(t, {closetMode: 'memorial', quotaPercent: 0});
    const page = await browser.newPage({viewport: {width: 430, height: 820}});
    t.after(() => page.close());
    await page.goto(`${origin}/pets/${petId}`);
    await visible(page.getByText('오늘은 여기까지, 새벽 4시 뒤에 또 이야기해요.'));
    assert.equal(await page.locator('.portrait .outfit-background').getAttribute('src'), '/static/backgrounds/rainbow_meadow.webp');
    assert.equal(await page.getByRole('button', {name: '충전하기'}).count(), 0);
    assert.equal(await page.getByLabel('콩이에게 할 말').isEnabled(), true);
  });

  test('SCR-147 reconnects across two history pages without duplicating or reordering replies', {timeout: 15000}, async t => {
    const {origin} = await fixture(t);
    const page = await browser.newPage();
    t.after(() => page.close());
    await page.addInitScript(() => {
      window.petChatStreams = [];
      window.EventSource = class extends EventTarget {
        constructor() {
          super();
          window.petChatStreams.push(this);
        }
        close() {}
      };
    });
    const createRow = (number, role = 'pet', kind = 'chat') => ({
      id: String(number), text: `시험 대화 ${number}`, role, kind, createdAt: '2026-11-18T08:00:00Z',
    });
    const rows = [createRow(1, 'pet', 'greeting')];
    const fetched = [];
    const resumed = Promise.withResolvers();
    const complete = Promise.withResolvers();
    t.after(complete.resolve);
    await page.route('**/api/pets/*/messages*', async route => {
      const request = route.request();
      if (request.method() === 'POST') {
        const data = request.postDataJSON();
        const row = {...createRow(57, 'member'), text: data.text, clientId: data.clientId};
        rows.push(row);
        return route.fulfill({status: 201, json: row});
      }
      const before = new URL(request.url()).searchParams.get('before');
      const pageRows = rows.filter(row => before === null || Number(row.id) < Number(before)).reverse().slice(0, 50);
      if (rows.length > 1) {
        fetched.push(before);
        if (before === null) {
          resumed.resolve();
          await complete.promise;
        }
      }
      return route.fulfill({json: {items: pageRows, before: pageRows.length === 50 ? pageRows.at(-1).id : null}});
    });
    await page.goto(`${origin}/pets/${petId}`);
    await visible(page.getByText('시험 대화 1', {exact: true}));
    await page.waitForFunction(() => window.petChatStreams.length === 1);
    await page.evaluate(() => window.petChatStreams[0].dispatchEvent(new Event('error')));
    await visible(page.getByText('다시 연결하는 중이에요'));

    for (let number = 2; number <= 56; number++) rows.push(createRow(number));
    await page.getByLabel('콩이에게 할 말').fill('시험 대화 57');
    const ack = page.waitForResponse(response => response.status() === 201 && response.request().method() === 'POST');
    await page.getByRole('button', {name: '보내기'}).click();
    await ack;
    await page.waitForFunction(() => window.petChatStreams.length === 2);
    await page.evaluate(() => window.petChatStreams[1].dispatchEvent(new Event('open')));
    await resumed.promise;
    await page.evaluate(row => window.petChatStreams[1].dispatchEvent(
      new MessageEvent('message', {data: JSON.stringify(row)})), createRow(58));
    assert.equal(await page.getByText('시험 대화 58', {exact: true}).count(), 0);
    complete.resolve();
    await visible(page.getByText('시험 대화 58', {exact: true}));
    assert.deepEqual(fetched, [null, '8']);
    assert.equal(await page.getByText('다시 연결하는 중이에요').isVisible(), false);
    assert.deepEqual(await page.locator('.chat-log .bubble').evaluateAll(items => items.map(item =>
      item.querySelector('p')?.textContent || item.textContent)),
    Array.from({length: 58}, (_, index) => `시험 대화 ${index + 1}`));
  });

  test('SCR-147 keeps a draft through loss of network and repeated reloads', async t => {
    const {origin, writes} = await fixture(t);
    const context = await browser.newContext();
    t.after(() => context.close());
    const page = await context.newPage();
    await page.goto(`${origin}/pets/${petId}`);
    const entry = page.getByLabel('콩이에게 할 말');
    await entry.fill('남겨 둘 시험 초안');
    await context.setOffline(true);
    await visible(page.getByText('연결이 없어요. 연결되면 다시 불러올게요.'));
    assert.equal(await entry.isDisabled(), true);
    assert.equal(await page.getByRole('button', {name: '보내기'}).isDisabled(), true);
    await context.setOffline(false);
    await page.waitForFunction(() => document.querySelector('.composer textarea')?.disabled === false);
    assert.equal(await entry.inputValue(), '남겨 둘 시험 초안');
    await page.reload();
    assert.equal(await entry.inputValue(), '남겨 둘 시험 초안');
    assert.deepEqual(writes, []);
  });

  test('SCR-147 retries a failed send with the same client id and one retry prompt', async t => {
    const {origin} = await fixture(t);
    const context = await browser.newContext();
    t.after(() => context.close());
    const page = await context.newPage();
    const submitted = [];
    await page.route('**/api/pets/*/messages', async route => {
      if (route.request().method() !== 'POST') return route.continue();
      const data = route.request().postDataJSON();
      submitted.push(data);
      if (submitted.length < 3) return route.fulfill({status: 503, json: {code: 'server_error'}});
      return route.fulfill({status: 201, json: {...data, id: 'confirmed-message', role: 'member', kind: 'chat'}});
    });
    await page.goto(`${origin}/pets/${petId}`);
    await page.getByLabel('콩이에게 할 말').fill('같은 요청으로 다시 보내기');
    await page.getByRole('button', {name: '보내기'}).click();
    const retry = page.getByRole('button', {name: '다시 보내기'});
    await visible(retry);
    await page.evaluate(() => { window.sentBeforeOffline = true; });
    await context.setOffline(true);
    await page.waitForFunction(() => document.querySelector('.composer textarea').disabled);
    await context.setOffline(false);
    await page.waitForFunction(() => !document.querySelector('.composer textarea').disabled);
    assert.equal(await page.evaluate(() => window.sentBeforeOffline), true);
    await retry.click();
    await visible(retry);
    assert.equal(await page.getByText('보내지 못했어요', {exact: true}).count(), 1);
    const ack = page.waitForResponse(response => response.status() === 201 && response.request().method() === 'POST');
    await retry.click();
    await ack;
    assert.equal(submitted.length, 3);
    assert.equal(new Set(submitted.map(data => data.clientId)).size, 1);
    await visible(page.getByText('같은 요청으로 다시 보내기', {exact: true}));
    assert.equal(await page.getByText('보내지 못했어요', {exact: true}).count(), 0);
  });

  test('SCR-147 reconciles an accepted send recovered after its response was lost', async t => {
    const {origin} = await fixture(t);
    const context = await browser.newContext();
    t.after(() => context.close());
    const page = await context.newPage();
    await page.addInitScript(() => {
      window.chatStreams = [];
      window.EventSource = class extends EventTarget {
        constructor() { super(); window.chatStreams.push(this); }
        close() {}
      };
    });
    const greeting = {id: 'first', role: 'pet', kind: 'greeting', text: '처음 인사'};
    let saved = null;
    let sends = 0;
    await page.route('**/api/pets/*/messages', route => {
      if (route.request().method() === 'POST') {
        sends += 1;
        saved = {...route.request().postDataJSON(), id: 'accepted', role: 'member', kind: 'chat'};
        return route.abort('connectionreset');
      }
      return route.fulfill({json: {items: saved ? [saved, greeting] : [greeting], before: null}});
    });
    await page.goto(`${origin}/pets/${petId}`);
    const message = '서버에는 도착한 한 문장';
    await page.getByLabel('콩이에게 할 말').fill(message);
    await page.getByRole('button', {name: '보내기'}).click();
    const retry = page.getByRole('button', {name: '다시 보내기'});
    await visible(retry);
    await context.setOffline(true);
    await context.setOffline(false);
    await page.waitForFunction(() => window.chatStreams.length === 2);
    await page.evaluate(() => window.chatStreams[1].dispatchEvent(new Event('open')));
    await retry.waitFor({state: 'detached'});
    assert.equal(await page.getByText(message, {exact: true}).count(), 1);
    assert.equal(sends, 1);
  });

  test('SCR-147 shows the Korean call date and hour and keeps the transcript folded', async t => {
    const call = {id: 'synthetic-call-turn', role: 'member', kind: 'call',
      createdAt: '2026-11-17T15:10:00Z', text: '시험 통화 기록'};
    const {origin} = await fixture(t, {chatNotices: [call]});
    const page = await browser.newPage({timezoneId: 'America/Los_Angeles'});
    t.after(() => page.close());
    await page.goto(`${origin}/pets/${petId}`);
    const summary = page.getByText('통화했어요 · 11월 18일 오전 12시', {exact: true});
    const transcript = page.getByText(call.text, {exact: true});
    await visible(summary);
    assert.equal(await transcript.isVisible(), false);
    await summary.click();
    await visible(transcript);
  });

  test('SCR-148 at 390px: mic denial, disclosure, PCM, quota ending and return', async t => {
    const app = await fixture(t);
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    t.after(() => page.close());
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const route = '/pets/' + petId + '/call';
    let gateway;
    const micBlock = page.addInitScript(() => {
      const getMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia = opts => {
        if (!window.allowMic) return Promise.reject(new DOMException('denied', 'NotAllowedError'));
        return getMedia(opts).then(stream => {
          window.testTracks = stream.getTracks();
          return stream;
        });
      };
      const Worklet = window.AudioWorkletNode;
      window.callAudio = false;
      window.AudioWorkletNode = class extends Worklet {
        constructor(...args) {
          super(...args);
          if (args[1] === 'playback-pcm') this.port.addEventListener('message', event => {
            if (event.data.playedMs > 0) window.callAudio = true;
          });
        }
      };
    });
    await micBlock;
    let authenticate, capture;
    const auth = new Promise(resolve => { authenticate = resolve; });
    const pcm = new Promise(resolve => { capture = resolve; });
    await page.routeWebSocket('**/pet-call', ws => {
      gateway = ws;
      ws.onMessage(data => {
        if (typeof data === 'string') authenticate(JSON.parse(data));
        else capture(data.length);
      });
    });
    await page.goto(app.origin + route);
    await visible(page.getByText('통화는 1분마다 오늘 한도를 써요 · 지금 60%'));
    await page.getByRole('button', {name: '전화 걸기'}).click();
    await visible(page.getByText('마이크를 허용해야 통화할 수 있어요'));
    assert.equal(app.callStarts, 0);
    await page.evaluate(() => { window.allowMic = true; });
    await page.getByRole('button', {name: '다시 해 보기'}).click();
    assert.deepEqual(await auth, {type: 'auth', token: 'synthetic-call-token'});
    await visible(page.getByText('AI로 만든 목소리예요', {exact: true}));
    const packet = Buffer.alloc(24 + 4800);
    packet.write('MRG2');
    packet.writeUInt32BE(2400, 20);
    for (let i = 24; i < packet.length; i += 2) packet.writeInt16LE(1000, i);
    gateway.send(packet);
    gateway.send(JSON.stringify({type: 'audio_end', turn: 0, epoch: 0}));
    await page.waitForFunction(() => window.callAudio);
    gateway.send(JSON.stringify({type: 'ready'}));
    assert.equal(await pcm, 3200);
    assert.equal(await page.getByText(/지금 60%/).count(), 0);
    gateway.send(JSON.stringify({type: 'ending', reason: 'quota'}));
    await visible(page.getByText(/졸려서 자러 가요/));
    gateway.send(JSON.stringify({type: 'ended', reason: 'quota'}));
    await visible(page.getByText('통화했어요', {exact: true}));
    assert.equal(await page.evaluate(() => window.testTracks.every(track => track.readyState === 'ended')), true);
    assert.equal(await page.evaluate(() => document.body.scrollWidth <= innerWidth), true);
    await page.getByRole('link', {name: '대화로 돌아가기'}).click();
    await visible(page.getByText('누나, 나 왔어!', {exact: true}));
    assert.deepEqual(errors, []);
  });

  test('SCR-148 displays the contracted HTTP failures and frees the microphone', async t => {
    const cases = [
      {code: 'call_in_progress', status: 409, message: '이미 통화 중이에요.'},
      {code: 'call_unavailable', status: 503, message: '지금은 통화를 걸 수 없어요.', retry: true},
      {code: 'quota_exhausted', status: 409, prompt: 'brief', message: '오늘 한도를 다 썼어요. 새벽 4시에 다시 차요.'},
      {code: 'quota_exhausted', status: 409, prompt: 'recharge', message: '오늘 한도를 다 썼어요. 새벽 4시에 다시 차요.', recharge: true},
      {code: 'quota_exhausted', status: 409, prompt: 'none', mode: 'memorial', message: '오늘은 여기까지, 새벽 4시 뒤에 또 이야기해요.'},
      {code: 'budget_paused', status: 409, message: '오늘은 새 그림과 통화가 쉬어요. 글로는 계속 이야기할 수 있어요.'},
      {code: 'archived', status: 409, message: '보관한 아이예요. 꺼내면 다시 이야기할 수 있어요.'},
      {code: 'consent_required', status: 409, message: '사진과 대화를 해외 AI 회사로 보내는 데 동의해야 쓸 수 있어요. 설정에서 바꿀 수 있어요.'},
    ];
    const page = await browser.newPage({viewport: {width: 360, height: 800}});
    t.after(() => page.close());
    await page.addInitScript(() => {
      const getMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia = async options => {
        const stream = await getMedia(options);
        window.callTracks = stream.getTracks();
        return stream;
      };
    });
    for (const example of cases) {
      const app = await fixture(t, {closetMode: example.mode || 'living'});
      let reservations = 0;
      let sockets = 0;
      const reject = route => {
        reservations += 1;
        return route.fulfill({status: example.status,
          json: {code: example.code, detail: example.message, prompt: example.prompt}});
      };
      await page.route('**/api/pets/*/calls', reject);
      await page.routeWebSocket('**/pet-call', () => { sockets += 1; });
      await page.goto(`${app.origin}/pets/${petId}/call`);
      await page.getByRole('button', {name: '전화 걸기'}).click();
      const dialog = page.getByRole('dialog', {name: '충전권'});
      const status = example.recharge ? dialog : page.locator('.call-card');
      await visible(status.getByText(example.message, {exact: true}));
      assert.equal(reservations, 1, example.code);
      assert.equal(sockets, 0, example.code);
      assert.equal(await page.evaluate(() => window.callTracks.every(track => track.readyState === 'ended')), true, example.code);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, example.code);
      assert.equal(await dialog.count(), Number(Boolean(example.recharge)), example.code);
      if (example.retry) await visible(page.getByRole('button', {name: '다시 해 보기'}));
      await page.unroute('**/api/pets/*/calls', reject);
    }
  });

  test('SCR-148 blocks direct call entry for archived pets and missing consent', async t => {
    const page = await browser.newPage({viewport: {width: 430, height: 850}});
    t.after(() => page.close());
    await page.addInitScript(() => {
      window.micRequests = 0;
      navigator.mediaDevices.getUserMedia = () => {
        window.micRequests += 1;
        return Promise.reject(new Error('permission should never be requested'));
      };
    });
    const archived = await fixture(t, {closetMode: 'archived'});
    await page.goto(`${archived.origin}/pets/${petId}/call`);
    await visible(page.getByText('보관한 아이예요. 꺼내면 다시 이야기할 수 있어요.'));
    assert.equal(await page.getByRole('link', {name: '돌아가기', exact: true}).getAttribute('href'), '/pets/' + petId);
    assert.equal(await page.getByRole('button', {name: '전화 걸기'}).count(), 0);
    assert.equal(await page.evaluate(() => window.micRequests), 0);
    assert.equal(archived.callStarts, 0);

    const consentMissing = await fixture(t, {consent: false});
    await page.goto(`${consentMissing.origin}/pets/${petId}/call`);
    assert.equal(await page.getByRole('link', {name: '설정에서 바꾸기'}).getAttribute('href'), '/me#consents');
    assert.equal(await page.getByRole('button', {name: '전화 걸기'}).count(), 0);
    assert.equal(await page.evaluate(() => window.micRequests), 0);
    assert.equal(consentMissing.callStarts, 0);
  });

  test('SCR-148 releases the interrupted call and reconnects on an explicit retry', {timeout: 15_000}, async t => {
    const app = await fixture(t);
    const page = await browser.newPage({viewport: {width: 430, height: 850}});
    t.after(() => page.close());
    await page.addInitScript(() => {
      const getMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      window.callTracks = [];
      navigator.mediaDevices.getUserMedia = async options => {
        const stream = await getMedia(options);
        window.callTracks.push(...stream.getTracks());
        return stream;
      };
    });
    let connections = 0;
    const receivedStop = Promise.withResolvers();
    await page.routeWebSocket('**/pet-call', gateway => {
      const call = ++connections;
      gateway.onMessage(data => {
        if (typeof data !== 'string') return;
        const control = JSON.parse(data);
        if (control.type === 'auth') {
          if (call === 1) gateway.close({code: 1011});
          else gateway.send(JSON.stringify({type: 'ready'}));
        }
        if (control.type === 'stop') receivedStop.resolve();
      });
    });
    await page.goto(`${app.origin}/pets/${petId}/call`);
    await page.getByRole('button', {name: '전화 걸기'}).click();
    await visible(page.getByText('연결이 끊겼어요'));
    assert.deepEqual(await page.evaluate(() => window.callTracks.map(track => track.readyState)), ['ended']);
    await page.getByRole('button', {name: '다시 걸기'}).click();
    await page.waitForFunction(() => window.callTracks.length === 2 && window.callTracks.at(-1).readyState === 'live');
    await page.locator('.call-card [role=status]').getByText('연결하고 있어요').waitFor({state: 'detached'});
    await page.getByRole('button', {name: '끊기'}).click();
    await visible(page.getByText('통화했어요', {exact: true}));
    await receivedStop.promise;
    assert.equal(app.callStarts, 2);
    assert.equal(connections, 2);
    assert.deepEqual(await page.evaluate(() => window.callTracks.map(track => track.readyState)), ['ended', 'ended']);
  });

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

  test('SCR-143 saves the changed field, waits for its receipt, and refreshes a stale tab', async t => {
    const hold = Promise.withResolvers();
    t.after(hold.resolve);
    const {origin, writes} = await fixture(t, {creationState: 'traits',
      holdTraits: data => data.breedGuess === '믹스' ? hold.promise : undefined});
    const context = await browser.newContext({viewport: {width: 360, height: 820}});
    t.after(() => context.close());
    const [first, stale] = await Promise.all([context.newPage(), context.newPage()]);
    const documentUrl = `${origin}/create/${creationId}/traits`;
    const apiUrl = `${origin}/api/creations/${creationId}`;
    await Promise.all([first.goto(documentUrl), stale.goto(documentUrl)]);
    const breed = first.getByLabel('품종 추정');
    await breed.fill('거절 입력');
    await breed.blur();
    const breedStatus = first.locator('label:has([name=breedGuess]) + div');
    await visible(breedStatus.getByText('입력을 확인해 주세요.'));
    await breed.fill('믹스');
    await breed.blur();
    await visible(breedStatus.locator('xpath=self::*[@aria-busy="true"]'));
    const confirm = first.getByRole('button', {name: '이대로 만들기'});
    await confirm.click();
    assert.equal(await confirm.isDisabled(), true);
    assert.deepEqual(writes, [{breedGuess: '거절 입력'}, {breedGuess: '믹스'}]);

    await stale.request.patch(apiUrl + '/traits', {data: {patternNotes: '다른 탭에서 고친 메모'}});
    hold.resolve();
    await visible(first.getByRole('heading', {name: '미리 보기와 결제'}));
    const fromApi = await (await first.request.get(apiUrl)).json();
    assert.equal(fromApi.traits.breedGuess, '믹스');
    assert.equal(fromApi.traits.patternNotes, '다른 탭에서 고친 메모');
    assert.deepEqual(writes.slice(2), [{patternNotes: '다른 탭에서 고친 메모'}, {}]);

    const lateEdit = stale.getByLabel('품종 추정');
    await lateEdit.fill('늦게 고친 값');
    await lateEdit.blur();
    await stale.waitForURL('**/preview');
    await visible(stale.getByText('화면을 새로 고쳤어요.'));
    assert.equal((await (await stale.request.get(apiUrl)).json()).traits.breedGuess, '믹스');
  });

  test('SCR-144 uses the approved limit and consent states and disables drawing', async t => {
    const {origin} = await fixture(t, {creationState: 'traits_confirmed'});
    const cases = [
      [429, 'preview_limit', '오늘 미리 보기를 다 봤어요. 새벽 4시 뒤에 다시 볼 수 있어요.'],
      [409, 'budget_paused', '오늘은 새 그림과 통화가 쉬어요. 글로는 계속 이야기할 수 있어요.'],
      [409, 'consent_required', '사진과 대화를 해외 AI 회사로 보내는 데 동의해야 쓸 수 있어요. 설정에서 바꿀 수 있어요.'],
    ];
    for (const [status, code, detail] of cases) {
      const page = await browser.newPage();
      try {
        await page.route('**/api/creations/*/preview', route => route.fulfill({status, json: {code, detail}}));
        await page.goto(`${origin}/create/${creationId}/preview`);
        const draw = page.getByRole('button', {name: '미리 보기 그리기'});
        await draw.click();
        await visible(page.getByText(detail, {exact: true}));
        assert.equal(await draw.isDisabled(), true);
        if (code === 'consent_required') await visible(page.getByRole('link', {name: '설정에서 바꾸기'}));
      } finally {
        await page.close();
      }
    }
  });

  test('SCR-145 refreshes the chosen picture when another tab has already picked it', async t => {
    const {origin, writes} = await fixture(t, {creationState: 'candidates', chooseBusy: true});
    const page = await browser.newPage();
    t.after(() => page.close());
    await page.goto(`${origin}/create/${creationId}/candidates`);
    await page.getByRole('radio', {name: 'AI가 그린 후보 AI가 그린 그림'}).check();
    await page.getByRole('button', {name: '이 그림으로 할게요'}).click();
    await visible(page.getByText('표정을 그리고 있어요. 다 되면 이름을 지어 줘요'));
    await visible(page.getByText('화면을 새로 고쳤어요.'));
    assert.deepEqual(writes, [{candidateId}]);
  });

  test('SCR-146 keeps the draft across reloads and shows progress until naming succeeds', async t => {
    const finish = Promise.withResolvers();
    t.after(finish.resolve);
    const {origin, writes} = await fixture(t, {creationState: 'sheet_ready', holdFinish: () => finish.promise});
    const page = await browser.newPage({viewport: {width: 430, height: 820}});
    t.after(() => page.close());
    await page.goto(`${origin}/create/${creationId}/name`);
    const name = page.getByLabel('이름', {exact: true});
    const callMe = page.getByLabel('나를 부르는 말');
    await name.fill('도토리');
    await callMe.fill('누나');
    await page.getByRole('checkbox', {name: '느긋함'}).check();
    for (let index = 0; index < 2; index++) {
      await page.reload();
      await visible(name);
      assert.equal(await name.inputValue(), '도토리');
      assert.equal(await callMe.inputValue(), '누나');
      assert.equal(await page.getByRole('checkbox', {name: '느긋함'}).isChecked(), true);
    }
    const submit = page.getByRole('button', {name: '만나러 가기'});
    await submit.click();
    await visible(page.getByText('첫 인사를 준비하고 있어요'));
    assert.equal(await submit.isDisabled(), true);
    finish.resolve();
    await page.waitForURL(`**/pets/${petId}`);
    await visible(page.getByText('누나, 나 왔어!'));
    assert.equal(await page.evaluate(key => sessionStorage.getItem(key), `pet:profile:${creationId}`), null);
    assert.deepEqual(writes[0].intro.personality, ['느긋함']);
  });

  test('SCR-142 encodes photo fallback locally at 1600px JPEG 0.9 and explains unsupported HEIC', async t => {
    const {origin} = await fixture(t);
    const page = await browser.newPage();
    t.after(() => page.close());
    await page.addInitScript(() => {
      window.createImageBitmap = async () => { throw new Error('fixture fallback'); };
      const encode = HTMLCanvasElement.prototype.toBlob;
      HTMLCanvasElement.prototype.toBlob = function (callback, mime, quality) {
        if (mime === 'image/jpeg') window.photoEncoding = [this.width, this.height, mime, quality];
        return encode.call(this, callback, mime, quality);
      };
    });
    await page.goto(origin + '/create');
    const source = await page.evaluate(() => {
      const canvas = document.createElement('canvas');
      canvas.width = 2000;
      canvas.height = 1000;
      return canvas.toDataURL('image/png').split(',')[1];
    });
    await page.getByLabel('정면 얼굴', {exact: true}).setInputFiles({
      name: 'synthetic.png', mimeType: 'image/png', buffer: Buffer.from(source, 'base64'),
    });
    await visible(page.getByRole('img', {name: '정면 얼굴'}));
    assert.deepEqual(await page.evaluate(() => window.photoEncoding), [1600, 800, 'image/jpeg', .9]);
    await page.getByLabel('귀와 무늬', {exact: true}).setInputFiles({
      name: 'unreadable.heic', mimeType: 'image/heic', buffer: Buffer.from('synthetic unsupported HEIC'),
    });
    await visible(page.getByText('사진 앱에서 JPEG로 저장해 주세요'));
  });

  test('SCR-145/159 enables Web Push on click and removes the current device registration', async t => {
    const applicationKey = Buffer.alloc(65, 1);
    applicationKey[0] = 4;
    const {origin, writes} = await fixture(t, {creationState: 'paid', pushKey: applicationKey.toString('base64url')});
    const page = await browser.newPage();
    t.after(() => page.close());
    const parameters = {endpoint: 'https://fcm.googleapis.com/fcm/send/pet-test',
      keys: {p256dh: 'synthetic-device-public-key', auth: 'synthetic-auth'}};
    await page.addInitScript(device => {
      window.pushActions = [];
      const subscription = {
        toJSON: () => ({...device, expirationTime: null}),
        unsubscribe: async () => { sessionStorage.removeItem('test-push'); window.pushActions.push('removed'); },
      };
      const manager = {
        getSubscription: async () => sessionStorage.getItem('test-push') ? subscription : null,
        subscribe: async options => {
          window.pushActions.push([options.userVisibleOnly, ...options.applicationServerKey]);
          if (document.URL.endsWith('#denied')) throw new DOMException('Fixture denial', 'NotAllowedError');
          if (document.URL.endsWith('#broken')) throw new DOMException('Fixture service failure', 'AbortError');
          sessionStorage.setItem('test-push', 'yes');
          return subscription;
        },
      };
      Object.defineProperty(navigator, 'serviceWorker', {value: {
        register: async () => {}, ready: Promise.resolve({pushManager: manager}),
      }});
      Object.defineProperty(window, 'PushManager', {value: function () {}});
      Object.defineProperty(Notification, 'permission', {value: 'default'});
    }, parameters);
    await page.goto(`${origin}/create/${creationId}/candidates#denied`);
    const subscribe = page.getByRole('button', {name: '다 그리면 알려 드릴까요?'});
    await visible(subscribe);
    assert.deepEqual(await page.evaluate(() => window.pushActions), []);
    await subscribe.click();
    await visible(page.getByText('알림을 끄셨어요. 이 화면을 다시 열면 볼 수 있어요'));
    assert.deepEqual(writes, []);
    await page.evaluate(() => history.replaceState(null, '', location.pathname + '#broken'));
    await subscribe.click();
    await visible(page.getByText('잠시 뒤 다시 해 주세요.'));
    assert.deepEqual(writes, []);
    await page.evaluate(() => history.replaceState(null, '', location.pathname));
    await subscribe.click();
    await visible(page.getByText('알려 드릴게요'));
    assert.deepEqual(writes, [parameters]);
    assert.deepEqual(await page.evaluate(() => window.pushActions[2]), [true, ...applicationKey]);
    await page.goto(origin + '/me');
    await page.getByRole('button', {name: '알림 끄기'}).click();
    await visible(page.getByRole('button', {name: '알림 켜기'}));
    assert.deepEqual(writes, [parameters, 'remove-push']);
    assert.deepEqual(await page.evaluate(() => window.pushActions), ['removed']);
  });

  test('SCR-159 shows installation instructions in an iPhone browser tab', async t => {
    const {origin, writes} = await fixture(t);
    const page = await browser.newPage({userAgent: 'Mozilla/5.0 (iPhone) Safari/605.1.15'});
    t.after(() => page.close());
    await page.goto(origin + '/me');
    await visible(page.getByText('홈 화면에 추가하면 알림을 받을 수 있어요'));
    assert.equal(await page.getByRole('button', {name: '알림 켜기'}).count(), 0);
    assert.deepEqual(writes, []);
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

  test('SCR-150 uses the saved composition and only navigates to visible dates', async t => {
    const {origin} = await fixture(t, {diaryDays: true});
    const page = await browser.newPage({viewport: {width: 430, height: 790}});
    t.after(() => page.close());
    await page.goto(`${origin}/pets/${petId}/diary/2026-11-17`);
    await visible(page.getByRole('heading', {name: '산책 간 날'}));
    await visible(page.getByText('AI가 그린 그림'));
    const frame = page.locator('.diary-art-frame');
    assert.equal(await frame.locator('.outfit-background').getAttribute('src'), '/static/backgrounds/park.webp');
    assert.equal(await frame.locator('img[alt="콩이"]').getAttribute('src'), '/static/pet-welcome.webp');
    assert.equal(await frame.locator('[data-slot="head"]').getAttribute('src'), `/api/items/${garmentId}/layer?template=dog_small`);
    await frame.locator('.outfit-stage[data-aligned="true"]').waitFor();
    const positions = await frame.locator('.outfit-layer').evaluateAll(layers => layers.map(layer => {
      const {left, top, width, height} = layer.getBoundingClientRect();
      return [left, top, width, height];
    }));
    assert.deepEqual(positions[0], positions[1]);
    assert(await page.getByRole('button', {name: '뒷 날'}).isDisabled());
    await page.getByRole('link', {name: '앞 날'}).click();
    await visible(page.getByRole('heading', {name: '지난 일기'}));
    assert(await page.getByRole('button', {name: '앞 날'}).isDisabled());
    await page.getByRole('link', {name: '뒷 날'}).click();
    await visible(page.getByRole('heading', {name: '산책 간 날'}));
  });

  test('SCR-150 previews owned decor, asks before paid use and saves a moved sticker', async t => {
    const {origin, writes} = await fixture(t, {diaryDecor: true});
    const page = await browser.newPage({viewport: {width: 360, height: 790}});
    t.after(() => page.close());
    await page.goto(`${origin}/pets/${petId}/diary/2026-11-17`);
    const decorate = page.getByRole('button', {name: '꾸미기'});
    const pick = page.getByRole('button', {name: '군밤 테마'});
    const confirm = page.getByRole('dialog');
    const paper = page.locator('.diary-paper');
    await decorate.click();
    await pick.click();
    await visible(confirm.getByText('이 테마를 쓰면 청약철회할 수 없어요. 쓸까요?'));
    await confirm.getByRole('button', {name: '아니요'}).click();
    assert.equal(await paper.evaluate(node => node.style.backgroundImage), '');
    await pick.click();
    await confirm.getByRole('button', {name: '쓸게요'}).click();
    await page.waitForFunction(id => document.querySelector('.diary-paper').style.backgroundImage.includes(id), themeId);
    await page.getByRole('button', {name: '취소'}).click();
    await visible(decorate);
    assert.equal(await paper.evaluate(node => node.style.backgroundImage), '');
    assert.deepEqual(writes, []);
    await decorate.click();
    await pick.click();
    await confirm.getByRole('button', {name: '쓸게요'}).click();
    await page.getByRole('button', {name: '스티커', exact: true}).click();
    await page.getByRole('button', {name: '별 스티커'}).click();
    const marker = page.getByRole('button', {name: '스티커 1'});
    await marker.press('ArrowRight');
    await page.getByRole('button', {name: '저장', exact: true}).click();
    await visible(decorate);
    assert.deepEqual(writes, [{themeId, fontId: null}, [
      {packId: stickerPackId, sticker: 'star-small', x: .52, y: .5, scale: 1, rotate: 0},
    ]]);
    await page.reload();
    await visible(decorate);
    assert.match(await paper.evaluate(node => node.style.backgroundImage), new RegExp(themeId));
    assert.equal(await page.locator('.diary-stickers img').count(), 1);
    assert.equal(await page.evaluate(() => document.body.scrollWidth <= innerWidth), true);
  });

  test('SCR-160 shows quota, disabled payments, price consent and two-step cancellation', async t => {
    const page = await browser.newPage({viewport: {width: 360, height: 790}});
    t.after(() => page.close());
    const free = await fixture(t);
    await page.goto(free.origin + '/me/plan');
    await visible(page.getByText('60% · 새벽 4시에 다시 차요'));
    await visible(page.getByText('결제는 곧 열려요.'));
    assert(await page.getByRole('button', {name: '구독하기'}).isDisabled());
    assert(await page.getByRole('button', {name: '절반 채우기'}).isDisabled());
    assert.deepEqual(free.writes, []);
    const subscription = {status: 'active', priceKrw: 9900, periodEnd: '2026-12-17T00:00:00Z',
      nextChargeAt: '2026-12-17T00:00:00Z', newPrice: {priceKrw: 10900, from: '2026-12-20', agreed: false}};
    const active = await fixture(t, {subscription, paymentsEnabled: true});
    await page.goto(active.origin + '/me/plan');
    await visible(page.getByText('구독 중 · 다음 결제 12월 17일 · 9,900원'));
    await visible(page.getByText(/12월 20일부터 월 10,900원으로 바뀌어요/));
    await page.getByRole('button', {name: '동의하기'}).click();
    await visible(page.getByText('동의했어요'));
    await page.getByRole('button', {name: '해지하기'}).click();
    const dialog = page.getByRole('dialog');
    await visible(dialog.getByRole('heading', {name: '구독 해지'}));
    assert.deepEqual(active.writes, ['price-consent']);
    await dialog.getByRole('button', {name: '해지하기'}).click();
    await dialog.waitFor({state: 'hidden'});
    await visible(page.getByText('12월 17일까지 하루 한도 2배예요. 그 뒤 끝나요.'));
    assert.equal(await page.getByRole('button', {name: '해지하기'}).count(), 0);
    assert.deepEqual(active.writes, ['price-consent', 'cancel']);
    assert.equal(await page.evaluate(() => document.body.scrollWidth <= innerWidth), true);
  });

  test('SCR-155 opens from the quota row and only the first exhausted redraw opens it automatically', async t => {
    const {origin} = await fixture(t, {exhaustedRedraw: true});
    const page = await browser.newPage({viewport: {width: 360, height: 790}});
    t.after(() => page.close());
    await page.goto(`${origin}/pets/${petId}#recharge`);
    const recharge = page.getByRole('dialog', {name: '충전권'});
    assert.equal(await recharge.count(), 0);
    await page.getByRole('button', {name: '충전하기'}).click();
    await visible(recharge.getByText('오늘 한도 60% · 새벽 4시에 다시 차요'));
    assert(await recharge.getByRole('button', {name: '절반 채우기 · 1,500원'}).isDisabled());
    await recharge.getByRole('button', {name: '괜찮아요'}).click();
    await page.goto(`${origin}/pets/${petId}/diary/2026-11-17`);
    const redraw = page.getByRole('button', {name: /새 그림으로 다시 그리기/});
    await redraw.click();
    await page.getByRole('dialog').getByRole('button', {name: '그리기 · 2번 남음'}).click();
    await visible(recharge.getByText('오늘 한도를 다 썼어요. 새벽 4시에 다시 차요.'));
    await recharge.getByRole('button', {name: '괜찮아요'}).click();
    await redraw.click();
    const paint = page.getByRole('dialog');
    await paint.getByRole('button', {name: '그리기 · 2번 남음'}).click();
    await visible(paint.getByText('오늘 한도를 다 썼어요.'));
    assert.equal(await recharge.count(), 0);
    const memorial = await fixture(t, {closetMode: 'memorial'});
    await page.goto(`${memorial.origin}/pets/${petId}#recharge`);
    await visible(page.getByRole('heading', {name: '콩이'}));
    assert.equal(await page.getByRole('button', {name: '충전하기'}).count(), 0);
    assert.equal(await recharge.count(), 0);
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

  test('SCR-161 reads the current order and updates only after the API confirms withdrawal', async t => {
    const {origin} = await fixture(t);
    const page = await browser.newPage({viewport: {width: 360, height: 760}});
    t.after(() => page.close());
    await page.goto(origin + '/me/orders');
    await visible(page.getByText('1,200원'));
    await page.getByRole('button', {name: '청약철회'}).click();
    await page.getByRole('dialog').getByRole('button', {name: '청약철회'}).click();
    await visible(page.getByText('결제를 취소했어요', {exact: true}));
    await visible(page.getByText(/환불됨/));
  });

  test('SCR-162 handles completed, preconfirmed, and canceled payment returns', async t => {
    for (const payment of ['fulfilled', 'already', 'canceled']) {
      const {origin, writes} = await fixture(t, {payment});
      const page = await browser.newPage({viewport: {width: 430, height: 760}});
      try {
        const query = payment === 'canceled' ? 'canceled=1' : `orderId=${orderId}&amount=1200&paymentKey=fixture`;
        await page.goto(origin + '/pay/return?' + query);
        await visible(page.getByText(payment === 'canceled' ? '결제를 취소했어요.' : '결제했어요', {exact: true}));
        assert.equal(new URL(page.url()).search, '');
        assert.deepEqual(writes, payment === 'canceled' ? [] : [{paymentKey: 'fixture', amount: 1200}]);
      } finally { await page.close(); }
    }
  });

  test('SCR-153–154 confirms memorial mode, creates a farewell page, and protects deletion', async t => {
    const {origin, writes} = await fixture(t);
    const page = await browser.newPage({viewport: {width: 360, height: 780}});
    t.after(() => page.close());
    await page.goto(origin + '/pets/' + petId + '/settings');
    await page.getByRole('button', {name: '아이 지우기'}).click();
    const dialog = page.getByRole('dialog');
    assert.equal(await dialog.getByRole('button', {name: '지우기', exact: true}).isDisabled(), true);
    await dialog.getByLabel('아이 이름').fill('콩이');
    assert.equal(await dialog.getByRole('button', {name: '지우기', exact: true}).isEnabled(), true);
    await dialog.getByRole('button', {name: '아니에요'}).click();
    await page.getByRole('button', {name: '무지개다리를 건넜어요'}).click();
    await visible(dialog.getByText('7일 안에 되돌릴 수 있어요'));
    await dialog.getByRole('button', {name: '추억 모드로 바꾸기'}).click();
    await page.getByRole('link', {name: '작별 의식'}).click();
    await page.getByLabel('마지막 편지 받기').check();
    await page.getByRole('button', {name: '시작하기'}).click();
    await visible(page.getByText('같이 산책한 날이 정말 좋았어.'));
    assert.equal(await page.getByRole('link', {name: '일기장 마지막 장에 남겼어요'}).getAttribute('href'),
      '/pets/' + petId + '/diary/2026-11-17');
    assert.deepEqual(writes, [{mode: 'memorial'}, {kind: 'letter'}]);
  });

  test('SCR-153 resets stale mode actions from the current server state', async t => {
    const {origin} = await fixture(t);
    const page = await browser.newPage({viewport: {width: 360, height: 800}});
    t.after(() => page.close());
    const future = new Date(Date.now() + 86_400_000).toISOString();
    const past = new Date(Date.now() - 86_400_000).toISOString();
    for (const example of [
      {mode: 'living', trigger: '무지개다리를 건넜어요', confirm: '추억 모드로 바꾸기',
        endpoint: 'mode', code: 'archived', next: {mode: 'memorial', status: 'archived'},
        notice: '화면을 새로 고쳤어요.', available: '꺼내기'},
      {mode: 'memorial', trigger: /함께 사는 아이로 되돌리기 ·/, confirm: '함께 사는 아이로 되돌리기',
        endpoint: 'mode', code: 'revert_window_passed', next: {mode: 'memorial', revertUntil: past},
        notice: '추억 모드로 바꾼 지 7일이 지나 되돌릴 수 없어요.', available: '보관하기'},
      {mode: 'memorial', trigger: '보관하기', confirm: '보관하기',
        endpoint: 'archive', code: 'not_memorial', next: {mode: 'living'},
        notice: '함께 사는 아이는 보관하지 않아요.', available: '무지개다리를 건넜어요'},
    ]) {
      let state = {...pet, mode: example.mode, revertUntil: future};
      let reads = 0;
      const petRoute = `**/api/pets/${petId}`;
      const actionRoute = `${petRoute}/${example.endpoint}`;
      const read = route => { reads += 1; return route.fulfill({json: state}); };
      const refuse = route => {
        state = {...state, ...example.next};
        return route.fulfill({status: 409, json: {code: example.code}});
      };
      await page.route(petRoute, read);
      await page.route(actionRoute, refuse);
      await page.goto(`${origin}/pets/${petId}/settings`);
      await page.getByRole('button', {name: example.trigger, exact: typeof example.trigger === 'string'}).click();
      await page.getByRole('dialog').getByRole('button', {name: example.confirm, exact: true}).click();
      await visible(page.getByText(example.notice, {exact: true}));
      await visible(page.getByRole('button', {name: example.available, exact: true}));
      assert.equal(await page.getByRole('button', {name: example.trigger}).count(), 0);
      assert.equal(reads, 2, example.code);
      await page.unroute(actionRoute, refuse);
      await page.unroute(petRoute, read);
    }
  });

  test('SCR-153 keeps the export ID through polling and exposes the authorized download route', async t => {
    const {origin} = await fixture(t);
    const page = await browser.newPage({viewport: {width: 430, height: 780}});
    t.after(() => page.close());
    await page.goto(origin + '/pets/' + petId + '/settings');
    await page.getByRole('button', {name: '기록 내보내기'}).click();
    await visible(page.getByText('만들고 있어요', {exact: true}));
    const download = page.getByRole('link', {name: /^받기 · /});
    await visible(download);
    assert.equal(await download.getAttribute('href'), '/api/exports/' + orderId + '/download');
  });

  test('SCR-152 at 360px: withdrawal notice, equip, take off and slots', async t => {
    const {origin, writes} = await fixture(t, {closetMode: 'living'});
    const page = await browser.newPage({viewport: {width: 360, height: 780}});
    t.after(() => page.close());
    await page.goto(origin + '/pets/' + petId + '/closet');
    await page.getByRole('button', {name: '털모자', exact: true}).click();
    const dialog = page.getByRole('dialog');
    await visible(dialog.getByText(/철회할 수 없어요/));
    await dialog.getByRole('button', {name: '아니요'}).click();
    assert.deepEqual(writes, []);
    await page.getByRole('button', {name: '털모자', exact: true}).click();
    await dialog.getByRole('button', {name: '입히기', exact: true}).click();
    const worn = page.getByRole('button', {name: '✓ 털모자', exact: true});
    await visible(worn);
    assert.match(await page.locator('[data-slot="head"]').getAttribute('src'), /layer\?template=dog_small$/);
    await worn.click();
    await visible(page.getByRole('button', {name: '털모자', exact: true}));
    assert.deepEqual(writes, [{head: garmentId, body: null, neck: null}, {head: null, body: null, neck: null}]);
    await page.getByRole('button', {name: '몸', exact: true}).click();
    await visible(page.getByText('이 자리에 입힐 아이템이 없어요.'));
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 360);
  });

  test('SCR-152 restores the outfit on a wrong-slot response and hides shopping for a memorial pet', async t => {
    const {origin, writes} = await fixture(t, {closetMode: 'memorial', outfitFailure: true});
    const page = await browser.newPage({viewport: {width: 430, height: 780}});
    t.after(() => page.close());
    await page.goto(origin + '/pets/' + petId + '/closet');
    await page.getByRole('button', {name: '털모자', exact: true}).click();
    await page.getByRole('dialog').getByRole('button', {name: '입히기', exact: true}).click();
    await visible(page.getByText('입힐 수 없어요', {exact: true}));
    assert.equal(await page.locator('[data-slot="head"]').count(), 0);
    assert.match(await page.locator('.outfit-background').getAttribute('src'), /rainbow_meadow\.webp$/);
    assert.equal(await page.getByRole('link', {name: '상점에서 더 보기'}).count(), 0);
    assert.equal(writes.length, 1);
    await page.goto(origin + '/shop');
    await visible(page.getByText('함께 사는 아이가 있을 때 열려요.'));
  });

  test('SCR-157/158 at 430px: catalog, read-only try-on failure and payment-off state', async t => {
    const {origin, writes} = await fixture(t, {closetMode: 'living', layerFailure: true});
    const page = await browser.newPage({viewport: {width: 430, height: 800}});
    t.after(() => page.close());
    await page.goto(origin + '/shop');
    await visible(page.getByText('결제는 곧 열려요.'));
    await page.getByRole('button', {name: '스티커', exact: true}).click();
    await visible(page.getByText('지금은 팔고 있는 것이 없어요.'));
    await page.getByRole('button', {name: '착용', exact: true}).click();
    await page.getByRole('link', {name: /털모자/}).click();
    await visible(page.getByText('입혀 보기를 불러오지 못했어요'));
    await visible(page.getByText('1,200원(부가세 포함)', {exact: true}));
    assert.equal(await page.getByRole('button', {name: '사기'}).isDisabled(), true);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 430);
    assert.deepEqual(writes, []);
  });

  test('SCR-158 keeps its order key on retry and updates ownership only after fulfillment', async t => {
    const {origin, writes} = await fixture(t, {closetMode: 'living', paymentsEnabled: true, orderRetry: true});
    const page = await browser.newPage({viewport: {width: 360, height: 780}});
    t.after(() => page.close());
    await page.goto(origin + '/shop/' + garmentId);
    await page.getByRole('button', {name: '사기'}).click();
    const dialog = page.getByRole('dialog');
    await visible(dialog.getByText('1,200원, 부가세 포함', {exact: true}));
    await visible(dialog.getByText(/산 지 7일 안이고/));
    await dialog.getByRole('button', {name: '결제하기'}).click();
    await visible(dialog.getByText('잠시 뒤 다시 해 주세요.'));
    await dialog.getByRole('button', {name: '결제하기'}).click();
    await visible(page.getByText('가지고 있어요', {exact: true}));
    assert.equal(writes.length, 2);
    assert.deepEqual(writes[0], writes[1]);
    assert.equal(writes[1].itemId, garmentId);
    assert.match(writes[1].idempotencyKey, /^[\da-f-]{36}$/i);
  });
}
