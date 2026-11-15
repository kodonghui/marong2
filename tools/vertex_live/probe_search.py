"""Real Vertex check of call search. Authorized server only, from a separate copy of the call files.

A fake page types two questions into the real LiveSession with search on and one search allowed per call:
1. a weather question: the search is counted, then the session moves to a connection without search
   once the answer has had time to play;
2. a news question on that connection: no search is counted and Marong should say she cannot look it up now.
It prints the search mode each Google connection got, counts, timings and Marong's captions. Typed text
stands in for the microphone. No database, memory, Discord or Kakao; it saves nothing and never prints
credentials.

    python probe_search.py
"""
import asyncio,json,time,uuid
from types import SimpleNamespace

from aiohttp import WSMsgType
import live_session,server
from call_search import SearchBudget

QUESTIONS=['지금 서울 날씨 어때? 인터넷에서 찾아봐 줘.','오늘 한국 뉴스 하나만 찾아서 알려 줘.']


class Page:
    """The browser side: typed questions in, everything the session sends kept with its time."""
    def __init__(self):self.t0=time.monotonic();self.incoming=asyncio.Queue();self.sent=[];self.closed=False
    def at(self):return round(time.monotonic()-self.t0,2)
    async def send_json(self,d):self.sent.append((self.at(),'json',d))
    async def send_bytes(self,b):self.sent.append((self.at(),'bytes',len(b)))
    async def close(self,**kw):self.closed=True
    def __aiter__(self):return self
    async def __anext__(self):
        item=await self.incoming.get()
        if item is None:raise StopAsyncIteration
        return item
    def say(self,data):self.incoming.put_nowait(SimpleNamespace(type=WSMsgType.TEXT,data=json.dumps(data,ensure_ascii=False)))
    def events(self,kind):return [(t,d) for t,k,d in self.sent if k=='json' and d.get('type')==kind]
    def first_audio_after(self,t0):return next((t for t,k,_ in self.sent if k=='bytes' and t>=t0),None)
    def captions(self,who):
        lines={}
        for _,k,d in self.sent:
            if k=='json' and d.get('type')=='transcript' and d.get('who')==who:lines[d.get('key')]=d.get('text')
        return list(lines.values())


async def wait(check,seconds,what):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if check():return
        await asyncio.sleep(.1)
    raise TimeoutError(what)


async def main():
    modes=[]
    def setup(*args,**kw):modes.append(kw.get('search'));return server.setup(*args,**kw)
    page=Page();d={};budget=SearchBudget(per_call=1,daily=5)
    session=live_session.LiveSession(page,'probe-search',None,None,setup,server.google_headers,{},d,server.LOCATION,server.MODEL,
                                     server.VOICE,str(uuid.uuid4()),hangup=True,search=budget)
    run=asyncio.create_task(session.run())
    out={'build':live_session.BUILD,'per_call':budget.per_call}
    try:
        await wait(lambda:page.events('ready'),30,'ready')
        asked=page.at();page.say({'type':'text','id':'q1','text':QUESTIONS[0]})
        await wait(lambda:page.events('turn'),60,'first answer')
        turn=page.events('turn')[0][0];audio=page.first_audio_after(asked)
        out['q1']={'audio_starts_s':round(audio-asked,2) if audio else None,'turn_complete_s':round(turn-asked,2),'searches':session.searches}
        await wait(lambda:len(page.events('ready'))>=2,60,'resume without search')
        ready=page.events('ready')[1]
        out['moved_after_turn_s']=round(ready[0]-turn,2);out['moved_resumed']=ready[1].get('resumed')
        asked=page.at();page.say({'type':'text','id':'q2','text':QUESTIONS[1]})
        await wait(lambda:len(page.events('turn'))>=2,60,'second answer')
        turn=page.events('turn')[1][0];audio=page.first_audio_after(asked)
        out['q2']={'audio_starts_s':round(audio-asked,2) if audio else None,'turn_complete_s':round(turn-asked,2),'searches_total':session.searches}
        await asyncio.sleep(2)
    except TimeoutError as error:
        out['timeout']=str(error)
    finally:
        page.incoming.put_nowait(None)
        try:await asyncio.wait_for(run,20)
        except Exception as error:out['run_end']=type(error).__name__
    out.update(modes=modes,reconnecting_notices=len(page.events('reconnecting')),
               diagnostics={k:d.get(k) for k in ('webSearches','searchReconnects','providerReconnects')},
               today_left=budget.left(),marong=page.captions('marong'))
    print(json.dumps(out,ensure_ascii=False,indent=1))


if __name__=='__main__':asyncio.run(main())
