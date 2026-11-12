"""Caller-scoped PostgreSQL memory. Never used synchronously in the PCM loop."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool


@dataclass(frozen=True)
class Principal:
    caller_id: int
    friend_id: int
    name: str
    revision: int = 0


SCOPE = """WITH roots AS (
 SELECT r.room_key FROM marong.rooms r WHERE r.is_channel AND EXISTS (
  SELECT 1 FROM marong.messages m JOIN marong.people p USING(user_key)
  WHERE m.room_key=r.room_key AND m.role='user' AND p.friend_id=%(friend)s)
), rooms AS (
 SELECT r.room_key FROM marong.rooms r WHERE r.room_key IN (SELECT room_key FROM roots)
 OR r.memory_room IN (SELECT room_key FROM roots)
) """


def normalized(text):
    return ' '.join(str(text).split())


def quoted(quote, text):
    return bool(quote) and normalized(quote) in normalized(text)


def pack(items, budget):
    """Keep whole source items, truncating only a single overlong source."""
    result = []
    for item in items:
        data = dict(item)
        data['text'] = str(data.pop('content', data.get('text', '')))
        overhead = len(json.dumps({k: v for k, v in data.items() if k != 'text'}, ensure_ascii=False, default=str)) + 20
        room = budget - overhead
        if room < 30:
            break
        data['text'] = data['text'][:room]
        result.append(data)
        budget -= len(json.dumps(data, ensure_ascii=False, default=str))
    return result


class MemoryStore:
    def __init__(self, dsn):
        self.pool = AsyncConnectionPool(dsn, min_size=1, max_size=4, open=False, timeout=2,
            kwargs={'autocommit': True, 'row_factory': dict_row, 'options': '-c statement_timeout=2500'})

    async def open(self):
        await self.pool.open(wait=True, timeout=5)
        row = await self.one("SELECT value FROM call.meta WHERE key='schema_version'")
        if not row or row['value'] != '2':
            raise RuntimeError('call_schema_version')

    async def close(self):
        await self.pool.close()

    async def all(self, sql, params=()):
        async with self.pool.connection() as c:
            cur = await c.execute(sql, params)
            return await cur.fetchall()

    async def one(self, sql, params=()):
        rows = await self.all(sql, params)
        return rows[0] if rows else None

    async def principal(self, email_hash):
        row = await self.one("""SELECT c.id AS caller_id,c.friend_id,f.name,c.context_revision
            FROM call.caller_logins l JOIN call.callers c ON c.id=l.caller_id
            JOIN marong.friends f ON f.id=c.friend_id WHERE l.email_sha256=%s AND c.enabled""", (email_hash,))
        return Principal(row['caller_id'], row['friend_id'], row['name'], row['context_revision']) if row else None

    async def revision(self, p):
        row = await self.one('SELECT context_revision FROM call.callers WHERE id=%s AND enabled', (p.caller_id,))
        return row['context_revision'] if row else -1

    @staticmethod
    def params(p):
        return {'friend': p.friend_id, 'caller': p.caller_id}

    async def seed(self, p, call_id=None):
        params = self.params(p)
        notes = await self.all(SCOPE + """SELECT * FROM (
          SELECT DISTINCT ON(n.user_key) n.id,n.content,n.created_at,'kakao_note' AS source
          FROM marong.notes n JOIN marong.people p ON p.user_key=n.user_key
          WHERE n.room_key IN (SELECT room_key FROM rooms) AND p.friend_id=%(friend)s
          AND NOT call.kakao_hidden('note',n.id,n.room_key)
          AND NOT EXISTS(SELECT 1 FROM call.source_exclusions x WHERE x.caller_id=%(caller)s AND x.source_type='kakao_note' AND x.source_id=n.id::text)
          ORDER BY n.user_key,(n.room_key IN (SELECT room_key FROM roots)) DESC,n.id DESC
        ) n ORDER BY id DESC LIMIT 4""", params)
        summaries = await self.all(SCOPE + """SELECT id,content,created_at,'kakao_summary' AS source
          FROM marong.summaries s WHERE room_key IN (SELECT room_key FROM rooms) AND content<>''
          AND NOT call.kakao_hidden('summary',id,room_key)
          AND NOT EXISTS(SELECT 1 FROM call.source_exclusions x WHERE x.caller_id=%(caller)s AND x.source_type='kakao_summary' AND x.source_id=s.id::text)
          ORDER BY last_id DESC LIMIT 3""", params)
        recent = await self.all(SCOPE + """SELECT m.id,m.role,m.content,m.created_at,'kakao_message' AS source
          FROM marong.messages m WHERE room_key IN (SELECT room_key FROM rooms)
          AND m.meta->>'delivered' IS DISTINCT FROM 'false' AND NOT call.kakao_hidden('message',id,room_key)
          AND NOT EXISTS(SELECT 1 FROM call.source_exclusions x WHERE x.caller_id=%(caller)s AND x.source_type='kakao_message' AND x.source_id=m.id::text)
          ORDER BY id DESC LIMIT 10""", params)
        # Other people contribute only the existing, explicitly shared notes.
        friends = await self.all("""SELECT f.name,fs.label,s.content,
          CASE WHEN fs.close THEN s.close_content ELSE '' END AS close_content
          FROM marong.friendships fs JOIN marong.friends f
            ON f.id=CASE WHEN fs.friend_a=%s THEN fs.friend_b ELSE fs.friend_a END
          LEFT JOIN LATERAL(SELECT content,close_content FROM marong.shared_notes WHERE friend_id=f.id ORDER BY id DESC LIMIT 1) s ON true
          WHERE %s IN(fs.friend_a,fs.friend_b) AND f.share ORDER BY f.id LIMIT 8""", (p.friend_id,p.friend_id))
        for row in friends:
            row['content'] = (row['content'] or '') + '\n' + (row.pop('close_content') or '')
        memories = await self.all("""SELECT m.id,m.content,m.created_at,'call_memory' AS source FROM call.memories m
          JOIN call.calls c ON c.id=m.call_id WHERE m.caller_id=%s AND m.status='active' AND c.deleted_at IS NULL
          ORDER BY m.created_at DESC LIMIT 30""", (p.caller_id,))
        cards = await self.all("""SELECT c.id,k.summary AS content,k.created_at,'call_card' AS source
          FROM call.cards k JOIN call.calls c ON c.id=k.call_id WHERE c.caller_id=%s AND c.deleted_at IS NULL
          AND k.forgotten_at IS NULL ORDER BY c.started_at DESC LIMIT 3""", (p.caller_id,))
        history = []
        if call_id:
            history = await self.all("""SELECT t.id,t.role,t.content,t.started_at,'current_call' AS source
              FROM call.turns t JOIN call.calls c ON c.id=t.call_id
              WHERE c.caller_id=%s AND c.id=%s AND c.deleted_at IS NULL
              AND t.forgotten_at IS NULL AND t.finalized AND NOT t.interrupted ORDER BY t.seq DESC LIMIT 40""", (p.caller_id,call_id))
        payload = {'friend': p.name, 'kakao_notes': pack(notes,1000), 'kakao_summaries': pack(summaries,1500),
            'kakao_recent': list(reversed(pack(recent,1500))), 'shared_friends': pack(friends,1500),
            'call_memories': pack(memories,1500), 'call_cards': pack(cards,1500),
            'current_call': list(reversed(pack(history,4000)))}
        return json.dumps(payload,ensure_ascii=False,default=str)

    async def recall(self,p,query):
        query=normalized(query)[:100]
        if len(query)<2:return {'result':'ask_which','items':[]}
        q='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        params=self.params(p)|{'q':q}
        rows=await self.all(SCOPE+"""SELECT * FROM (
          SELECT 'kakao_message' AS source,m.id::text AS id,m.content,m.created_at FROM marong.messages m
          WHERE m.room_key IN(SELECT room_key FROM rooms) AND m.content ILIKE %(q)s
          AND m.meta->>'delivered' IS DISTINCT FROM 'false' AND NOT call.kakao_hidden('message',m.id,m.room_key)
          UNION ALL SELECT 'kakao_note',n.id::text,n.content,n.created_at FROM marong.notes n JOIN marong.people p USING(user_key)
          WHERE n.room_key IN(SELECT room_key FROM rooms) AND p.friend_id=%(friend)s AND n.content ILIKE %(q)s
          AND NOT call.kakao_hidden('note',n.id,n.room_key)
          UNION ALL SELECT 'kakao_summary',s.id::text,s.content,s.created_at FROM marong.summaries s
          WHERE s.room_key IN(SELECT room_key FROM rooms) AND s.content ILIKE %(q)s
          AND NOT call.kakao_hidden('summary',s.id,s.room_key)
          UNION ALL SELECT 'call_memory',m.id::text,m.content,m.created_at FROM call.memories m
          JOIN call.calls c ON c.id=m.call_id WHERE m.caller_id=%(caller)s AND m.status='active'
          AND c.deleted_at IS NULL AND m.content ILIKE %(q)s
          UNION ALL SELECT 'call_card',c.id::text,k.summary,k.created_at FROM call.cards k JOIN call.calls c ON c.id=k.call_id
          WHERE c.caller_id=%(caller)s AND c.deleted_at IS NULL AND k.forgotten_at IS NULL AND k.summary ILIKE %(q)s
        ) hits WHERE NOT EXISTS(SELECT 1 FROM call.source_exclusions x WHERE x.caller_id=%(caller)s
          AND x.source_type=hits.source AND x.source_id=hits.id) ORDER BY created_at DESC LIMIT 12""", params)
        return {'result':'found' if rows else 'not_found','items':pack(rows,3000)}

    async def start_call(self,p,client_id,voice,prompt_version):
        async with self.pool.connection() as c, c.transaction():
            await c.execute('SELECT id FROM call.callers WHERE id=%s FOR UPDATE',(p.caller_id,))
            cur=await c.execute("SELECT id FROM call.calls WHERE caller_id=%s AND status<>'ended' AND deleted_at IS NULL",(p.caller_id,))
            row=await cur.fetchone()
            if row:
                await c.execute("UPDATE call.calls SET status='live',client_id=%s,last_beat_at=now() WHERE id=%s",(client_id,row['id']))
                return str(row['id']),True
            cur=await c.execute("INSERT INTO call.calls(caller_id,client_id,prompt_version,voice) VALUES(%s,%s,%s,%s) RETURNING id",(p.caller_id,client_id,prompt_version,voice))
            return str((await cur.fetchone())['id']),False

    async def start_segment(self,p,call_id,client_id,model):
        segment=str(uuid.uuid4())
        async with self.pool.connection() as c,c.transaction():
            await self._owned(c,p,call_id)
            await c.execute("UPDATE call.segments SET state='closed',closed_at=now(),close_reason='connection_lost' WHERE call_id=%s AND state<>'closed'",(call_id,))
            await c.execute("""INSERT INTO call.segments(id,call_id,mode,client_id,state,provider,provider_model,provider_ready_at)
                VALUES(%s,%s,'reconnect',%s,'open','vertex',%s,now())""",(segment,call_id,client_id,model))
        return segment

    async def _owned(self,c,p,call_id):
        cur=await c.execute('SELECT * FROM call.calls WHERE id=%s AND caller_id=%s AND deleted_at IS NULL FOR UPDATE',(call_id,p.caller_id))
        row=await cur.fetchone()
        if not row:raise PermissionError('call_not_found')
        return row

    async def save_turn(self,p,call_id,segment,key,role,content,finalized=True,interrupted=False):
        content=content.strip()[:4000]
        if not content:return None
        async with self.pool.connection() as c,c.transaction():
            await self._owned(c,p,call_id)
            cur=await c.execute('SELECT id FROM call.turns WHERE call_id=%s AND turn_key=%s',(call_id,key))
            existing=await cur.fetchone()
            if existing:
                await c.execute("UPDATE call.turns SET content=%s,finalized=%s,interrupted=%s,revision=revision+1,ended_at=now() WHERE id=%s AND forgotten_at IS NULL",(content,finalized,interrupted,existing['id']))
                return existing['id']
            cur=await c.execute('UPDATE call.calls SET next_seq=next_seq+1,last_beat_at=now() WHERE id=%s RETURNING next_seq',(call_id,))
            seq=(await cur.fetchone())['next_seq']
            cur=await c.execute("""INSERT INTO call.turns(call_id,segment_id,seq,role,content,started_at,ended_at,turn_key,finalized,interrupted)
                VALUES(%s,%s,%s,%s,%s,now(),now(),%s,%s,%s) RETURNING id""",(call_id,segment,seq,role,content,key,finalized,interrupted))
            return (await cur.fetchone())['id']

    async def finish(self,p,call_id,explicit):
        async with self.pool.connection() as c,c.transaction():
            row=await self._owned(c,p,call_id)
            if row['status']=='ended':return
            await c.execute("UPDATE call.segments SET state='closed',closed_at=now(),close_reason=%s WHERE call_id=%s AND state<>'closed'",('user_hangup' if explicit else 'connection_lost',call_id))
            if explicit:
                await c.execute("UPDATE call.calls SET status='ended',ended_at=now(),end_reason='hangup',organize_status='pending',organize_next_at=now() WHERE id=%s",(call_id,))
            else:await c.execute("UPDATE call.calls SET status='resting',last_beat_at=now() WHERE id=%s",(call_id,))

    async def record_transport(self,p,call_id,connection_id,mode,reason):
        async with self.pool.connection() as c,c.transaction():
            await self._owned(c,p,call_id)
            await c.execute("""INSERT INTO call.transport_events(call_id,connection_id,mode,reason)
                VALUES(%s,%s,%s,%s) ON CONFLICT(connection_id,mode) DO NOTHING""",
                (call_id,connection_id,mode,reason))

    async def remember(self,p,call_id,segment,key,quote,replaces=()):
        quote=normalized(quote)
        if not 2<=len(quote)<=200:return {'result':'not_saved','reason':'quote_length'}
        async with self.pool.connection() as c,c.transaction():
            await c.execute('SELECT id FROM call.callers WHERE id=%s FOR UPDATE',(p.caller_id,))
            await self._owned(c,p,call_id)
            old=await self._operation(c,call_id,key)
            if old:return old
            cur=await c.execute("SELECT id,content FROM call.turns WHERE call_id=%s AND role='user' AND finalized AND NOT interrupted AND forgotten_at IS NULL ORDER BY seq DESC LIMIT 40",(call_id,))
            turn=next((t for t in await cur.fetchall() if quoted(quote,t['content'])),None)
            if not turn:return {'result':'not_saved','reason':'unverified_quote'}
            idem=hashlib.sha256((call_id+quote).encode()).hexdigest()
            cur=await c.execute("""INSERT INTO call.memories(caller_id,call_id,source,content,quote,turn_id,idem_key)
              VALUES(%s,%s,'delegation',%s,%s,%s,%s) ON CONFLICT(call_id,idem_key) DO UPDATE SET idem_key=EXCLUDED.idem_key RETURNING id""",(p.caller_id,call_id,quote,quote,turn['id'],idem))
            memory_id=(await cur.fetchone())['id'];result={'result':'saved','memory_id':memory_id}
            old_ids=[i for i in replaces if isinstance(i,int) and not isinstance(i,bool) and i>0 and i!=memory_id][:20]
            if old_ids:
                await c.execute("UPDATE call.memories SET status='superseded',superseded_by=%s WHERE caller_id=%s AND id=ANY(%s::bigint[]) AND status='active'",(memory_id,p.caller_id,old_ids))
            await self._record_operation(c,call_id,segment,key,'remember',result,[memory_id],len(quote))
            return result

    async def _operation(self,c,call_id,key):
        cur=await c.execute('SELECT result_data FROM call.delegations WHERE call_id=%s AND request_key=%s',(call_id,key))
        row=await cur.fetchone();return row['result_data'] if row else None

    async def _record_operation(self,c,call_id,segment,key,intent,result,ids,chars):
        await c.execute("""INSERT INTO call.delegations(call_id,segment_id,origin,state,intent,result,target_memory_ids,request_chars,finished_at,request_key,result_data)
           VALUES(%s,%s,'server','done',%s,%s,%s,%s,now(),%s,%s)""",(call_id,segment,intent,result['result'],ids,chars,key,Jsonb(result)))

    async def forget(self,p,memory_ids,call_id=None,segment=None,key=None):
        ids=[int(i) for i in memory_ids if isinstance(i,int) and not isinstance(i,bool) and i>0][:50]
        async with self.pool.connection() as c,c.transaction():
            await c.execute('SELECT id FROM call.callers WHERE id=%s FOR UPDATE',(p.caller_id,))
            if call_id:
                await self._owned(c,p,call_id)
                old=await self._operation(c,call_id,key)
                if old:return old
            cur=await c.execute("""WITH RECURSIVE gone AS (
              SELECT id,call_id,turn_id FROM call.memories WHERE caller_id=%s AND
                (id=ANY(%s::bigint[]) OR content IN(SELECT content FROM call.memories WHERE caller_id=%s AND id=ANY(%s::bigint[])))
              UNION SELECT m.id,m.call_id,m.turn_id FROM call.memories m JOIN gone g ON m.superseded_by=g.id WHERE m.caller_id=%s
            ) SELECT * FROM gone""",(p.caller_id,ids,p.caller_id,ids,p.caller_id))
            rows=await cur.fetchall();found=[r['id'] for r in rows]
            if found:
                calls=list({str(r['call_id']) for r in rows}|({call_id} if call_id else set()))
                await c.execute("UPDATE call.turns SET forgotten_at=now() WHERE call_id=ANY(%s::uuid[])",(calls,))
                await c.execute("UPDATE call.cards SET forgotten_at=now(),summary='잊은 내용이 포함되어 숨긴 통화',decided='[]',undecided='[]',todos='[]',ask_next='[]' WHERE call_id=ANY(%s::uuid[])",(calls,))
                await c.execute('DELETE FROM call.memories WHERE id=ANY(%s::bigint[])',(found,))
                await self._invalidate(c,p,calls,'forget',{'memories':found})
            result={'result':'forgotten' if found else 'none_matched','count':len(found)}
            if call_id:await self._record_operation(c,call_id,segment,key,'forget',result,found,0)
            return result

    async def _invalidate(self,c,p,calls,reason,source_ids):
        cur=await c.execute(SCOPE+'SELECT room_key FROM rooms ORDER BY room_key',self.params(p))
        for row in await cur.fetchall():
            await c.execute("SELECT pg_advisory_xact_lock(hashtextextended('call.kakao:'||%s,0))",(row['room_key'],))
        await c.execute('UPDATE call.callers SET context_revision=context_revision+1 WHERE id=%s',(p.caller_id,))
        for call_id in calls:
            await c.execute('INSERT INTO call.deletions(caller_id,call_ref,reason,source_ids) VALUES(%s,%s,%s,%s)',(p.caller_id,call_id,reason,Jsonb(source_ids)))
        await c.execute("""UPDATE call.kakao_guards g SET
          message_forgotten_through=coalesce((SELECT max(id) FROM marong.messages WHERE room_key=g.room_key),0),
          note_forgotten_through=coalesce((SELECT max(id) FROM marong.notes WHERE room_key=g.room_key),0),
          summary_forgotten_through=coalesce((SELECT max(id) FROM marong.summaries WHERE room_key=g.room_key),0)
          WHERE friend_id=%s""",(p.friend_id,))
        # Checkpoints contain only IDs/revision; dropping them also prevents an
        # in-flight organizer from restoring an obsolete revision on retry.
        for table in ('checkpoint_writes','checkpoint_blobs','checkpoints'):
            if await self._table_exists(c,table):
                await c.execute(f'DELETE FROM call_graph.{table} WHERE thread_id=ANY(%s::text[])',(['call:'+x for x in calls],))

    async def _table_exists(self,c,name):
        cur=await c.execute('SELECT to_regclass(%s) AS t',('call_graph.'+name,))
        return bool((await cur.fetchone())['t'])

    async def list_memories(self,p):
        return await self.all("SELECT m.id,m.content,m.created_at FROM call.memories m JOIN call.calls c ON c.id=m.call_id WHERE m.caller_id=%s AND m.status='active' AND c.deleted_at IS NULL ORDER BY m.created_at DESC LIMIT 100",(p.caller_id,))

    async def list_calls(self,p):
        return await self.all("SELECT c.id,c.status,c.started_at,c.ended_at,c.organize_status,CASE WHEN k.forgotten_at IS NULL THEN k.summary END AS summary FROM call.calls c LEFT JOIN call.cards k ON k.call_id=c.id WHERE c.caller_id=%s AND c.deleted_at IS NULL ORDER BY c.started_at DESC LIMIT 50",(p.caller_id,))

    async def detail(self,p,call_id):
        row=await self.one('SELECT id,status,started_at,ended_at,organize_status FROM call.calls WHERE id=%s AND caller_id=%s AND deleted_at IS NULL',(call_id,p.caller_id))
        if not row:raise PermissionError('call_not_found')
        row['turns']=await self.all("SELECT id,role,CASE WHEN forgotten_at IS NULL THEN content ELSE '잊은 내용' END AS content,finalized,forgotten_at FROM call.turns WHERE call_id=%s ORDER BY seq LIMIT 500",(call_id,))
        return row

    async def delete_call(self,p,call_id):
        async with self.pool.connection() as c,c.transaction():
            await c.execute('SELECT id FROM call.callers WHERE id=%s FOR UPDATE',(p.caller_id,))
            row=await self._owned(c,p,call_id)
            if row['status']=='live':raise ValueError('call_active')
            await self._invalidate(c,p,[call_id],'delete_call',{})
            await c.execute('DELETE FROM call.calls WHERE id=%s',(call_id,))
        return {'ok':True}
