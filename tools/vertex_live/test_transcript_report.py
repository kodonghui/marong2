"""Private transcript export on the isolated restored DB; never calls the bot or Sheets."""
import asyncio,sys,uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import psycopg
from psycopg.rows import dict_row
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.report import build,workbook,FRIEND_COLOR,MARONG_COLOR
from call_memory import MemoryStore,Principal

from fixture_database import CALL_DSN, BOT_DSN, admin
CHECKS=0
def ok(value,label):
    global CHECKS
    assert value,label
    CHECKS+=1;print('PASS',label,flush=True)

async def main():
    prefix='report_asr_'+uuid.uuid4().hex
    friend=int(admin(f"INSERT INTO marong.friends(name) VALUES('{prefix}') RETURNING id"))
    caller=int(admin(f"INSERT INTO call.callers(friend_id) VALUES({friend}) RETURNING id"))
    admin(f"INSERT INTO marong.rooms(room_key,is_channel,proactive) VALUES('{prefix}',true,false);")
    kakao=int(admin(f"INSERT INTO marong.messages(room_key,role,content,created_at) VALUES('{prefix}','user','KAKAO_FIXTURE','2001-01-02 10:00:10+09') RETURNING id;"))
    p=Principal(caller,friend,prefix);store=MemoryStore(CALL_DSN);await store.open()
    try:
        call,_=await store.start_call(p,str(uuid.uuid4()),'Sulafat','report-only-test')
        seg=await store.start_segment(p,call,str(uuid.uuid4()),'gemini-3.8-live')
        ids={}
        for key,role,content,finalized,interrupted,at in [
            ('asr','user','전사 중인 말',False,False,'10:00:00'),
            ('answer','assistant','확정된 마롱이 응답',True,False,'10:00:20'),
            ('stopped','assistant','중간에 멈춘 응답',True,True,'10:00:30'),
            ('hidden','user','DO_NOT_EXPORT_FORGOTTEN',True,False,'10:00:40'),
            ('text:typed','user','=1+1',True,False,'10:00:15'),
            ('blank','user','will become whitespace',True,False,'10:00:45'),
            ('outside','user','OUTSIDE_WINDOW',True,False,'11:00:00')]:
            tid=await store.save_turn(p,call,seg,key,role,content,finalized,interrupted);ids[key]=tid
            admin(f"UPDATE call.turns SET started_at='2001-01-02 {at}+09',ended_at='2001-01-02 {at}+09' WHERE id={tid};")
        admin(f"UPDATE call.turns SET forgotten_at=now() WHERE id={ids['hidden']}; UPDATE call.turns SET content=' ' WHERE id={ids['blank']};")
        tz=ZoneInfo('Asia/Seoul');start=datetime(2001,1,2,10,tzinfo=tz);until=datetime(2001,1,2,11,tzinfo=tz)
        def snapshot():
            with psycopg.connect(BOT_DSN,row_factory=dict_row) as c:
                c.read_only=True
                return build(c,start,until,tz,now=until,vectors=False)
        before=admin(f"SELECT count(*) FROM marong.messages WHERE room_key='{prefix}'")
        tabs,counts=snapshot();talk=next(t for t in tabs if t['name']=='대화');rows=talk['rows']
        expected=[f"V{ids[k]}" for k in ['stopped','answer','text:typed']]+[kakao,f"V{ids['asr']}"]
        ok([r[0] for r in rows]==expected,'Kakao and voice merge by timestamp with collision-free V IDs')
        ok(all(len(r)==15 for r in rows) and len(talk['headers'])==15,'existing conversation columns remain aligned')
        byid={r[0]:r for r in rows};draft=byid[f"V{ids['asr']}"]
        ok(draft[3]==prefix and draft[4]=='통화(전사 중)','speaker and draft transcription label')
        answer=byid[f"V{ids['answer']}"]
        ok(answer[3]=='마롱이' and answer[4]=='통화(응답)' and answer[8]=='gemini-3.8-live','model output and provider label')
        ok(answer[7]=='미확인' and answer[9:14]==[None]*5 and answer[14]=='미집계','no invented playback, token or retrieval counts')
        ok(byid[f"V{ids['stopped']}"][4]=='통화(중단)' and byid[f"V{ids['text:typed']}"][4]=='통화(글)','interrupted and typed turns distinguished')
        ok(talk['colors']==[MARONG_COLOR,MARONG_COLOR,FRIEND_COLOR,FRIEND_COLOR,FRIEND_COLOR],'row colors follow speaker after merge')
        ok(counts['call_transcripts']==4 and counts['messages']==1,'Kakao statistics do not absorb call transcripts')
        wb=workbook(tabs);ws=wb['대화'];formula_row=next(i for i in range(2,ws.max_row+1) if ws.cell(i,1).value==f"V{ids['text:typed']}")
        ok(ws.cell(formula_row,6).data_type=='s','transcript starting with equals remains literal text')
        updated=await store.save_turn(p,call,seg,'asr','user','전사가 완성된 말',True,False)
        changed,_=snapshot();updated_rows=next(t for t in changed if t['name']=='대화')['rows']
        final=next(r for r in updated_rows if r[0]==f'V{updated}')
        ok(updated==ids['asr'] and len(updated_rows)==5 and final[4]=='통화(전사)' and final[5]=='전사가 완성된 말','partial updates replace the same row without duplication')
        ok(snapshot()==(changed,_),'repeated refresh is idempotent')
        ok(admin(f"SELECT count(*) FROM marong.messages WHERE room_key='{prefix}'")==before,'report never writes transcripts into Kakao storage')
        with psycopg.connect(BOT_DSN,autocommit=True) as c:
            try:c.execute('SELECT content FROM call.turns LIMIT 1');raise AssertionError('raw transcript-table access granted')
            except psycopg.errors.InsufficientPrivilege:pass
            ok(not c.execute("SELECT has_table_privilege(current_user,'call.transcript_report','INSERT,UPDATE,DELETE')").fetchone()[0],
               'report role cannot write through transcript view')
            columns=[d.name for d in c.execute('SELECT * FROM call.transcript_report LIMIT 0').description]
            ok(not any(k in columns for k in ['email_sha256','email_hint','client_id','caller_id','friend_id','turn_key']),'view omits login IDs and internal keys; raw/read-write privileges stay denied')
        admin(f"UPDATE call.calls SET deleted_at=now() WHERE id='{call}'")
        deleted,_=snapshot();ok([r[0] for r in next(t for t in deleted if t['name']=='대화')['rows']]==[kakao],'deleted call and excluded/blank/out-of-range turns do not export')
        print({'checks':CHECKS,'externalMessagesSent':0,'liveServiceRestarts':0})
    finally:
        await store.close()
        admin(f"DELETE FROM call.calls WHERE caller_id={caller}; DELETE FROM call.callers WHERE id={caller}; DELETE FROM marong.friends WHERE id={friend}; DELETE FROM marong.messages WHERE room_key='{prefix}'; DELETE FROM marong.rooms WHERE room_key='{prefix}';")

asyncio.run(main())
