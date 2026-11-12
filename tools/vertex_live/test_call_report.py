"""Call metadata reporting on the isolated restored DB. No external Sheet writes."""
import asyncio,json,os,subprocess,sys,uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import psycopg
from psycopg.rows import dict_row
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.report import call_sessions
from call_memory import MemoryStore,Principal

DB=os.environ.get('TEST_DATABASE','marong_voice_verify_20261112')
assert DB.startswith('marong_voice_verify_')
def admin(sql):
    r=subprocess.run(['sudo','-n','-u','postgres','psql','-X','-q','-At','-v','ON_ERROR_STOP=1','-d',DB],input=sql,text=True,capture_output=True)
    if r.returncode:raise RuntimeError(r.stderr)
    return r.stdout.strip()

async def main():
    name='testreport_'+uuid.uuid4().hex
    friend=int(admin(f"INSERT INTO marong.friends(name) VALUES('{name}') RETURNING id"))
    caller=int(admin(f"INSERT INTO call.callers(friend_id) VALUES({friend}) RETURNING id"))
    p=Principal(caller,friend,name);store=MemoryStore(f'dbname={DB} user=marong_call');await store.open()
    try:
        call,_=await store.start_call(p,str(uuid.uuid4()),'Sulafat','test-report')
        first=await store.start_segment(p,call,str(uuid.uuid4()),'gemini-3.8-live')
        await store.save_turn(p,call,first,'private-test','user','PRIVATE_VOICE_CONTENT_MUST_NOT_REACH_SHEET')
        conn=str(uuid.uuid4());await store.record_transport(p,call,conn,'webrtc','start')
        for _ in range(3):await store.record_transport(p,call,conn,'pcm','rtc_media_stalled')
        second=await store.start_segment(p,call,str(uuid.uuid4()),'gemini-3.8-live')
        await store.record_transport(p,call,str(uuid.uuid4()),'pcm','start')
        await store.finish(p,call,True)
        admin(f"""UPDATE call.calls SET started_at='2040-01-01 01:00+09',ended_at='2040-01-01 01:11+09' WHERE id='{call}';
          UPDATE call.segments SET opened_at='2040-01-01 01:00+09',closed_at='2040-01-01 01:00:30+09' WHERE id='{first}';
          UPDATE call.segments SET opened_at='2040-01-01 01:10+09',closed_at='2040-01-01 01:11+09' WHERE id='{second}';""")
        tz=ZoneInfo('Asia/Seoul');start=datetime(2040,1,1,tzinfo=tz);until=datetime(2040,1,2,tzinfo=tz)
        def report():
            with psycopg.connect(f'dbname={DB} user=marong',row_factory=dict_row) as c:
                c.read_only=True
                return call_sessions(c,start,until,tz)
        tab=report();matched=[r for r in tab['rows'] if r[0]==call];assert len(matched)==1
        row=matched[0]
        assert row[:6]==[call,'2040-01-01 01:00:00','2040-01-01 01:11:00','종료',90.0,2],row
        assert row[6:9]==['WebRTC','WebSocket PCM',1],row
        assert report()==tab,'refresh duplicated or changed a closed session'
        assert name not in json.dumps(tab) and 'PRIVATE_VOICE_CONTENT' not in json.dumps(tab)
        with psycopg.connect(f'dbname={DB} user=marong',autocommit=True) as c:
            try:c.execute('SELECT content FROM call.turns LIMIT 1');raise AssertionError('report role can read transcript')
            except psycopg.errors.InsufficientPrivilege:pass
        admin(f"UPDATE call.calls SET deleted_at=now() WHERE id='{call}'")
        assert not any(r[0]==call for r in report()['rows']),'deleted call stayed in Sheet'
        print('PASS one row per logical call, two provider segments, gap excluded, one idempotent fallback, KST times, repeat refresh, deleted exclusion and no voice-content access')
    finally:
        await store.close()
        admin(f"DELETE FROM call.calls WHERE caller_id={caller}; DELETE FROM call.callers WHERE id={caller}; DELETE FROM marong.friends WHERE id={friend};")

asyncio.run(main())
