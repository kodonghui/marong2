"""Caller-scoped PostgreSQL memory. Never used synchronously in the PCM loop."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from psycopg import Error
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from call_usage import Ledger
from call_cost import MonthlyCost
from call_tuning import BASE
from marong.room_scope import writing_room
from marong.friend_scope import accepted_circle
from marong.usage import Usage, configured_limit


@dataclass(frozen=True)
class Principal:
    caller_id: int
    friend_id: int
    name: str
    revision: int = 0
    private_rooms: tuple[str, str] | None = None
    unified: bool = False
    usage_profile: dict | None = field(default=None, repr=False, compare=False)


class CallBusy(Exception):
    pass


SCOPE = """WITH roots AS (
 SELECT r.room_key FROM marong.rooms r WHERE r.is_channel AND EXISTS (
  SELECT 1 FROM marong.messages m JOIN marong.people p USING(user_key)
  WHERE m.room_key=r.room_key AND m.role='user' AND p.friend_id=%(friend)s)
), rooms AS (
 SELECT r.room_key FROM marong.rooms r WHERE r.room_key IN (SELECT room_key FROM roots)
 OR r.memory_room IN (SELECT room_key FROM roots)
) """

PRIVATE_SCOPE = """WITH roots AS (
 SELECT r.room_key FROM marong.rooms r
 WHERE r.room_key IN (%(discord_room)s,%(kakao_room)s)
 AND r.is_channel AND r.memory_room IS NULL
 AND EXISTS (
   SELECT 1 FROM marong.messages m JOIN marong.people p USING(user_key)
   WHERE m.room_key=r.room_key AND m.role='user' AND p.friend_id=%(friend)s
 )
 AND NOT EXISTS (
   SELECT 1 FROM marong.messages m LEFT JOIN marong.people p USING(user_key)
   WHERE m.room_key=r.room_key AND m.role='user' AND p.friend_id IS DISTINCT FROM %(friend)s
 )
), rooms AS (SELECT room_key FROM roots) """

OWNED_SCOPE = f"""WITH roots AS (
 SELECT r.room_key FROM marong.rooms r
 WHERE r.owner_friend_id=%(friend)s AND r.is_channel AND r.memory_room IS NULL
 AND (
   {writing_room('r')}
   OR NOT EXISTS (
     SELECT 1 FROM marong.messages m LEFT JOIN marong.people p USING (user_key)
     WHERE m.room_key=r.room_key AND m.role='user' AND p.friend_id IS DISTINCT FROM %(friend)s
   )
 )
), rooms AS (SELECT room_key FROM roots)
"""


def memory_scope(p):
    if p.unified:
        return OWNED_SCOPE
    return PRIVATE_SCOPE if p.private_rooms is not None else SCOPE


def summary_visibility(p, alias):
    if p.unified:
        return (f"EXISTS (SELECT 1 FROM marong.rooms owned WHERE owned.room_key={alias}.room_key"
                f" AND {writing_room('owned')})")
    return "true" if p.private_rooms is None else "false"


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
        self.friend_marks = False
        self.pool = AsyncConnectionPool(dsn, min_size=1, max_size=4, open=False, timeout=2,
            kwargs={'autocommit': True, 'row_factory': dict_row, 'options': '-c statement_timeout=2500'})
        self.live_usage = Ledger(self)
        self.monthly_cost = MonthlyCost(self)
        self.daily_usage = Usage(self.pool, configured_limit())

    async def open(self):
        await self.pool.open(wait=True, timeout=5)
        row = await self.one("SELECT value FROM call.meta WHERE key='schema_version'")
        if not row or row['value'] != '2':
            raise RuntimeError('call_schema_version')
        marks = await self.one("SELECT to_regclass('marong.forget_marks') IS NOT NULL AS ready")
        self.friend_marks = marks["ready"]

    async def close(self):
        await self.live_usage.close()
        await self.pool.close()

    async def all(self, sql, params=()):
        async with self.pool.connection() as c:
            cur = await c.execute(sql, params)
            return await cur.fetchall()

    async def one(self, sql, params=()):
        rows = await self.all(sql, params)
        return rows[0] if rows else None

    async def friend_instruction(self, p):
        if os.getenv("MARONG_FRIEND_CARD") != "on":
            return ""
        from marong.friend_card import FriendCards
        from marong.persona_prompt import FriendPrompt
        adapter = type("FriendReader", (), {"pool": self.pool})()
        data = await FriendCards(adapter).read(p.friend_id, include_call_first=False)
        prompt = FriendPrompt().build(p.friend_id, "call", data, private=True)
        if os.getenv("MARONG_SAFETY") == "on":
            from marong.safety import ASK, ASKED, BODY_HELP, CALL_HELP, URGENT
            state = await self.one("""SELECT * FROM marong.safety_states WHERE friend_id=%s AND closed_at IS NULL
                AND last_signal_at>now()-CASE WHEN kind='crisis' THEN interval '3 days' ELSE interval '7 days' END
                ORDER BY (kind='crisis') DESC LIMIT 1""", (p.friend_id,))
            if state:
                if state["kind"] == "body":
                    safety = BODY_HELP if not state["told_help_at"] else ""
                elif not state["told_109_at"] and (state["injured"] or state["answer"] == "now"):
                    safety = URGENT if state["injured"] else CALL_HELP
                elif state["told_109_at"] and state["asked_at"] is None:
                    safety = ""
                else:
                    safety = ASK if state["asked_at"] is None else ASKED
                prompt += "\n\n" + safety
        return prompt

    async def principal(self, email_hash, *, include_limits=False):
        columns = ",p.usage_unlimited,p.daily_units,p.call_monthly_usd" if include_limits else ""
        profile_join = "LEFT JOIN marong.friend_profiles p ON p.friend_id=f.id" if include_limits else ""
        row = await self.one(f"""SELECT c.id AS caller_id,c.friend_id,f.name,c.context_revision{columns}
            FROM call.caller_logins l JOIN call.callers c ON c.id=l.caller_id
            JOIN marong.friends f ON f.id=c.friend_id {profile_join}
            WHERE l.email_sha256=%s AND c.enabled""", (email_hash,))
        return Principal(row['caller_id'], row['friend_id'], row['name'], row['context_revision'],
                         usage_profile=row if include_limits else None) if row else None

    def context_version(self):
        version = "context_revision"
        if self.friend_marks:
            version += ("+coalesce((SELECT max(f.id) FROM marong.memory_forgets f "
                        "WHERE f.friend_id=call.callers.friend_id AND (f.items>0 OR f.messages>0)),0)")
        return version

    async def revision(self, p):
        row = await self.one(f'SELECT {self.context_version()} AS revision FROM call.callers WHERE id=%s AND enabled',
                             (p.caller_id,))
        return row['revision'] if row else -1

    def friend_memory_enabled(self):
        return self.friend_marks and os.getenv("MARONG_FRIEND_MEMORY") == "on"

    def keep_source(self, kind, ident):
        if not self.friend_marks:
            return ""
        return (" AND NOT EXISTS (SELECT 1 FROM marong.forget_marks fm "
                f"WHERE fm.target_type='{kind}' AND fm.target_id={ident}) ")

    def keep_call_copy(self, call_id, turn_id=None):
        if not self.friend_marks:
            return ""
        scope = f" AND ({turn_id} IS NULL OR t.id={turn_id})" if turn_id else ""
        return (" AND NOT EXISTS (SELECT 1 FROM call.turns t JOIN marong.forget_marks fm "
                "ON fm.target_type='call_turn' AND fm.target_id=t.id "
                f"WHERE t.call_id={call_id}{scope}) ")

    @staticmethod
    def params(p):
        params = {'friend': p.friend_id, 'caller': p.caller_id}
        if p.private_rooms is not None:
            params.update(zip(('discord_room', 'kakao_room'), p.private_rooms, strict=True))
        return params

    async def seed(self, p, call_id=None, *, memory_limit=30, history_chars=4000):
        params = self.params(p)
        scope = memory_scope(p)
        notes = await self.all(scope + f"""SELECT * FROM (
          SELECT DISTINCT ON(n.user_key) n.id,n.content,n.created_at,'kakao_note' AS source
          FROM marong.notes n JOIN marong.people p ON p.user_key=n.user_key
          WHERE n.room_key IN (SELECT room_key FROM rooms) AND p.friend_id=%(friend)s
          AND ({summary_visibility(p, 'n')} OR n.summary_id IS NULL)
          AND NOT call.kakao_hidden('note',n.id,n.room_key)
          AND NOT EXISTS(SELECT 1 FROM call.source_exclusions x WHERE x.caller_id=%(caller)s AND x.source_type='kakao_note' AND x.source_id=n.id::text)
        """ + self.keep_source("note", "n.id") + """
          ORDER BY n.user_key,(n.room_key IN (SELECT room_key FROM roots)) DESC,n.id DESC
        ) n ORDER BY id DESC LIMIT 4""", params)
        summaries = await self.all(scope + f"""SELECT id,content,created_at,'kakao_summary' AS source
          FROM marong.summaries s WHERE room_key IN (SELECT room_key FROM rooms) AND content<>''
          AND {summary_visibility(p, 's')}
          AND NOT call.kakao_hidden('summary',id,room_key)
          AND NOT EXISTS(SELECT 1 FROM call.source_exclusions x WHERE x.caller_id=%(caller)s AND x.source_type='kakao_summary' AND x.source_id=s.id::text)
        """ + self.keep_source("summary", "s.id") + """
          ORDER BY last_id DESC LIMIT 3""", params)
        recent = await self.all(scope + """SELECT m.id,m.role,m.content,m.created_at,'kakao_message' AS source
          FROM marong.messages m WHERE room_key IN (SELECT room_key FROM rooms)
          AND m.meta->>'delivered' IS DISTINCT FROM 'false' AND NOT call.kakao_hidden('message',id,room_key)
          AND NOT EXISTS(SELECT 1 FROM call.source_exclusions x WHERE x.caller_id=%(caller)s AND x.source_type='kakao_message' AND x.source_id=m.id::text)
        """ + self.keep_source("message", "m.id") + self.keep_source("message", "m.reply_to") + """
          ORDER BY id DESC LIMIT 10""", params)
        # Other people contribute only the existing, explicitly shared notes.
        friends = [] if p.unified or p.private_rooms is not None else await self.all("""SELECT f.name,fs.label,s.content,
          CASE WHEN fs.close THEN s.close_content ELSE '' END AS close_content
          FROM marong.friendships fs JOIN marong.friends f
            ON f.id=CASE WHEN fs.friend_a=%s THEN fs.friend_b ELSE fs.friend_a END
          LEFT JOIN LATERAL(SELECT n.content,n.close_content FROM marong.shared_notes n WHERE n.friend_id=f.id
          """ + self.keep_source("shared_note", "n.id") + """ ORDER BY n.id DESC LIMIT 1) s ON true
          WHERE %s IN(fs.friend_a,fs.friend_b) AND f.share AND coalesce(to_jsonb(fs)->>'state','accepted')='accepted' ORDER BY f.id LIMIT 8""", (p.friend_id,p.friend_id))
        for row in friends:
            row['content'] = (row['content'] or '') + '\n' + (row.pop('close_content') or '')
        if p.unified and os.getenv("MARONG_FRIENDS") == "1":
            try:
                query = accepted_circle(self.keep_source("shared_note", "x.id"))
                circle = await asyncio.wait_for(self.all(query, {"friend": p.friend_id, "limit": 20}), .7)
            except (Error, TimeoutError):
                circle = []
            friends = [{"name": row["name"], "label": row["label"], "close": row["close"],
                        "content": "\n".join(filter(None, (row["shared"], row["shared_close"])))} for row in circle]
        memories = await self.all("""SELECT m.id,m.content,m.created_at,'call_memory' AS source FROM call.memories m
          JOIN call.calls c ON c.id=m.call_id WHERE m.caller_id=%s AND m.status='active' AND c.deleted_at IS NULL
          """ + self.keep_call_copy("m.call_id", "m.turn_id") + " ORDER BY m.created_at DESC LIMIT %s", (p.caller_id,memory_limit))
        cards = await self.all("""SELECT c.id,k.summary AS content,k.created_at,'call_card' AS source
          FROM call.cards k JOIN call.calls c ON c.id=k.call_id WHERE c.caller_id=%s AND c.deleted_at IS NULL
          AND k.forgotten_at IS NULL""" + self.keep_call_copy("c.id") +
          " ORDER BY c.started_at DESC LIMIT 3", (p.caller_id,))
        history = []
        if call_id:
            history = await self.all("""SELECT t.id,t.role,t.content,t.started_at,'current_call' AS source
              FROM call.turns t JOIN call.calls c ON c.id=t.call_id
              WHERE c.caller_id=%s AND c.id=%s AND c.deleted_at IS NULL
              AND t.forgotten_at IS NULL AND t.finalized AND NOT t.interrupted"""
              + self.keep_source("call_turn", "t.id") + " ORDER BY t.seq DESC LIMIT 40", (p.caller_id,call_id))
        payload = {'friend': p.name, 'kakao_notes': pack(notes,1000), 'kakao_summaries': pack(summaries,1500),
            'kakao_recent': list(reversed(pack(recent,1500))), 'shared_friends': pack(friends,1500),
            'call_memories': pack(memories,1500), 'call_cards': pack(cards,1500),
            'current_call': list(reversed(pack(history,history_chars)))}
        return json.dumps(payload,ensure_ascii=False,default=str)

    async def recall(self,p,query):
        query=normalized(query)[:100]
        if len(query)<2:return {'result':'ask_which','items':[]}
        q='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        params=self.params(p)|{'q':q}
        scope = memory_scope(p)
        rows=await self.all(scope+"""SELECT * FROM (
          SELECT 'kakao_message' AS source,m.id::text AS id,m.content,m.created_at FROM marong.messages m
          WHERE m.room_key IN(SELECT room_key FROM rooms) AND m.content ILIKE %(q)s
          AND m.meta->>'delivered' IS DISTINCT FROM 'false' AND NOT call.kakao_hidden('message',m.id,m.room_key)
        """ + self.keep_source("message", "m.id") + self.keep_source("message", "m.reply_to") + f"""
          UNION ALL SELECT 'kakao_note',n.id::text,n.content,n.created_at FROM marong.notes n JOIN marong.people p USING(user_key)
          WHERE n.room_key IN(SELECT room_key FROM rooms) AND p.friend_id=%(friend)s AND n.content ILIKE %(q)s
          AND ({summary_visibility(p, 'n')} OR n.summary_id IS NULL)
          AND NOT call.kakao_hidden('note',n.id,n.room_key)
        """ + self.keep_source("note", "n.id") + f"""
          UNION ALL SELECT 'kakao_summary',s.id::text,s.content,s.created_at FROM marong.summaries s
          WHERE {summary_visibility(p, 's')} AND s.room_key IN(SELECT room_key FROM rooms) AND s.content ILIKE %(q)s
          AND NOT call.kakao_hidden('summary',s.id,s.room_key)
        """ + self.keep_source("summary", "s.id") + """
          UNION ALL SELECT 'call_memory',m.id::text,m.content,m.created_at FROM call.memories m
          JOIN call.calls c ON c.id=m.call_id WHERE m.caller_id=%(caller)s AND m.status='active'
          AND c.deleted_at IS NULL AND m.content ILIKE %(q)s
        """ + self.keep_call_copy("m.call_id", "m.turn_id") + """
          UNION ALL SELECT 'call_card',c.id::text,k.summary,k.created_at FROM call.cards k JOIN call.calls c ON c.id=k.call_id
          WHERE c.caller_id=%(caller)s AND c.deleted_at IS NULL AND k.forgotten_at IS NULL AND k.summary ILIKE %(q)s
        """ + self.keep_call_copy("c.id") + """
        ) hits WHERE NOT EXISTS(SELECT 1 FROM call.source_exclusions x WHERE x.caller_id=%(caller)s
          AND x.source_type=hits.source AND x.source_id=hits.id) ORDER BY created_at DESC LIMIT 12""", params)
        if self.friend_memory_enabled():
            from call_friend_memory import recall_items
            async with self.pool.connection() as conn:
                typed = await recall_items(conn, p.friend_id, query.casefold())
            rows = [*typed, *rows]
        return {'result':'found' if rows else 'not_found','items':pack(rows,3000)}

    async def forget_friend(self, p, call_id, segment, key, args):
        if not self.friend_memory_enabled() or not call_id or not segment or not key:
            return {"result": "not_saved", "ok": False}
        from call_friend_memory import forget_item
        request_key = "call:" + hashlib.sha256((call_id + ":" + key).encode()).hexdigest()
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(%s::bigint)", (p.friend_id,))
            call = await self._owned(conn, p, call_id)
            old = await self._operation(conn, call_id, request_key)
            if old:
                return old
            active = await conn.execute(
                "SELECT 1 FROM call.segments WHERE id=%s AND call_id=%s AND state='open'", (segment, call_id))
            if call["status"] != "live" or not await active.fetchone():
                return {"result": "not_saved", "ok": False}
            result = await forget_item(conn, p, call_id, segment, request_key, args)
            stored = {k: v for k, v in result.items() if k != "candidates"}
            await self._record_operation(conn, call_id, segment, request_key, "forget", stored, [], 0)
            return result

    async def start_call(self, p, client_id, voice, prompt_version, *, entrypoint='web'):
        async with self.pool.connection() as c, c.transaction():
            caller = await c.execute('SELECT id FROM call.callers WHERE id=%s AND enabled FOR UPDATE', (p.caller_id,))
            if not await caller.fetchone():
                raise PermissionError('caller_disabled')
            cur = await c.execute("""SELECT id,entrypoint,status,client_id FROM call.calls
                WHERE caller_id=%s AND status<>'ended' AND deleted_at IS NULL FOR UPDATE""", (p.caller_id,))
            row = await cur.fetchone()
            if row:
                same_call = row['entrypoint'] == entrypoint and (
                    entrypoint == 'web' or str(row['client_id']) == client_id)
                if same_call:
                    await c.execute("""UPDATE call.calls SET status='live',client_id=%s,last_beat_at=now()
                        WHERE id=%s""", (client_id, row['id']))
                    return str(row['id']), True
                if row['status'] == 'live':
                    raise CallBusy()
                # A disconnected call from another entry point keeps its own history and memory scope.
                if p.unified and row["entrypoint"] == "web":
                    await self.meter_closed(c, p, row["id"])
                await c.execute("""UPDATE call.calls SET status='ended',ended_at=now(),
                    end_reason='beat_lost',organize_status='pending',organize_next_at=now() WHERE id=%s""",
                    (row['id'],))
            cur = await c.execute("""INSERT INTO call.calls(caller_id,client_id,prompt_version,voice,entrypoint)
                VALUES(%s,%s,%s,%s,%s) RETURNING id""", (p.caller_id, client_id, prompt_version, voice, entrypoint))
            return str((await cur.fetchone())['id']), False

    async def can_resume_call(self, p, entrypoint, client_id):
        row = await self.one("""SELECT 1 FROM call.calls WHERE caller_id=%s AND entrypoint=%s
            AND (%s='web' OR client_id=%s) AND status<>'ended' AND deleted_at IS NULL""",
            (p.caller_id, entrypoint, entrypoint, client_id))
        return row is not None

    async def resume_voice(self, p, client_id):
        row = await self.one("""
            SELECT voice FROM call.calls WHERE caller_id=%s AND entrypoint='web' AND client_id=%s
            AND status<>'ended' AND deleted_at IS NULL
        """, (p.caller_id, client_id))
        return row["voice"] if row else None

    async def claim_ring(self, p, call_id, ring_id=None):
        """A call Marong placed at a time the friend set (marong.app_rings, docs/app-ring.md SPEC-136).
        The ringing row (this one when ring_id is given, else the caller's latest whose answer window is open) becomes
        answered by this call: fresh=True. A call that already answered it (a reconnect) gets it again: fresh=False.
        reason: promise | hello (a call Marong placed without a promise, docs/04-functional-spec/call-first.md
        SPEC-268), topic: its picture (v1/<name>) or None. None: an ordinary call."""
        async with self.pool.connection() as c, c.transaction():
            cur = await c.execute("""UPDATE marong.app_rings SET status='answered',answered_at=now(),call_id=%(call)s
                WHERE id=(SELECT id FROM marong.app_rings WHERE caller_id=%(caller)s AND status='ringing'
                          AND answer_until>now() AND (%(ring)s::uuid IS NULL OR id=%(ring)s::uuid)
                          ORDER BY created_at DESC LIMIT 1 FOR UPDATE SKIP LOCKED)
                  AND status='ringing'
                RETURNING id,title,say,created_at,now()-created_at AS waited,reason,topic""",
                {'call': call_id, 'caller': p.caller_id, 'ring': ring_id})
            row = await cur.fetchone()
            if row:
                return {**row, 'fresh': True}
            cur = await c.execute("""SELECT id,title,say,created_at,reason,topic FROM marong.app_rings
                WHERE caller_id=%s AND status='answered' AND call_id=%s ORDER BY created_at DESC LIMIT 1""",
                (p.caller_id, call_id))
            row = await cur.fetchone()
            return {**row, 'fresh': False} if row else None

    async def recover_entrypoint(self, entrypoint):
        async with self.pool.connection() as c, c.transaction():
            await c.execute("""UPDATE call.calls SET status='resting' WHERE status='live' AND entrypoint=%s""",
                            (entrypoint,))
            await c.execute("""UPDATE call.segments s SET state='closed',closed_at=now(),close_reason='server_restart'
                FROM call.calls c WHERE c.id=s.call_id AND s.state<>'closed' AND c.entrypoint=%s""",
                (entrypoint,))

    async def tuning(self):
        return await self.one("""SELECT t.* FROM call.live_tunings t WHERE name=COALESCE((
            SELECT value #>> '{}' FROM call.settings WHERE key='live_tuning'),%s)""", (BASE,))

    async def start_segment(self,p,call_id,client_id,model,*,tuning=None,handoff_from=None,await_provider=False):
        segment=str(uuid.uuid4())
        async with self.pool.connection() as c,c.transaction():
            await self._owned(c,p,call_id)
            if handoff_from:
                changed=await c.execute("""UPDATE call.segments SET state='closed',closed_at=now(),close_reason='handoff'
                    WHERE call_id=%s AND id=%s AND state='open'""",(call_id,handoff_from))
                if changed.rowcount!=1:raise ValueError('handoff_segment_changed')
            else:
                await c.execute("UPDATE call.segments SET state='closed',closed_at=now(),close_reason='connection_lost' WHERE call_id=%s AND state<>'closed'",(call_id,))
            await c.execute("""
                INSERT INTO call.segments(id,call_id,mode,client_id,state,provider,provider_model,provider_ready_at)
                VALUES(%s,%s,
                    CASE WHEN %s THEN 'handoff'
                         WHEN %s AND NOT EXISTS(SELECT 1 FROM call.segments WHERE call_id=%s) THEN 'start'
                         ELSE 'reconnect' END,
                    %s,%s,'vertex',%s,CASE WHEN %s THEN NULL ELSE clock_timestamp() END)
            """, (segment,call_id,handoff_from is not None,await_provider,call_id,client_id,
                  'opening' if await_provider else 'open',model,await_provider))
            if tuning:
                await c.execute("UPDATE call.segments SET tuning=%s WHERE id=%s", (tuning,segment))
        return segment

    async def segment_ready(self, segment):
        async with self.pool.connection() as c:
            await c.execute("""
                UPDATE call.segments SET state='open',provider_ready_at=clock_timestamp()
                WHERE id=%s AND state='opening'
            """, (segment,))

    async def segment_start_failed(self, segment):
        async with self.pool.connection() as c:
            await c.execute("""
                UPDATE call.segments SET state='closed',closed_at=clock_timestamp(),close_reason='start_failed'
                WHERE id=%s AND state='opening'
            """, (segment,))

    async def record_connection(self, segment, *, timing=None, playback=None):
        async with self.pool.connection() as c:
            await c.execute("""
                UPDATE call.segments SET connect_timing=coalesce(%s,connect_timing),playback=coalesce(%s,playback)
                WHERE id=%s
            """, (Jsonb(timing) if timing is not None else None,
                  Jsonb(playback) if playback is not None else None, segment))

    async def record_mic(self, segment, sent, held):
        async with self.pool.connection() as c:
            await c.execute("UPDATE call.segments SET mic_sent_ms=%s,mic_held_ms=%s WHERE id=%s",
                            (sent, held, segment))

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

    async def meter_closed(self, conn, p, call_id):
        try:
            async with conn.transaction():
                cursor = await conn.execute("""
                    SELECT coalesce(floor(sum(extract(epoch FROM (closed_at-opened_at)))),0)::integer AS seconds
                    FROM call.segments WHERE call_id=%s AND closed_at IS NOT NULL
                """, (call_id,))
                row = await cursor.fetchone()
                await self.daily_usage.record(p.friend_id, conn=conn, seconds=row["seconds"])
        except Exception as error:
            logging.getLogger(__name__).warning("usage_failed duration %s", type(error).__name__)

    async def finish(self,p,call_id,explicit,*,entrypoint=None,client_id=None,reason=None):
        # reason 'close_requested': Marong ended the call because the friend asked.
        async with self.pool.connection() as c,c.transaction():
            row=await self._owned(c,p,call_id)
            if entrypoint is not None and row['entrypoint'] != entrypoint:
                raise PermissionError('call_not_found')
            if client_id is not None and str(row['client_id']) != client_id:
                return
            if row['status']=='ended':return
            close=reason if explicit and reason in ('close_requested','budget_hard_stop') else 'user_hangup' if explicit else 'connection_lost'
            await c.execute("UPDATE call.segments SET state='closed',closed_at=now(),close_reason=%s WHERE call_id=%s AND state<>'closed'",(close,call_id))
            if explicit:
                if p.unified and row["entrypoint"] == "web":
                    await self.meter_closed(c, p, call_id)
                end_reason='budget_hard_stop' if close=='budget_hard_stop' else 'hangup'
                await c.execute("UPDATE call.calls SET status='ended',ended_at=now(),end_reason=%s,organize_status='pending',organize_next_at=now() WHERE id=%s",(end_reason,call_id))
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
            cur=await c.execute("SELECT t.id,t.content FROM call.turns t WHERE t.call_id=%s AND t.role='user'"
                " AND t.finalized AND NOT t.interrupted AND t.forgotten_at IS NULL"
                + self.keep_source("call_turn", "t.id") + " ORDER BY t.seq DESC LIMIT 40",(call_id,))
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
        cur=await c.execute(memory_scope(p)+'SELECT room_key FROM rooms ORDER BY room_key',self.params(p))
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
        return await self.all("""
            SELECT m.id,m.content,m.created_at FROM call.memories m JOIN call.calls c ON c.id=m.call_id
            WHERE m.caller_id=%s AND m.status='active' AND c.deleted_at IS NULL
        """ + self.keep_call_copy("m.call_id", "m.turn_id") + """
            ORDER BY m.created_at DESC LIMIT 100
        """, (p.caller_id,))

    async def list_calls(self,p):
        return await self.all("""
            SELECT c.id,c.status,c.started_at,c.ended_at,c.organize_status,
                   CASE WHEN k.forgotten_at IS NULL """ + self.keep_call_copy("c.id") + """
                        THEN k.summary END AS summary
            FROM call.calls c LEFT JOIN call.cards k ON k.call_id=c.id
            WHERE c.caller_id=%s AND c.deleted_at IS NULL ORDER BY c.started_at DESC LIMIT 50
        """, (p.caller_id,))

    async def detail(self,p,call_id):
        row=await self.one('SELECT id,status,started_at,ended_at,organize_status FROM call.calls WHERE id=%s AND caller_id=%s AND deleted_at IS NULL',(call_id,p.caller_id))
        if not row:raise PermissionError('call_not_found')
        row['turns'] = await self.all("""
            SELECT t.id,t.role,CASE WHEN t.forgotten_at IS NULL """ + self.keep_source("call_turn", "t.id") + """
                                   THEN t.content ELSE '잊은 내용' END AS content,t.finalized,t.forgotten_at
            FROM call.turns t WHERE t.call_id=%s ORDER BY t.seq LIMIT 500
        """, (call_id,))
        return row

    async def delete_call(self,p,call_id):
        async with self.pool.connection() as c,c.transaction():
            await c.execute('SELECT id FROM call.callers WHERE id=%s FOR UPDATE',(p.caller_id,))
            row=await self._owned(c,p,call_id)
            if row['status']=='live':raise ValueError('call_active')
            await self._invalidate(c,p,[call_id],'delete_call',{})
            ready=await c.execute("SELECT to_regclass('call.segment_costs') AS installed")
            if (await ready.fetchone())['installed']:
                await c.execute("""INSERT INTO call.live_usage
                    (kind,call_id,segment_id,segment_ref,seq,received_at,entrypoint,tuning,model,seconds,usd)
                    SELECT 'estimate',v.call_id,v.segment_id,v.segment_id,0,v.opened_at,v.entrypoint,
                    v.tuning,COALESCE(s.provider_model,s.provider),v.seconds,v.usd
                    FROM call.segment_costs v JOIN call.segments s ON s.id=v.segment_id
                    WHERE v.call_id=%s AND v.estimated ON CONFLICT(segment_ref,seq) DO NOTHING""",(call_id,))
            await c.execute('DELETE FROM call.calls WHERE id=%s',(call_id,))
        return {'ok':True}
