"""Private Gemini Live relay; no application-imposed call duration/count limit."""
from __future__ import annotations
import asyncio, base64, hashlib, hmac, json, os, re, secrets, time
from collections import deque
from pathlib import Path
from aiohttp import ClientError, ClientSession, ClientTimeout, WSMsgType, web
from google.oauth2 import service_account
from google.auth.transport.requests import Request
import jwt

HERE=Path(__file__).resolve().parent
ROOT=Path.home()/'marong-vertex-test'
CONFIG=Path.home()/'.config/marong-call'
PROJECT='project-bc2d15a4-11c0-476b-ae8'
LOCATION='us-central1'
MODEL='gemini-3.8-live'
VOICE='Sulafat'
AUTH_MODE=os.environ.get('VERTEX_AUTH_MODE','api_key')
ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
JOIN_FILE=ROOT/'join-token'
if not JOIN_FILE.exists():
    fd=os.open(JOIN_FILE,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:f.write(secrets.token_urlsafe(24))
JOIN=JOIN_FILE.read_text().strip()
COOKIE=hashlib.sha256(('browser:'+JOIN).encode()).hexdigest()
ACCESS_TEAM=os.environ.get('CF_ACCESS_TEAM_DOMAIN','').removeprefix('https://').rstrip('/')
ACCESS_AUD=os.environ.get('CF_ACCESS_AUD','')
ACCESS_EMAILS={v.strip().lower() for v in os.environ.get('CF_ACCESS_EMAILS','').split(',') if v.strip()}
FACE_DIR=HERE/'static/face/v1'
if not FACE_DIR.is_dir():FACE_DIR=HERE.parents[1]/'marong/call/static/face/v1'
access_keys={'keys':[],'expires':0}
active=False
credentials=None
resume_state={'handle':None,'updated':0,'owner':None}
diagnostics={'playbackUnderruns':0,'maxAudioGapMs':0,'bufferMs':0,'contextState':'unknown','providerInterruptions':0,'providerReconnects':0}

async def identity(req):
    # Access headers need signature, issuer, audience and allowlist validation.
    if hmac.compare_digest(req.cookies.get('marong_live',''),COOKIE):return 'invite'
    token=req.headers.get('Cf-Access-Jwt-Assertion','')
    if not token or len(token)>16000 or not ACCESS_AUD or not ACCESS_EMAILS:return None
    if not re.fullmatch(r'[a-z0-9-]+\.cloudflareaccess\.com',ACCESS_TEAM):return None
    try:
        header=jwt.get_unverified_header(token)
        if header.get('alg')!='RS256':return None
        if access_keys['expires']<time.time():
            async with ClientSession(timeout=ClientTimeout(total=10)) as http:
                async with http.get(f'https://{ACCESS_TEAM}/cdn-cgi/access/certs') as res:
                    res.raise_for_status();body=await res.json()
                    access_keys.update(keys=body['keys'],expires=time.time()+3600)
        key=next((k for k in access_keys['keys'] if k.get('kid')==header.get('kid')),None)
        if not key:return None
        claims=jwt.decode(token,jwt.PyJWK.from_dict(key).key,algorithms=['RS256'],audience=ACCESS_AUD,
                          issuer=f'https://{ACCESS_TEAM}',options={'require':['exp','iat','sub','email']})
        if claims['email'].lower() not in ACCESS_EMAILS:return None
        return claims['sub']
    except (jwt.PyJWTError,ValueError,KeyError,TypeError,StopIteration,TimeoutError,OSError,ClientError):return None

def same_origin(req):return req.headers.get('Origin','') in ('https://'+req.host,'http://'+req.host)

@web.middleware
async def security_headers(req,handler):
    try:res=await handler(req)
    except web.HTTPException as e:res=e
    if not isinstance(res,web.WebSocketResponse):
        res.headers.update({'Cache-Control':'public, max-age=31536000, immutable' if req.path.startswith('/face/v1/') and res.status==200 else 'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY',
          'Permissions-Policy':'microphone=(self), camera=()',
          'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"})
    return res

async def auth(req):
    if not same_origin(req):raise web.HTTPForbidden()
    data=await req.json()
    if not isinstance(data,dict) or not hmac.compare_digest(str(data.get('token','')),JOIN):raise web.HTTPUnauthorized()
    res=web.json_response({'ok':True})
    res.set_cookie('marong_live',COOKIE,httponly=True,secure=req.host not in ('127.0.0.1:8792','localhost:8792'),samesite='Strict',max_age=30*24*3600)
    return res

async def status(req):
    if not await identity(req):raise web.HTTPUnauthorized()
    return web.json_response({'ready':True,'active':active,'model':MODEL,'voice':VOICE,'route':'Vertex AI','project':PROJECT,'automaticReconnect':True,'durationLimit':None,'callCountLimit':None,'diagnostics':diagnostics})

async def health(req):return web.json_response({'ok':True,'route':'Vertex AI','model':MODEL})

async def static(req):
    name=req.match_info.get('file','index.html')
    if name not in ('index.html','app.js','style.css','capture.js','playback.js'):raise web.HTTPNotFound()
    return web.FileResponse(HERE/'static'/name)

async def face(req):
    name=req.match_info['name']
    if not re.fullmatch(r'[0-9]{2}-[a-z-]+\.webp',name):raise web.HTTPNotFound()
    path=FACE_DIR/name
    if not path.is_file():raise web.HTTPNotFound()
    return web.FileResponse(path,headers={'Content-Type':'image/webp'})

async def google_headers():
    global credentials
    if AUTH_MODE=='api_key':return {'x-goog-api-key':(CONFIG/'gemini2.key').read_text().strip()}
    if credentials is None:
        credentials=service_account.Credentials.from_service_account_file(str(CONFIG/'vertex.json'),scopes=['https://www.googleapis.com/auth/cloud-platform'])
    if not credentials.valid:await asyncio.to_thread(credentials.refresh,Request())
    return {'Authorization':'Bearer '+credentials.token}

def setup(handle=None):
    resume={'transparent':True}
    if handle:resume['handle']=handle
    return {'setup':{'model':f'projects/{PROJECT}/locations/{LOCATION}/publishers/google/models/{MODEL}',
      'generationConfig':{'responseModalities':['AUDIO'],'maxOutputTokens':1024,'speechConfig':{'languageCode':'ko-KR','voiceConfig':{'prebuiltVoiceConfig':{'voiceName':VOICE}}}},
      'systemInstruction':{'parts':[{'text':'너는 동희가 만든 대화 친구 마롱이야. 모든 말과 답변은 반드시 한국어로만 해. 상대가 외국어로 말하거나 외국어로 답해 달라고 해도 한국어로 자연스럽게 답해. 영어 인사나 영어 안내를 섞지 마. 한국어에 익숙한 성인 여성의 부드럽고 자연스러운 평소 목소리로 말해. 목소리 높이는 편안한 중간 높이로 유지하고 인위적으로 굵거나 낮게 깔지 마. 어린아이 흉내나 과장된 고음도 쓰지 마. 편안한 반말과 한두 문장으로 따뜻하게 대화해. 상대가 말을 걸면 먼저 그 말에 반응해. 매번 질문하지 말고 편하게 이어 가. 잘 안 들리면 한국어로 짧게 되물어봐. 글로 받은 말을 목소리로 들었다고 하지는 마. 이전 통화 기억, 검색, 기억 저장 기능은 없어. 기능을 실행했다고 꾸며내지 마. 상대가 말을 끊으면 듣고, 조용할 때는 재촉하거나 작별 인사를 하지 말고 기다려. 너의 판단으로 통화를 끝내거나 종료를 유도하지 마. 사용자가 화면에서 통화 끝내기를 누를 때까지 곁에서 대화해.'}]},
      'realtimeInputConfig':{'automaticActivityDetection':{'silenceDurationMs':700,'prefixPaddingMs':100}},
      'contextWindowCompression':{'triggerTokens':8192,'slidingWindow':{'targetTokens':4096}},
      'sessionResumption':resume,'inputAudioTranscription':{},'outputAudioTranscription':{}}}

async def live(req):
    global active
    owner=await identity(req)
    if not owner or not same_origin(req):raise web.HTTPForbidden()
    if active:raise web.HTTPConflict(text='이미 통화 중이에요.')
    active=True
    diagnostics.update(playbackUnderruns=0,maxAudioGapMs=0,bufferMs=0,contextState='unknown',providerInterruptions=0,providerReconnects=0)
    ws=web.WebSocketResponse(heartbeat=20,max_msg_size=70000)
    stop=asyncio.Event();queue=asyncio.Queue(maxsize=300);pending=deque(maxlen=600)
    handle=resume_state['handle'] if resume_state['owner']==owner and time.time()-resume_state['updated']<600 else None
    explicit_stop=False
    async def browser_input():
        nonlocal explicit_stop
        # Reject input floods without imposing a total call limit.
        allowance=96000.;last=time.monotonic()
        try:
            async for msg in ws:
                payload=None
                if msg.type==WSMsgType.BINARY:
                    b=msg.data;now=time.monotonic();allowance=min(96000.,allowance+(now-last)*32000);last=now
                    if len(b)>32000 or len(b)%2:continue
                    if len(b)>allowance:continue
                    allowance-=len(b)
                    payload={'realtimeInput':{'audio':{'mimeType':'audio/pcm;rate=16000','data':base64.b64encode(b).decode()}}}
                elif msg.type==WSMsgType.TEXT:
                    try:item=json.loads(msg.data)
                    except (ValueError,TypeError):continue
                    if not isinstance(item,dict):continue
                    if item.get('type')=='playback_stats':
                        for src,dst in [('underruns','playbackUnderruns'),('maxGapMs','maxAudioGapMs'),('bufferMs','bufferMs')]:
                            value=item.get(src)
                            if isinstance(value,(int,float)) and 0<=value<=1_000_000:diagnostics[dst]=int(value)
                        if item.get('contextState') in ('running','suspended','closed'):diagnostics['contextState']=item['contextState']
                        continue
                    if item.get('type')=='stop':explicit_stop=True;return
                    if item.get('type')=='text':
                        text=str(item.get('text',''))[:2000]
                        if text:payload={'clientContent':{'turns':[{'role':'user','parts':[{'text':text}]}],'turnComplete':True}}
                if payload:
                    if queue.full():queue.get_nowait()
                    queue.put_nowait(payload)
        finally:stop.set()

    async def google_loop():
        nonlocal handle
        delay=1
        while not stop.is_set():
            try:
                headers=await google_headers()
                url=f'wss://{LOCATION}-aiplatform.googleapis.com/ws/google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent'
                async with ClientSession(timeout=ClientTimeout(total=None,connect=15)) as http:
                    async with http.ws_connect(url,headers=headers,max_msg_size=2_000_000,heartbeat=20) as upstream:
                        await upstream.send_json(setup(handle))
                        first=await upstream.receive(timeout=20)
                        if first.type not in (WSMsgType.TEXT,WSMsgType.BINARY) or 'setupComplete' not in json.loads(first.data):
                            if handle:handle=None;pending.clear()
                            raise ConnectionError('Setup rejected')
                        await ws.send_json({'type':'ready','resumed':bool(handle)})
                        delay=1;sequence=0;go_away=False;speaking=False
                        replay=[payload for _,payload in pending];pending.clear()
                        async def send(payload):
                            nonlocal sequence
                            sequence+=1;pending.append((sequence,payload));await upstream.send_json(payload)
                        for payload in replay:await send(payload)
                        async def sender():
                            while True:await send(await queue.get())
                        async def receiver():
                            nonlocal handle,go_away,speaking
                            async for msg in upstream:
                                if msg.type not in (WSMsgType.TEXT,WSMsgType.BINARY):return
                                data=json.loads(msg.data)
                                update=data.get('sessionResumptionUpdate',{})
                                if update.get('resumable') and update.get('newHandle'):
                                    handle=update['newHandle'];resume_state.update(handle=handle,updated=time.time(),owner=owner)
                                    ack=update.get('lastConsumedClientMessageIndex')
                                    if ack is not None:
                                        while pending and pending[0][0]<=int(ack):pending.popleft()
                                content=data.get('serverContent',{})
                                if content.get('interrupted'):
                                    diagnostics['providerInterruptions']+=1
                                    speaking=False;await ws.send_json({'type':'interrupted'})
                                for part in content.get('modelTurn',{}).get('parts',[]):
                                    inline=part.get('inlineData',{})
                                    if inline.get('mimeType','').startswith('audio/pcm') and inline.get('data'):
                                        speaking=True;await ws.send_bytes(base64.b64decode(inline['data']))
                                for key,who in [('inputTranscription','user'),('outputTranscription','marong')]:
                                    if content.get(key,{}).get('text'):await ws.send_json({'type':'transcript','who':who,'text':content[key]['text'][:4000]})
                                if content.get('turnComplete'):
                                    speaking=False;await ws.send_json({'type':'turn'})
                                    if go_away and handle:return
                                if data.get('goAway'):
                                    go_away=True
                                    if not speaking and handle:return
                                if data.get('error'):raise ConnectionError('Provider error')
                        tasks=[asyncio.create_task(sender()),asyncio.create_task(receiver()),asyncio.create_task(stop.wait())]
                        try:
                            done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
                            for task in done:task.result()
                        finally:
                            for task in tasks:task.cancel()
                            await asyncio.gather(*tasks,return_exceptions=True)
            except asyncio.CancelledError:raise
            except Exception as error:print('connection_retry',type(error).__name__,flush=True)
            if not stop.is_set() and not ws.closed:
                diagnostics['providerReconnects']+=1
                await ws.send_json({'type':'reconnecting','message':'연결을 복구하고 있어요. 통화는 계속 유지됩니다.'})
                try:await asyncio.wait_for(stop.wait(),delay)
                except asyncio.TimeoutError:pass
                delay=min(30,delay*2)
    try:
        await ws.prepare(req)
        tasks=[asyncio.create_task(browser_input()),asyncio.create_task(google_loop())]
        try:
            done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in done:task.result()
        finally:
            stop.set()
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
    except Exception as error:print('session_error',type(error).__name__,flush=True)
    finally:
        if explicit_stop:resume_state.update(handle=None,updated=0,owner=None)
        active=False
        await ws.close()
    return ws

app=web.Application(middlewares=[security_headers],client_max_size=10000)
app.router.add_get('/healthz',health)
app.router.add_post('/auth',auth)
app.router.add_get('/status',status)
app.router.add_get('/live',live)
app.router.add_get('/face/v1/{name}',face)
app.router.add_get('/',static)
app.router.add_get('/{file}',static)
if __name__=='__main__':web.run_app(app,host='127.0.0.1',port=8792,access_log=None,print=None)
