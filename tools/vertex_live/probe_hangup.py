"""Real Vertex check of Marong's hang-up. Authorized server only.

Synthetic Korean lines are first read aloud by Gemini, then streamed as the
microphone into the real LiveSession with a fake page: no database, memory,
Discord or Kakao, and nothing is saved. It prints event timings, tool results,
captions and token counts; never credentials.

    python probe_hangup.py [scenario ...]   # default: all scenarios
"""
import asyncio,audioop,base64,difflib,json,re,sys,time,uuid
from types import SimpleNamespace
import aiohttp
from aiohttp import WSMsgType
import live_session,server

READ='사용자가 준 한국어 문장을 정확히 그대로 한 번 읽어. 다른 말은 하지 마.'
SCENARIOS={
    'ask':['오늘 얘기 재밌었어. 나 이제 끊을게, 전화 꺼 줘.'],
    'short':['마롱아, 잠깐만 꺼 줘.'],
    'dropped':['아까 전화가 갑자기 끊겨서 진짜 짜증 났어.'],
    'sleepy':['아 나 이제 졸리다.','응, 그래.'],
    'stay':['끊지 마, 나 더 얘기하고 싶어.'],
    'quiet':['잠깐만 조용히 해 봐.'],
}
URL=f'wss://{server.LOCATION}-aiplatform.googleapis.com/ws/google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent'


def plain(text):return re.sub(r'[^가-힣a-z0-9]','',text.lower())


async def speech(text):
    """Gemini reads the line: 24 kHz output resampled to the 16 kHz microphone format.
    A take whose own transcript is not close to the line is read again; after three
    tries the closest take is used and the report shows what it said."""
    config=server.setup();config['setup']['systemInstruction']={'parts':[{'text':READ}]}
    best=(-1,b'','')
    for _ in range(3):
        pcm=bytearray();read=''
        async with aiohttp.ClientSession() as http,http.ws_connect(URL,headers=await server.google_headers()) as ws:
            await ws.send_json(config)
            assert 'setupComplete' in json.loads((await ws.receive(timeout=20)).data)
            await ws.send_json({'clientContent':{'turns':[{'role':'user','parts':[{'text':text}]}],'turnComplete':True}})
            while True:
                content=json.loads((await ws.receive(timeout=30)).data).get('serverContent',{})
                for part in content.get('modelTurn',{}).get('parts',[]):
                    if part.get('inlineData',{}).get('data'):pcm.extend(base64.b64decode(part['inlineData']['data']))
                read+=content.get('outputTranscription',{}).get('text','')
                if content.get('turnComplete'):break
        score=difflib.SequenceMatcher(None,plain(text),plain(read)).ratio() if len(pcm)>24000 else -1
        if score>best[0]:best=(score,bytes(pcm),read)
        if score>=.8:break
    if best[0]<0:raise RuntimeError('no usable speech for the fixture')
    return audioop.ratecv(best[1],2,1,24000,16000,None)[0],best[2]


class Log:
    def __init__(self):self.start=time.monotonic();self.events=[];self.usage=[]
    def add(self,kind,detail=''):self.events.append((round(time.monotonic()-self.start,2),kind,detail))
    def got(self,msg):
        if msg.type not in (WSMsgType.TEXT,WSMsgType.BINARY):return
        data=json.loads(msg.data);content=data.get('serverContent',{})
        if data.get('usageMetadata'):self.usage.append(data['usageMetadata'])
        for part in content.get('modelTurn',{}).get('parts',[]):
            if part.get('inlineData',{}).get('data'):self.add('g:audio',len(base64.b64decode(part['inlineData']['data']))//48)
        for key,role in (('inputTranscription','g:heard'),('outputTranscription','g:said')):
            if content.get(key,{}).get('text'):self.add(role,content[key]['text'])
        for key in ('generationComplete','turnComplete','interrupted'):
            if content.get(key):self.add('g:'+key)
        for call in data.get('toolCall',{}).get('functionCalls',[]):self.add('g:toolCall',call.get('name'))
        if data.get('goAway'):self.add('g:goAway')
    def sent(self,data):
        for response in data.get('toolResponse',{}).get('functionResponses',[]):self.add('r:toolResponse',response['response'].get('result'))
    def timeline(self):
        """Merge runs of audio chunks into one line: time, chunks, milliseconds."""
        out=[]
        for at,kind,detail in self.events:
            if kind in ('g:audio','p:audio') and out and out[-1][1]==kind:
                out[-1]=(out[-1][0],kind,out[-1][2]+detail,out[-1][3]+1,at)
            elif kind in ('g:audio','p:audio'):out.append((at,kind,detail,1,at))
            else:out.append((at,kind,detail))
        return [f'{e[0]:6.2f}{"-"+format(e[4],".2f") if len(e)==5 else ""} {e[1]} {e[2]}{" ms in "+str(e[3])+" chunks" if len(e)==5 else ""}' for e in out]


class Upstream:
    def __init__(self,ws,log):self.ws=ws;self.log=log
    def __getattr__(self,name):return getattr(self.ws,name)
    async def send_json(self,data):self.log.sent(data);await self.ws.send_json(data)
    async def receive(self,timeout=None):
        msg=await self.ws.receive(timeout=timeout);self.log.got(msg);return msg
    def __aiter__(self):return self
    async def __anext__(self):
        msg=await self.ws.__anext__();self.log.got(msg);return msg
class Connect:
    def __init__(self,manager,log):self.manager=manager;self.log=log
    async def __aenter__(self):return Upstream(await self.manager.__aenter__(),self.log)
    async def __aexit__(self,*exc):return await self.manager.__aexit__(*exc)


class Page:
    """The browser side: plays nothing, records what the relay sends and when."""
    def __init__(self,log):self.log=log;self.incoming=asyncio.Queue();self.closed=False;self.hangup=None
    async def send_json(self,data):
        if data.get('type') in ('ready','audio_end','turn','hangup','reconnecting','interrupted'):self.log.add('p:'+data['type'],data.get('pendingMs',''))
        if data.get('type')=='hangup':self.hangup=time.monotonic()
    async def send_bytes(self,data):self.log.add('p:audio',(len(data)-24)//48)
    async def close(self,**kw):self.closed=True
    def __aiter__(self):return self
    async def __anext__(self):
        item=await self.incoming.get()
        if item is None:raise StopAsyncIteration
        return item
    def mic(self,pcm):self.incoming.put_nowait(SimpleNamespace(type=WSMsgType.BINARY,data=pcm))
    def stop(self):self.incoming.put_nowait(SimpleNamespace(type=WSMsgType.TEXT,data='{"type":"stop"}'))


async def say(page,log,pcm,text):
    log.add('mic:start',text)
    for start in range(0,len(pcm),3200):  # 100 ms chunks in real time
        page.mic(pcm[start:start+3200]);await asyncio.sleep(.1)
    log.add('mic:end')
    for _ in range(20):page.mic(b'\0'*3200);await asyncio.sleep(.1)  # 2 s of silence for the VAD


async def scenario(name,lines,fixtures):
    log=Log();page=Page(log);diagnostics={}
    live_session.ClientSession=lambda **kw:Session(log,**kw)
    session=live_session.LiveSession(page,'probe',None,None,server.setup,server.google_headers,{},diagnostics,
        server.LOCATION,server.MODEL,server.VOICE,str(uuid.uuid4()),hangup=True)
    task=asyncio.create_task(session.run())
    for _ in range(300):
        if session.ready:break
        await asyncio.sleep(.1)
    for index,line in enumerate(lines):
        await say(page,log,fixtures[line][0],line)
        # Wait for Marong's reply to finish (or the hang-up) before the next line.
        for _ in range(250):
            await asyncio.sleep(.1)
            if page.hangup or task.done():break
            last=max((at for at,kind,_ in log.events if kind.startswith('g:')),default=0)
            if time.monotonic()-log.start-last>4:break
        if page.hangup:break
    if page.hangup:
        await asyncio.sleep(3)  # anything after 'hangup' would be cut off on a real page
        page.stop()
    else:page.stop()
    try:await asyncio.wait_for(task,10)
    except TimeoutError:task.cancel()
    after=[e for e in log.events if page.hangup and e[0]>page.hangup-log.start and e[1]=='p:audio']
    spoken=max((e[0] for e in log.events if e[1]=='mic:end'),default=0)
    first=lambda kind:next((e[0] for e in log.events if e[1]==kind and e[0]>=spoken),None)
    since=lambda at:None if at is None else round(at-spoken,2)
    goodbye=sum(e[2] for e in log.events if e[1]=='p:audio' and e[0]>=spoken and (not page.hangup or e[0]<=page.hangup-log.start))
    said=''.join(d for _,k,d in log.events if k=='g:said')
    heard=' / '.join(d for _,k,d in log.events if k=='g:heard')
    tokens={k:sum(u.get(k,0) or 0 for u in log.usage[-1:]) for k in ('promptTokenCount','responseTokenCount','totalTokenCount')}
    return {'scenario':name,'read_as':[fixtures[line][1] for line in lines],'hangup':bool(page.hangup),
            'after_last_line_s':{'tool_call':since(first('g:toolCall')),'tool_response':since(first('r:toolResponse')),
                'turn_complete':since(first('g:turnComplete')),'hangup':since(first('p:hangup'))},
            'reply_audio_ms_before_hangup':goodbye,'audio_after_hangup_ms':sum(e[2] for e in after),
            'diagnostics':{k:diagnostics.get(k) for k in ('hangup','hangupRefused','hangupServerEnded') if k in diagnostics},
            'heard':heard,'said':said,'last_usage':tokens,'timeline':log.timeline()}


class Session:
    """aiohttp.ClientSession whose Vertex socket is recorded."""
    def __init__(self,log,**kw):self.http=aiohttp.ClientSession(**kw);self.log=log
    async def __aenter__(self):await self.http.__aenter__();return self
    async def __aexit__(self,*exc):return await self.http.__aexit__(*exc)
    def ws_connect(self,*a,**kw):return Connect(self.http.ws_connect(*a,**kw),self.log)


async def main(names):
    names=names or list(SCENARIOS)
    fixtures={}
    for name in names:
        for line in SCENARIOS[name]:
            if line not in fixtures:fixtures[line]=await speech(line)
    for name in names:
        print(json.dumps(await scenario(name,SCENARIOS[name],fixtures),ensure_ascii=False,indent=1),flush=True)

if __name__=='__main__':asyncio.run(main(sys.argv[1:]))
