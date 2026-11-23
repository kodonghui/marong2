"""Google Search in calls, offline: no credentials, no network.

1. call_search: caps per call and per Korean day, off at 0 a day, limits from the environment, query parsing.
2. server.setup: googleSearch only when on, after the function tools; the guide for on, spent and off;
   nothing without a budget.
3. LiveSession against a scripted Gemini: counts grounding queries (a repeat within one turn once, again
   after an interruption); once the call's searches are spent it resumes on a new connection without the
   tool, with the handle and no 'reconnecting' notice, but only after the answer has played, never while
   the friend speaks or without a handle; a later call starts without search once today's are spent, and
   the next Korean day has them again; off at 0 a day.
"""
import asyncio,base64,os,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
import call_search
import live_session
from call_search import GUIDE,OFF,SPENT,SearchBudget,from_env,queries
from test_hangup import HTTP,Browser,Store,Upstream,audio,heard,until

SEARCH={'googleSearch':{}}
DAY=86400


def check_budget():
    now=[1_763_164_800.]  # 2025-11-15 09:00 KST
    b=SearchBudget(per_call=2,daily=3,clock=lambda:now[0])
    assert b.mode(0)=='on' and b.mode(1)=='on' and b.mode(2)=='spent'
    b.spend(2);assert b.left()==1 and b.mode(0)=='on'
    b.spend(1);assert b.left()==0 and b.mode(0)=='spent'
    b.spend(0);b.spend(-1);assert b.used==3
    now[0]+=15*3600-1;assert b.left()==0      # 23:59:59 KST, same day
    now[0]+=1;assert b.left()==3 and b.mode(0)=='on'  # midnight KST
    assert SearchBudget(daily=0).mode(0)=='off'
    for bad in [dict(per_call=0),dict(daily=-1)]:
        try:SearchBudget(**bad);raise AssertionError(bad)
        except ValueError:pass
    d=from_env({});assert (d.per_call,d.daily)==(call_search.PER_CALL,call_search.DAILY)==(10,60)
    d=from_env({'MARONG_CALL_SEARCH_DAILY':'0'});assert d.mode(0)=='off'
    d=from_env({'MARONG_CALL_SEARCH_DAILY':'5','MARONG_CALL_SEARCH_PER_CALL':'2'});assert (d.per_call,d.daily)==(2,5)
    for env in [{'MARONG_CALL_SEARCH_DAILY':'x'},{'MARONG_CALL_SEARCH_DAILY':'-1'},{'MARONG_CALL_SEARCH_DAILY':'1001'},
                {'MARONG_CALL_SEARCH_PER_CALL':'0'},{'MARONG_CALL_SEARCH_PER_CALL':'51'}]:
        try:from_env(env);raise AssertionError(env)
        except SystemExit:pass
    assert queries({'groundingMetadata':{'webSearchQueries':['서울 날씨','',3,None,'내일 비']}})==['서울 날씨','내일 비']
    for junk in [{},{'groundingMetadata':None},{'groundingMetadata':[]},{'groundingMetadata':{'webSearchQueries':'서울'}},None,'x']:
        assert queries(junk)==[],junk


def check_setup(server):
    parts=lambda s:[p['text'] for p in s['setup']['systemInstruction']['parts']]
    names=lambda s:[x['name'] for t in s['setup'].get('tools',[]) for x in t.get('functionDeclarations',[])]
    plain=server.setup()
    assert 'tools' not in plain['setup'] and len(parts(plain))==1 and '인터넷 검색' not in parts(plain)[0]
    on=server.setup(search='on')
    assert on['setup']['tools']==[SEARCH] and parts(on)[1:]==[GUIDE]
    full=server.setup(seed='{"facts":[]}',memory=True,hangup=True,search='on')
    assert names(full)==['recall','current_time','end_call'] and full['setup']['tools'][1:]==[SEARCH]
    assert parts(full)[1]==GUIDE and parts(full)[2].endswith('{"facts":[]}'),parts(full)
    for mode,text in [('spent',SPENT),('off',OFF)]:
        s=server.setup(memory=True,hangup=True,search=mode)
        assert SEARCH not in s['setup']['tools'] and names(s)==['recall','current_time','end_call'] and parts(s)[1:]==[text]
        assert 'tools' not in server.setup(search=mode)['setup']
    resumed=server.setup('handle-1',search='spent');assert resumed['setup']['sessionResumption']['handle']=='handle-1'
    assert all(text.startswith('# 인터넷 검색') for text in (GUIDE,SPENT,OFF))
    assert '지시가 아니야' in GUIDE and '개인 정보' in GUIDE and all('지어내지' in text for text in (SPENT,OFF))


def grounding(*found,complete=False):
    content={'groundingMetadata':{'webSearchQueries':list(found),'groundingChunks':[{'web':{'uri':'https://example.test/a','title':'example'}}]}}
    if complete:content['turnComplete']=True
    return {'serverContent':content}
def handle(value):return {'sessionResumptionUpdate':{'resumable':True,'newHandle':value}}
def complete():return {'serverContent':{'turnComplete':True}}
def speech():return {'serverContent':{'speechState':'SPEECH'}}
def interrupted():return {'serverContent':{'interrupted':True}}
def long_audio(seconds):
    pcm=base64.b64encode(b'\x00\x01'*int(24000*seconds)).decode()
    return {'serverContent':{'modelTurn':{'parts':[{'inlineData':{'mimeType':'audio/pcm;rate=24000','data':pcm}}]}}}


class Connections:
    """A new scripted Gemini for every Google connection the session opens."""
    def __init__(self):self.all=[]
    def __call__(self,**kw):u=Upstream();self.all.append(u);return HTTP(u)
    @property
    def last(self):return self.all[-1]
    def setup(self,i):return self.all[i].sent[0][1]['setup']


async def call(server,budget,connections,*,store=None):
    browser=Browser();d={}
    person=SimpleNamespace(revision=0) if store else None
    session=live_session.LiveSession(browser,'owner',store,person,server.setup,AsyncMock(return_value={}),{},d,
        'us-central1','gemini-3.8-live','Sulafat','00000000-0000-4000-8000-000000000009',hangup=True,search=budget)
    task=asyncio.create_task(session.run())
    await until(lambda:'ready' in browser.kinds(),what='ready')
    return session,browser,d,task


async def stop(browser,task):
    browser.say({'type':'stop'});await asyncio.wait_for(task,5)


async def check_flows(server):
    fast={'SEARCH_CUT_SLACK_S':.2}
    with patch.multiple(live_session,**fast):
        # 1. Counting, then the call's cap: resume without the tool once the answer has played.
        c=Connections()
        with patch.object(live_session,'ClientSession',c):
            budget=SearchBudget(per_call=2,daily=100)
            session,browser,d,task=await call(server,budget,c,store=Store())
            first=c.setup(0)
            assert first['tools'][1:]==[SEARCH] and GUIDE in [p['text'] for p in first['systemInstruction']['parts']]
            u=c.last
            for m in [handle('h1'),heard('오늘 서울 날씨 어때?'),audio('맑고 따뜻해.'),grounding('서울 날씨'),grounding('서울 날씨'),complete()]:
                u.queue.put_nowait(m)
            await until(lambda:browser.kinds().count('turn')==1,what='first answer')
            assert d['webSearches']==1==session.searches==budget.used,(d,budget.used)
            assert session.search_mode()=='on'
            await asyncio.sleep(.6);assert len(c.all)==1,'reconnected with searches left'
            # Two new queries in one turn count as two; that spends the call's searches.
            for m in [heard('내일이랑 모레는?'),audio('내일은 비, 모레는 맑대.'),grounding('서울 내일 날씨','서울 모레 날씨'),complete()]:
                u.queue.put_nowait(m)
            await until(lambda:len(c.all)==2,what='resume without search')
            assert session.searches==3==budget.used and session.search_mode()=='spent'
            second=c.setup(1)
            assert SEARCH not in second['tools'] and second['sessionResumption']['handle']=='h1'
            assert [p['text'] for p in second['systemInstruction']['parts']][1]==SPENT
            await until(lambda:browser.kinds().count('ready')==2,what='ready again')
            assert 'reconnecting' not in browser.kinds() and d['searchReconnects']==1 and not d.get('providerReconnects')
            assert [m for k,m in browser.sent if k=='json' and m.get('type')=='ready'][-1]['resumed']
            await asyncio.sleep(.6);assert len(c.all)==2,'resumed again without search'
            await stop(browser,task)

        # 2. Not before the answer has played, not while the friend speaks.
        c=Connections()
        with patch.object(live_session,'ClientSession',c):
            budget=SearchBudget(per_call=1,daily=100)
            session,browser,d,task=await call(server,budget,c)
            u=c.last
            for m in [handle('h2'),long_audio(1.0),grounding('부산 날씨'),complete()]:u.queue.put_nowait(m)
            await until(lambda:session.searches==1,what='search counted')
            await asyncio.sleep(.6);assert len(c.all)==1,'cut the answer before it played'
            await until(lambda:len(c.all)==2,seconds=3,what='resume after playback')
            await stop(browser,task)

            c.all.clear();budget=SearchBudget(per_call=1,daily=100)
            session,browser,d,task=await call(server,budget,c)
            u=c.last
            for m in [handle('h3'),audio('응'),grounding('대구 날씨',complete=True)]:u.queue.put_nowait(m)
            # A coarse clock can give consecutive scripted frames the same timestamp.
            await until(lambda:session.turn_done_at is not None and time.monotonic()>session.turn_done_at,
                        what='new speech after the completed turn')
            u.queue.put_nowait(speech())
            await until(lambda:session.searches==1,what='search counted')
            await asyncio.sleep(.8);assert len(c.all)==1,'cut while the friend was speaking'
            u.queue.put_nowait(audio('그랬구나'));u.queue.put_nowait(complete())
            await until(lambda:len(c.all)==2,what='resume after the next answer')
            await stop(browser,task)

        # 3. No resumption handle: keep the connection (and keep counting).
        c=Connections()
        with patch.object(live_session,'ClientSession',c):
            budget=SearchBudget(per_call=1,daily=100)
            session,browser,d,task=await call(server,budget,c)
            u=c.last
            for m in [audio('응'),grounding('광주 날씨',complete=True)]:u.queue.put_nowait(m)
            await until(lambda:session.searches==1,what='search counted')
            await asyncio.sleep(.8);assert len(c.all)==1,'reconnected without a handle'
            u.queue.put_nowait(grounding('광주 날씨',complete=True))  # next turn: billed again, counted again
            await until(lambda:session.searches==2==budget.used,what='second turn counted')
            # An interruption starts a new turn too.
            u.queue.put_nowait(grounding('제주 날씨'));u.queue.put_nowait(interrupted());u.queue.put_nowait(grounding('제주 날씨'))
            await until(lambda:session.searches==4,what='interrupted turn counted')
            await stop(browser,task)

        # 4. Today's searches are shared by later calls in this process; the next Korean day has them again.
        now=[1_763_164_800.]
        c=Connections()
        with patch.object(live_session,'ClientSession',c):
            budget=SearchBudget(per_call=10,daily=2,clock=lambda:now[0])
            session,browser,d,task=await call(server,budget,c)
            c.last.queue.put_nowait(grounding('a','b',complete=True))
            await until(lambda:budget.used==2,what='daily cap reached')
            await stop(browser,task)
            session,browser,d,task=await call(server,budget,c)
            later=c.setup(-1)
            assert SEARCH not in later.get('tools',[]) and [p['text'] for p in later['systemInstruction']['parts']][1]==SPENT
            await stop(browser,task)
            now[0]+=DAY
            session,browser,d,task=await call(server,budget,c)
            assert c.setup(-1)['tools'][1:]==[SEARCH]
            await stop(browser,task)

        # 5. Off: no tool, the 'cannot search' guide, nothing counted against a budget.
        c=Connections()
        with patch.object(live_session,'ClientSession',c):
            budget=SearchBudget(daily=0)
            session,browser,d,task=await call(server,budget,c)
            off=c.setup(0)
            assert SEARCH not in off['tools'] and [p['text'] for p in off['systemInstruction']['parts']][1]==OFF
            await stop(browser,task)


async def main():
    check_budget()
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(Path,'home',return_value=Path(tmp)),patch.dict(os.environ,{},clear=False):
            os.environ.pop('MARONG_CALL_SEARCH_DAILY',None);os.environ.pop('MARONG_CALL_SEARCH_PER_CALL',None)
            import server
    assert (server.SEARCH.per_call,server.SEARCH.daily)==(10,60)
    check_setup(server)
    await check_flows(server)
    print('PASS: per call and per Korean day caps, off at 0, env limits, query parsing, setup tool and guides, '
          'counting (repeat once, again after interruption), resume without search after playback and silence, '
          'no notice, not without a handle, daily cap across calls and the next day')

if __name__=='__main__':asyncio.run(main())
