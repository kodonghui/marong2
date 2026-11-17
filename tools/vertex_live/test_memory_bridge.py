"""Integration test on a restored, isolated database. Never sends Kakao messages."""
import asyncio,hashlib,json,sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from call_memory import MemoryStore
from organizer import Organizer,AsyncPostgresSaver,extract
from marong.store import Store

from fixture_database import CALL_DSN, BOT_DSN, admin
DSN=CALL_DSN
PREFIX='testvoice_'+uuid.uuid4().hex[:10]
CHECKS=0
def ok(value,label):
    global CHECKS
    assert value,label
    CHECKS+=1
    print('PASS',label,flush=True)
def digest(s):return hashlib.sha256(s.encode()).hexdigest()

async def main():
    # Only synthetic records are read or printed by this test.
    f1=int(admin(f"INSERT INTO marong.friends(name) VALUES('{PREFIX}_owner') RETURNING id;"))
    f2=int(admin(f"INSERT INTO marong.friends(name) VALUES('{PREFIX}_other') RETURNING id;"))
    room=PREFIX+'_private';group=PREFIX+'_linked';other=PREFIX+'_other';unlinked=PREFIX+'_unlinked'
    user=PREFIX+'_u';user2=PREFIX+'_u2'
    admin(f"""
      INSERT INTO marong.rooms(room_key,is_channel,proactive) VALUES('{room}',true,false),('{other}',true,false),('{group}',false,false),('{unlinked}',false,false);
      UPDATE marong.rooms SET memory_room='{room}' WHERE room_key='{group}';
      INSERT INTO marong.people(user_key,name,friend_id) VALUES('{user}','시험사용자',{f1}),('{user2}','시험다른친구',{f2});
      INSERT INTO marong.messages(room_key,user_key,role,content) VALUES
       ('{room}','{user}','user','카톡에서 말한 파란 우산'),('{group}','{user}','user','연결된 방의 노란 꽃'),
       ('{other}','{user2}','user','다른 친구 비밀 자주색'),('{unlinked}','{user}','user','미연결방 비밀 주황색');
      INSERT INTO marong.notes(room_key,user_key,content) VALUES('{room}','{user}','기존에 공유 가능한 민트 취향');
    """)
    c1=int(admin(f"INSERT INTO call.callers(friend_id) VALUES({f1}) RETURNING id;"))
    c2=int(admin(f"INSERT INTO call.callers(friend_id) VALUES({f2}) RETURNING id;"))
    admin(f"INSERT INTO call.caller_logins(caller_id,email_sha256,email_hint) VALUES({c1},'{digest(PREFIX)}','t***'),({c1},'{digest(PREFIX+'alias')}','t***'),({c2},'{digest(PREFIX+'other')}','t***');")
    mem=MemoryStore(DSN);await mem.open()
    bot=Store(BOT_DSN,call_bridge=True);await bot.open(wait=True)
    try:
        p=await mem.principal(digest(PREFIX));q=await mem.principal(digest(PREFIX+'other'))
        ok(p.caller_id==c1 and (await mem.principal(digest(PREFIX+'alias'))).caller_id==c1,'approved aliases resolve one caller')
        ok(await mem.principal(digest('unmapped')) is None,'unmapped identity has no private principal')
        seed=await mem.seed(p)
        ok('파란 우산' in seed and '노란 꽃' in seed and '자주색' not in seed and '주황색' not in seed,'Kakao to voice room scope')
        ok((await mem.recall(p,'우산'))['result']=='found','Kakao recall')
        call,resumed=await mem.start_call(p,str(uuid.uuid4()),'Sulafat','test')
        seg=await mem.start_segment(p,call,str(uuid.uuid4()),'gemini-3.8-live')
        same,again=await mem.start_call(p,str(uuid.uuid4()),'Sulafat','test')
        ok(same==call and again and not resumed,'one logical call survives reconnect')
        await mem.save_turn(p,call,seg,'old-preference','user','예전에는 홍차를 마실 계획이었어')
        old=await mem.remember(p,call,seg,'remember-old','예전에는 홍차를 마실 계획이었어')
        quote='다음 주에는 라벤더 차를 마실 거야'
        tid=await mem.save_turn(p,call,seg,'user-1','user',quote)
        await mem.save_turn(p,call,seg,'ai-1','assistant','사용자는 달나라 여행을 예약했다')
        ok((await mem.remember(p,call,seg,'bad','달나라 여행'))['result']=='not_saved','assistant hallucination cannot be remembered')
        saved=await mem.remember(p,call,seg,'remember-1',quote,[old['memory_id']])
        ok(saved['result']=='saved','verified user quote saved')
        ok((await mem.one('SELECT superseded_by FROM call.memories WHERE id=%s',(old['memory_id'],)))['superseded_by']==saved['memory_id'],'explicit correction supersedes an old memory')
        ok(await mem.remember(p,call,seg,'remember-1',quote)==saved,'remember operation is idempotent')
        ok(quote not in await mem.seed(q),'other caller cannot read memory')
        try:await mem.detail(q,call);raise AssertionError('IDOR')
        except PermissionError:ok(True,'call detail denies other caller')
        ctx=await bot.call_context(room,user)
        ok(quote in json.dumps(ctx,ensure_ascii=False),'voice to Kakao 1:1 context')
        from marong.agent import Agent,Incoming
        from marong.config import load_settings
        from types import SimpleNamespace
        from dataclasses import replace
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tests'))
        from fakes import ScriptedLLM,message,text
        llm=ScriptedLLM(lambda body:message([text('시험용 답변')]))
        settings=replace(load_settings(),group_triggers=())
        agent=Agent(settings,bot,SimpleNamespace(ready=False),llm)
        sent=[]
        async def fake_send(answer):sent.append(answer);return True
        await agent.handle(Incoming(room,user,'아까 통화 취향 기억해?'),fake_send)
        ok(quote in json.dumps(llm.bodies[-1],ensure_ascii=False),'actual Kakao Agent prompt includes own voice memory')
        await agent.handle(Incoming(group,user,'마롱아 안녕',is_channel=False),fake_send)
        ok(quote not in json.dumps(llm.bodies[-1],ensure_ascii=False),'actual Kakao Agent group prompt excludes voice memory')
        ok(len(sent)==2,'Kakao integration exercised with fake delivery only')
        ok(not await bot.call_context(group,user) and not await bot.call_context(other,user2),'no group or other-person injection')
        bot.call_context_enabled=False
        ok(not await bot.call_context(room,user),'injection can stop without disabling privacy guards')
        bot.call_context_enabled=True
        admin(f"""INSERT INTO marong.messages(room_key,role,content) VALUES('{room}','assistant','라벤더 통화기억에서 나온 답변');
          INSERT INTO marong.notes(room_key,user_key,content) VALUES('{room}','{user}','라벤더 파생 비공개 메모');""")
        ok(any('라벤더' in x['content'] for x in await bot.recent(room,20)),'own Kakao room can continue voice memory')
        ok(not any('라벤더' in x['content'] for x in await bot.recent(group,20)),'linked group cannot read private derived messages')
        shared=[x for x in await bot.friend_notes() if x['friend_id']==f1]
        ok(shared and all('라벤더' not in x['content'] for x in shared),'shared-note worker retains safe pre-bridge notes')
        await mem.finish(p,call,True)
        async def fake_extract(turns):return {'summary':'모델이 지어낸 요약','memories':[{'quote':quote},{'quote':'지어낸 여행 예약'}]},{}
        worker=Organizer(mem,fake_extract)
        async with AsyncPostgresSaver.from_conn_string(DSN+" options='-c search_path=call_graph,public'") as saver:
            await saver.setup()
            state={'call_id':call,'caller_id':c1,'revision':0,'saved':0}
            out=await worker.graph(saver).ainvoke(state,{'configurable':{'thread_id':'call:'+call}})
            ok(out['saved']==1,'LangGraph persists only transcript-grounded candidates')
            card=await mem.one('SELECT summary FROM call.cards WHERE call_id=%s',(call,))
            ok(card['summary']==quote,'card cannot promote an invented model summary')
            ok(len(await mem.list_memories(p))==1,'explicit and organizer memory deduplicate')
            # Delete while an organizer is generating: revision must invalidate its write.
            stale=await worker.load(state)
            forgotten=await mem.forget(p,[saved['memory_id']])
            ok(forgotten['result']=='forgotten','forget succeeds')
            await bot.add_message(room,'assistant','라벤더 늦게 도착한 답변',meta={'memory':{'call_revision':0}})
            ok(not any('늦게 도착한' in x['content'] for x in await bot.recent(room,20)),'stale Kakao reply excluded after forget')
            await bot.add_notes(room,{user:'라벤더 늦게 도착한 과거 메모'},999999,private_revision=0)
            ok(not any('늦게 도착한' in x['content'] for x in await bot.notes(room)),'in-flight Kakao summarizer cannot resurrect forgotten memory')
            ok(quote not in await mem.seed(p) and (await mem.recall(p,'라벤더'))['result']=='not_found','forgotten fact absent from all voice retrieval')
            ok(not any('라벤더' in x['content'] for x in await bot.recent(room,20)),'forgotten derived Kakao messages excluded')
            ok(not any('라벤더' in x['content'] for x in await bot.notes(room)),'forgotten derived Kakao notes excluded')
            ok(quote not in json.dumps(await mem.detail(p,call),ensure_ascii=False,default=str),'forgotten transcript hidden in history UI')
            try:await worker.organize(state|stale);raise AssertionError('stale revision wrote')
            except ValueError as e:ok(str(e)=='context_changed','stale organizer cannot resurrect deleted memory')
            await worker.maintenance()
            ok(True,'retention sweep and checkpoint cleanup run')
        await mem.delete_call(p,call)
        ok(not await mem.list_calls(p),'delete removes call and its descendants')
        permissions=admin("SELECT has_table_privilege('marong_call','marong.messages','UPDATE'),has_table_privilege('marong','call.turns','SELECT');")
        ok(permissions=='f|f','database roles enforce raw Kakao and transcript boundaries')
        if os.environ.get('REAL_VERTEX_TEST')=='1':
            result,usage=await extract([{'role':'user','content':'나는 캐모마일 차를 좋아해. 다음에도 기억해 줘.'}])
            ok(bool(result.get('memories')) and bool(usage.get('promptTokenCount')),'real Vertex organizer API and structured output')
        print(json.dumps({'checks':CHECKS,'fixture':PREFIX,'externalKakaoMessagesSent':0}),flush=True)
    finally:
        await bot.close();await mem.close()

if __name__=='__main__':asyncio.run(main())
