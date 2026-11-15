"""Natural voice -> automatic call summary -> Kakao, using isolated fixtures."""
import asyncio,audioop,base64,json,os,struct,time,uuid
from pathlib import Path
from unittest.mock import AsyncMock,patch
import aiohttp
from aiohttp.test_utils import TestClient,TestServer
from test_memory_bridge import admin,digest,DB
os.environ['MARONG_CALL_DSN']=f'dbname={DB} user=marong_call'
import server
from organizer import Organizer
from marong.store import Store

async def source_audio_once():
    config=server.setup()
    config['setup']['systemInstruction']={'parts':[{'text':'사용자가 준 한국어 문장을 정확히 그대로 읽어. 다른 말은 하지 마.'}]}
    pcm=bytearray()
    url=f'wss://{server.LOCATION}-aiplatform.googleapis.com/ws/google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent'
    async with aiohttp.ClientSession() as h,h.ws_connect(url,headers=await server.google_headers()) as w:
        await w.send_json(config)
        assert 'setupComplete' in json.loads((await w.receive(timeout=20)).data)
        await w.send_json({'clientContent':{'turns':[{'role':'user','parts':[{'text':'나는 잠들기 전에 캐모마일 차를 마시는 걸 좋아해.'}]}],'turnComplete':True}})
        while True:
            m=await w.receive(timeout=30);assert m.type in (aiohttp.WSMsgType.TEXT,aiohttp.WSMsgType.BINARY)
            c=json.loads(m.data).get('serverContent',{})
            for part in c.get('modelTurn',{}).get('parts',[]):
                d=part.get('inlineData',{})
                if d.get('data'):pcm.extend(base64.b64decode(d['data']))
            if c.get('turnComplete'):break
    return bytes(pcm)

async def source_audio():
    # Some provider turns finish without audio. Retry fixture generation only;
    # the actual ASR, automatic organization and retrieval assertions are not retried.
    for attempt in range(3):
        pcm=await source_audio_once()
        if len(pcm)>48000:return audioop.ratecv(pcm,2,1,24000,16000,None)[0]
        print('Synthetic speech fixture too short; retry',attempt+1,len(pcm)//48,'ms',flush=True)
    raise AssertionError('Provider did not generate a usable synthetic speech fixture')

async def until(w,kind):
    packets=[];transcripts=[];start=time.monotonic()
    while time.monotonic()-start<60:
        m=await w.receive(timeout=45)
        if m.type==aiohttp.WSMsgType.BINARY:
            magic,epoch,turn,seq,offset,count=struct.unpack('!4sIIIII',m.data[:24]);assert magic==b'MRG2'
            packets.append({'at':time.monotonic()-start,'pcm':base64.b64encode(m.data[24:]).decode()})
        else:
            assert m.type==aiohttp.WSMsgType.TEXT,(m.type,m.extra)
            d=json.loads(m.data)
            if d.get('type')=='transcript':transcripts.append(d)
            if d.get('type')==kind and (kind!='turn' or packets):return d,packets,transcripts
    raise AssertionError('event timeout '+kind)

async def main():
    name='audioverify_'+uuid.uuid4().hex[:8];room=name+'_room';user=name+'_user'
    friend=int(admin(f"INSERT INTO marong.friends(name) VALUES('{name}') RETURNING id;"))
    caller=int(admin(f"INSERT INTO call.callers(friend_id) VALUES({friend}) RETURNING id;"))
    admin(f"""INSERT INTO call.caller_logins(caller_id,email_sha256,email_hint) VALUES({caller},'{digest(name)}','a***');
      INSERT INTO marong.rooms(room_key,is_channel,proactive) VALUES('{room}',true,false);
      INSERT INTO marong.people(user_key,name,friend_id) VALUES('{user}','음성시험친구',{friend});
      INSERT INTO marong.messages(room_key,user_key,role,content) VALUES('{room}','{user}','user','내 시험용 우산은 파란색이야');""")
    pcm=await source_audio();print('PASS synthetic speech generated',len(pcm)//32,'ms',flush=True)
    with patch.object(server,'identity',AsyncMock(return_value={'owner':name,'email_hash':digest(name)})):
        async with TestClient(TestServer(server.app)) as c:
            origin=str(c.make_url('/')).rstrip('/');headers={'Origin':origin}
            w=await c.ws_connect('/live?client=00000000-0000-4000-8000-000000000001',headers=headers)
            ready,_,_=await until(w,'ready');assert ready['memoryConnected'];call=ready['callId']
            # Real microphone framing and pacing, including trailing silence for VAD.
            for i in range(0,len(pcm),3200):await w.send_bytes(pcm[i:i+3200]);await asyncio.sleep(.1)
            for _ in range(15):await w.send_bytes(bytes(3200));await asyncio.sleep(.1)
            _,packets,captions=await until(w,'turn')
            await asyncio.sleep(1)
            p=await server.memory_store.principal(digest(name))
            turns=await server.memory_store.detail(p,call)
            print(json.dumps({'syntheticTranscripts':[(t['role'],t['content'],t['finalized']) for t in turns['turns']],
                'audioPackets':len(packets)},ensure_ascii=False),flush=True)
            assert any(t['role']=='user' and t['finalized'] and '캐모마일' in t['content'] for t in turns['turns'])
            assert not await server.memory_store.list_memories(p),'No user-command save path is expected'
            assert packets
            Path('probe-packets.json').write_text(json.dumps(packets),encoding='utf8')
            await w.send_json({'type':'text','text':'카톡에서 말한 내 우산은 무슨 색이야?'});_,_,reply=await until(w,'turn')
            assert any('파란' in t['text'] for t in reply if t['who']=='marong'),'Kakao seed not used by live model'
            await w.send_json({'type':'stop'});await w.receive();await w.close();await asyncio.sleep(.3)
            row=await server.memory_store.one('SELECT status FROM call.calls WHERE id=%s',(call,));assert row['status']=='ended'
            worker=Organizer(server.memory_store)
            state={'call_id':call,'caller_id':caller,'revision':0,'saved':0}
            state.update(await worker.load(state));await worker.organize(state)
            assert await server.memory_store.one('SELECT 1 FROM call.cards WHERE call_id=%s',(call,))
            memories=await server.memory_store.list_memories(p)
            assert any('캐모마일' in m['content'] for m in memories),'Natural preference was not automatically organized'
            bot=Store(f'dbname={DB} user=marong',call_bridge=True);await bot.open(wait=True)
            try:
                assert '캐모마일' in json.dumps(await bot.call_context(room,user),ensure_ascii=False)
                from marong.agent import Agent,Incoming
                from marong.config import load_settings
                from types import SimpleNamespace
                from dataclasses import replace
                import sys
                sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tests'))
                from fakes import ScriptedLLM,message,text
                llm=ScriptedLLM(lambda body:message([text('시험용 답변')]))
                agent=Agent(replace(load_settings(),group_triggers=()),bot,SimpleNamespace(ready=False),llm)
                sent=[]
                async def fake_send(answer):sent.append(answer);return True
                await agent.handle(Incoming(room,user,'내가 잠들기 전에 마시는 차가 뭐였지?'),fake_send)
                assert '캐모마일' in json.dumps(llm.bodies[-1],ensure_ascii=False) and len(sent)==1
            finally:await bot.close()
            await server.memory_store.delete_call(p,call)
            print('PASS natural Korean speech -> real ASR -> automatic organizer -> PostgreSQL -> actual Kakao Agent prompt; Kakao -> live answer; no save/delete commands; no external Kakao messages; Sulafat unchanged',flush=True)

if __name__=='__main__':asyncio.run(main())
