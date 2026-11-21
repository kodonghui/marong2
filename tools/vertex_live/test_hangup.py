"""Hang-up on the friend's request, offline: no credentials, no network.

1. hangup.Consent: which words allow Marong to end the call.
2. server.setup: end_call is offered only to clients that can hang up.
3. LiveSession against a scripted Gemini: refused without a request, goodbye
   audio before 'hangup', no microphone after acceptance, close reason, server
   fallback, late captions, a goodbye that starts after the answer, text input.
"""
import asyncio,base64,json,struct,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
import aiohttp
from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient,TestServer
import live_session
from hangup import Consent

ASKS=['끊어 줘','이제 끊자','나 끊을게','나 이제 끊을게요','전화 꺼','꺼 줘','마루야, 잠깐만 꺼 줘.','통화 종료','그만 통화하자',
      '바이바이','나 들어갈게','이제 끊어도 돼','오늘 재밌었다 이제 끊자','전화 끊고 잘게','마롱아 꺼','이제 끝내자']
NOT_ASKS=['오늘 진짜 재밌었다','아 졸려','나 이제 잘게','밥 먹으러 가야겠다','아까 전화가 갑자기 끊겨서 짜증 났어','끊지 마',
          '아직 끊지 마','끊기 싫어','안 끊어','담배 끊었어','끊길까 봐 무서워','아까 끊어져서 다시 걸었어','이제 꺼내 볼게',
          '끊기지 않게 해 줘','전화 끄지 마','잘 자','고마워','']


def check_consent():
    now=[0.]
    def fresh():return Consent(lambda:now[0])
    for text in ASKS:
        c=fresh();c.note('user','u',text);assert c.asked(),text
    for text in NOT_ASKS:
        c=fresh();c.note('user','u',text);assert not c.asked(),text
    # Marong's own words never count.
    c=fresh();c.note('assistant','a','나 이제 끊을게');c.note('model','b','전화 꺼 줄까?');assert not c.asked()
    # A short yes to Marong's offer.
    for reply,expected in [('응',True),('응 그래',True),('ㅇㅇ',True),('그래 잘 자',True),('어 끊어',True),('아니 더 얘기하자',False),
                           ('응 근데 아직',False),('어?',False),('응?',False),('어 잠깐만',False),('싫어',False),('그 얘기 마저 해 줘',False)]:
        c=fresh();c.note('user','u1','아 졸려');c.note('assistant','a1','그럼 이제 끊을까?');c.note('user','u2',reply)
        assert c.asked() is expected,reply
    # The offer must be Marong's latest line before the yes.
    c=fresh();c.note('user','u1','졸려');c.note('assistant','a1','끊을까?');c.note('assistant','a2','아 맞다 그거 어떻게 됐어?');c.note('user','u2','응')
    assert not c.asked()
    # Streaming captions replace their own line: a request that turns into a refusal is no request.
    c=fresh();c.note('user','u','끊');assert c.asked();c.note('user','u','끊지 마');assert not c.asked()
    # Only the friend's last two lines count for a direct request.
    c=fresh();c.note('user','u1','이제 끊을게');c.note('user','u2','아 근데');assert c.asked()
    c.note('user','u3','그거 알아?');assert not c.asked()
    # Only this call's recent words count.
    c=fresh();c.note('user','u1','이제 끊을게');now[0]+=91;assert not c.asked()
    # Marong talking after the request does not cancel it.
    c=fresh();c.note('user','u1','이제 끊을게');c.note('assistant','a1','응, 알겠어. 또 얘기하자!');assert c.asked()


async def check_setup():
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(Path,'home',return_value=Path(tmp)):import server
    names=lambda config:[x['name'] for tool in config['setup'].get('tools',[]) for x in tool.get('functionDeclarations',[])]
    assert names(server.setup())==[]
    assert names(server.setup(hangup=True))==['end_call']
    assert names(server.setup(memory=True))==['recall','current_time']
    assert names(server.setup(memory=True,hangup=True))==['recall','current_time','end_call']
    end_call=server.setup(hangup=True)['setup']['tools'][0]['functionDeclarations'][0]
    assert '분명히 말했을 때만' in end_call['description'] and end_call['parameters']['properties']=={}
    return server


AUDIO=base64.b64encode(b'\x00\x01'*240).decode()
def audio(text=None,complete=False):
    content={'modelTurn':{'parts':[{'inlineData':{'mimeType':'audio/pcm;rate=24000','data':AUDIO}}]}}
    if text:content['outputTranscription']={'text':text}
    if complete:content['turnComplete']=True
    return {'serverContent':content}
def heard(text):return {'serverContent':{'inputTranscription':{'text':text,'finished':True}}}
def end_call(identifier):return {'toolCall':{'functionCalls':[{'id':identifier,'name':'end_call','args':{}}]}}


class Upstream:
    """Scripted Gemini: the test pushes server messages and reads what the relay sent."""
    def __init__(self):self.queue=asyncio.Queue();self.sent=[]
    async def __aenter__(self):return self
    async def __aexit__(self,*a):pass
    async def send_json(self,d):self.sent.append((time.monotonic(),d))
    async def receive(self,timeout=None):return SimpleNamespace(type=WSMsgType.TEXT,data='{"setupComplete":{}}',extra='')
    def __aiter__(self):return self
    async def __anext__(self):return SimpleNamespace(type=WSMsgType.TEXT,data=json.dumps(await self.queue.get()),extra='')
    def tool_responses(self):
        return [r for _,d in self.sent for r in d.get('toolResponse',{}).get('functionResponses',[])]
    def microphone_after(self,at):
        return [d for when,d in self.sent if when>at and 'realtimeInput' in d]
class HTTP:
    def __init__(self,u):self.u=u
    async def __aenter__(self):return self
    async def __aexit__(self,*a):pass
    def ws_connect(self,url,**kw):return self.u

class Browser:
    """The page or Discord bot side of the relay socket."""
    def __init__(self):self.incoming=asyncio.Queue();self.sent=[];self.closed=False
    async def send_json(self,d):self.sent.append(('json',d))
    async def send_bytes(self,b):self.sent.append(('bytes',b))
    async def close(self,**kw):self.closed=True
    def __aiter__(self):return self
    async def __anext__(self):
        item=await self.incoming.get()
        if item is None:raise StopAsyncIteration
        return item
    def say(self,data):self.incoming.put_nowait(SimpleNamespace(type=WSMsgType.TEXT,data=json.dumps(data)))
    def mic(self):self.incoming.put_nowait(SimpleNamespace(type=WSMsgType.BINARY,data=b'\0'*640))
    def kinds(self):return [d.get('type') if kind=='json' else 'bytes' for kind,d in self.sent]
    def hangups(self):return [d for kind,d in self.sent if kind=='json' and d.get('type')=='hangup']

class Store:
    """Just enough of MemoryStore to see how the call ends."""
    def __init__(self):self.finished=[]
    async def start_call(self,p,client_id,voice,build,entrypoint):return 'call-1',False
    async def start_segment(self,p,call_id,client_id,model,**options):return 'segment-1'
    async def segment_ready(self,segment):pass
    async def record_connection(self,segment,**report):pass
    async def seed(self,p,call_id):return ''
    async def save_turn(self,*a):return 1
    async def record_transport(self,*a):pass
    async def revision(self,p):return 0
    async def finish(self,p,call_id,explicit,*,entrypoint=None,client_id=None,reason=None):self.finished.append((explicit,reason))


async def until(check,seconds=3,what='condition'):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if check():return
        await asyncio.sleep(.02)
    raise AssertionError('timed out waiting for '+what)


async def call(server,*,hangup=True,store=None):
    upstream=Upstream();browser=Browser();diagnostics={}
    person=SimpleNamespace(revision=0) if store else None
    session=live_session.LiveSession(browser,'owner',store,person,server.setup,AsyncMock(return_value={}),{},diagnostics,
                                     'us-central1','gemini-3.8-live','Sulafat','00000000-0000-4000-8000-000000000001',hangup=hangup)
    with patch.object(live_session,'ClientSession',lambda **kw:HTTP(upstream)):
        task=asyncio.create_task(session.run())
        await until(lambda:'ready' in browser.kinds(),what='ready')
    return session,upstream,browser,diagnostics,task


async def check_flows(server):
    fast={'HANGUP_LATE_CAPTION_S':.4,'HANGUP_QUIET_S':.3,'HANGUP_REPLY_S':.8,'HANGUP_CLIENT_S':.6,'HANGUP_MAX_S':4}
    with patch.multiple(live_session,**fast):
        # 1. No request: refused after the late-caption wait, the call goes on.
        session,upstream,browser,d,task=await call(server)
        assert [x['name'] for x in upstream.sent[0][1]['setup']['tools'][0]['functionDeclarations']]==['end_call']
        upstream.queue.put_nowait(heard('오늘 진짜 재밌었다'));upstream.queue.put_nowait(end_call('e1'))
        await until(lambda:upstream.tool_responses(),what='refusal')
        response=upstream.tool_responses()[0]
        assert response['id']=='e1' and response['response']['result']=='refused' and d['hangupRefused']==1
        upstream.queue.put_nowait(audio('그래서 그다음엔?',complete=True))
        await until(lambda:'turn' in browser.kinds(),what='next turn')
        await asyncio.sleep(.5);assert not browser.hangups() and not task.done() and session.hanging_up is None
        browser.incoming.put_nowait(None);await task

        # 2. Request, goodbye audio around a mid-turn tool call, no turnComplete.
        store=Store()
        session,upstream,browser,d,task=await call(server,store=store)
        names=[x['name'] for x in upstream.sent[0][1]['setup']['tools'][0]['functionDeclarations']]
        assert names==['recall','current_time','end_call'],names
        upstream.queue.put_nowait(heard('나 이제 끊을게'))
        upstream.queue.put_nowait(audio('응, 알겠어.'));upstream.queue.put_nowait(end_call('e2'))
        await until(lambda:upstream.tool_responses(),what='ending')
        assert upstream.tool_responses()[0]['response']['result']=='ending' and d['hangup']=='accepted'
        answered=time.monotonic()
        browser.mic();upstream.queue.put_nowait(audio(' 또 얘기하자!'))
        await until(lambda:browser.hangups(),what='hangup')
        kinds=browser.kinds();last_audio=len(kinds)-1-kinds[::-1].index('bytes')
        assert kinds.index('hangup')>kinds.index('audio_end',last_audio)>last_audio,kinds
        message=browser.hangups()[0];assert message['pendingMs']==0 and message['callId']=='call-1'
        assert not upstream.microphone_after(answered),'microphone reached Gemini after the goodbye started'
        browser.say({'type':'stop'});await task
        assert store.finished==[(True,'close_requested')],store.finished
        assert len(browser.hangups())==1 and 'hangupServerEnded' not in d

        # 3. A client that never stops: the server ends the call itself.
        store=Store()
        session,upstream,browser,d,task=await call(server,store=store)
        upstream.queue.put_nowait(heard('전화 꺼 줘'));upstream.queue.put_nowait(end_call('e3'))
        upstream.queue.put_nowait(audio('응, 잘 자!',complete=True))
        await asyncio.wait_for(task,5)
        assert browser.hangups() and d['hangupServerEnded'] and store.finished==[(True,'close_requested')]

        # 4. The request's caption arrives after the tool call.
        session,upstream,browser,d,task=await call(server)
        upstream.queue.put_nowait(end_call('e4'))
        await asyncio.sleep(.15);upstream.queue.put_nowait(heard('끊어 줘'))
        await until(lambda:upstream.tool_responses(),what='late caption')
        assert upstream.tool_responses()[0]['response']['result']=='ending'
        browser.say({'type':'stop'});await task

        # 5. Goodbye only after the answer, starting later than the quiet window.
        session,upstream,browser,d,task=await call(server)
        upstream.queue.put_nowait(heard('이제 끊자'));upstream.queue.put_nowait(end_call('e5'))
        await until(lambda:upstream.tool_responses(),what='ending')
        await asyncio.sleep(.5);assert not browser.hangups(),'hung up before the goodbye began'
        upstream.queue.put_nowait(audio('응, 또 얘기하자!'));upstream.queue.put_nowait(audio(complete=True))
        await until(lambda:browser.hangups(),what='hangup after the late goodbye')
        kinds=browser.kinds();assert kinds.index('hangup')>len(kinds)-1-kinds[::-1].index('bytes')
        browser.say({'type':'stop'});await task

        # 6. A second end_call during the goodbye is answered, not doubled.
        session,upstream,browser,d,task=await call(server)
        upstream.queue.put_nowait(heard('이제 끊자'));upstream.queue.put_nowait(end_call('e6'))
        await until(lambda:upstream.tool_responses(),what='ending')
        upstream.queue.put_nowait(end_call('e7'));await until(lambda:len(upstream.tool_responses())==2,what='second answer')
        assert [r['response']['result'] for r in upstream.tool_responses()]==['ending','ending']
        await until(lambda:browser.hangups(),what='hangup');await asyncio.sleep(.2);assert len(browser.hangups())==1
        browser.say({'type':'stop'});await task

        # 7. Typed request on the web page counts like a spoken one.
        session,upstream,browser,d,task=await call(server)
        browser.say({'type':'text','id':'t1','text':'나 이제 끊을게'})
        await until(lambda:any('clientContent' in x for _,x in upstream.sent),what='typed text')
        upstream.queue.put_nowait(end_call('e8'))
        await until(lambda:upstream.tool_responses(),what='ending')
        assert upstream.tool_responses()[0]['response']['result']=='ending'
        browser.say({'type':'stop'});await task

        # 8. A client that cannot hang up gets no tool, and a stray call is unavailable.
        session,upstream,browser,d,task=await call(server,hangup=False)
        assert 'tools' not in upstream.sent[0][1]['setup']
        upstream.queue.put_nowait(heard('끊어 줘'));upstream.queue.put_nowait(end_call('e9'))
        await until(lambda:upstream.tool_responses(),what='unavailable')
        assert upstream.tool_responses()[0]['response']['result']=='unavailable'
        await asyncio.sleep(.5);assert not browser.hangups() and session.hanging_up is None
        browser.say({'type':'stop'});await task


async def check_http(server):
    """The page opts in with ?hangup=1; a page loaded before this change does not."""
    upstreams=[]
    def factory(**kw):u=Upstream();upstreams.append(u);return HTTP(u)
    with patch.object(server,'google_headers',AsyncMock(return_value={})),patch.object(live_session,'ClientSession',factory):
        async with TestClient(TestServer(server.app)) as c:
            origin=str(c.make_url('/')).rstrip('/')
            headers={'Origin':origin,'Cookie':'marong_live='+server.COOKIE}
            for query,tools in [('&hangup=1',['end_call']),('',[])]:
                ws=await c.ws_connect('/live?client=00000000-0000-4000-8000-000000000002'+query,headers=headers)
                for _ in range(20):
                    m=await ws.receive(timeout=4)
                    if m.type==WSMsgType.TEXT and json.loads(m.data).get('type')=='ready':break
                setup=upstreams[-1].sent[0][1]['setup']
                assert [x['name'] for t in setup.get('tools',[]) for x in t.get('functionDeclarations',[])]==tools,query
                await ws.send_json({'type':'stop'});await ws.receive();await ws.close()
                for _ in range(100):
                    if not server.active_calls:break
                    await asyncio.sleep(.01)
            page=await (await c.get('/')).text()
            assert f'/app.js?v={server.ASSET_VERSIONS["app.js"]}' in page


async def main():
    check_consent()
    server=await check_setup()
    await check_flows(server)
    await check_http(server)
    print(f'PASS: {len(ASKS)} requests and {len(NOT_ASKS)} non-requests, offer and yes, refusal keeps the call, goodbye audio before hangup, '
          'no microphone after acceptance, close_requested, server fallback, late caption, late goodbye, typed request, old clients get no tool')

if __name__=='__main__':asyncio.run(main())
