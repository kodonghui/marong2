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
  closetMode, paymentsEnabled = false, layerFailure = false, outfitFailure = false, orderRetry = false} = {}) {
  let member = signedIn;
  let state;
  let selected = null;
  let memberPet = {...pet, intro: {personality: ['느긋함'], likes: '산책', dislikes: '', callMe: '누나'}};
  if (closetMode) memberPet = {...memberPet, mode: closetMode === 'memorial' ? 'memorial' : 'living',
    status: closetMode === 'archived' ? 'archived' : 'active', shopEntry: closetMode === 'living',
    template: 'dog_small', outfit: {head: null, body: null, neck: null}};
  let needsConfirmation = true;
  let ownsGarment = false;
  const writes = [];
  let callStarts = 0;
  const order = {id: orderId, orderNo: 'P20261117-ABC123', product: 'item', itemName: '털모자',
    amountKrw: 1200, vatKrw: 109, status: 'fulfilled', createdAt: '2026-11-17T06:40:00Z',
    withdrawable: true, withdrawalNote: '한 번 입히면 철회할 수 없어요.'};
  function job() {
    const preview = ['previewed', 'paid', 'candidates', 'chosen', 'sheet_ready', 'done'].includes(state);
    return {id: creationId, state, kind: 'living', traits, multiplePets: false,
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
    if (pathname === '/api/signup' && req.method === 'POST') {
      const data = JSON.parse(await body(req));
      writes.push(data);
      if (invite && !data.inviteCode) return json(res, {code: 'invite_required', detail: '지금은 초대받은 분만 가입할 수 있어요.'}, 403);
      member = true;
      return json(res, {}, 201);
    }
    if (pathname === '/api/me/quota') return json(res, {percent: 60});
    if (pathname === '/api/pets') return json(res, {items: state === 'done' ? [pet] : closetMode ? [memberPet] : []});
    if (pathname === '/api/me/inventory') return json(res, {items: [{itemId: garmentId, kind: 'wear', name: '털모자',
      slot: 'head', source: 'order', wornBy: [], contents: [],
      withdrawableUntil: needsConfirmation ? '2026-12-17T00:00:00Z' : null}]});
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
    if (pathname === `/api/pets/${petId}/messages`) return json(res, {items: [{
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
    if (pathname === `/static/items/${garmentId}/thumb.webp` || pathname.startsWith('/static/backgrounds/')) {
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
