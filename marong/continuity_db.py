"""Scoped, read-only inputs for SPEC-480 and SPEC-483."""

from datetime import datetime

from marong.continuity import (
    LOOKBACK, SIGNAL_TEXTS, Span, Turn, display_turns, fit_row_budget,
    length_label, older_conversations, recent_turns, shortened,
)
from marong.relative_time import relative_time


def _forget_guard(marks, kind, ident):
    if not marks:
        return ""
    return (
        " AND NOT EXISTS (SELECT 1 FROM marong.forget_marks fm "
        f"WHERE fm.target_type='{kind}' AND fm.target_id={ident})"
    )


def _source_guard(kind, ident):
    return (
        " AND NOT EXISTS (SELECT 1 FROM call.source_exclusions x "
        f"WHERE x.caller_id=%(caller)s AND x.source_type='{kind}' AND x.source_id={ident}::text)"
    )


def _text_cte(scope, marks):
    return scope + """, text_turns AS (
        SELECT m.id, m.created_at AS at, m.role, left(m.content,301) AS text,
               right(rtrim(m.content),1)='?' AS question
        FROM marong.messages m JOIN marong.rooms r USING(room_key)
        WHERE r.room_key IN (SELECT room_key FROM roots) AND r.is_channel AND r.memory_room IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM marong.messages other LEFT JOIN marong.people p USING(user_key)
            WHERE other.room_key=r.room_key AND other.role='user' AND p.friend_id IS DISTINCT FROM %(friend)s
          )
          AND m.created_at >= %(cutoff)s
          AND m.meta->>'delivered' IS DISTINCT FROM 'false'
          AND NOT call.kakao_hidden('message',m.id,m.room_key)
          AND m.content ~ '[^[:space:]]' AND m.content <> ALL(%(signals)s)
          AND m.content NOT LIKE '[알림]%%'
        """ + _source_guard("kakao_message", "m.id") + _forget_guard(marks, "message", "m.id") + (
            _forget_guard(marks, "message", "m.reply_to") + ") "
        )


def _call_cte(voice, marks):
    source = "call.turns" if voice else "call.transcript_report"
    private = (
        " AND t.forgotten_at IS NULL AND EXISTS (SELECT 1 FROM call.segments s "
        "WHERE s.id=t.segment_id AND s.call_id=t.call_id)" if voice else ""
    )
    return f"""eligible_calls AS (
        SELECT id, started_at, ended_at FROM call.calls
        WHERE caller_id=%(caller)s AND deleted_at IS NULL AND status IN ('ended','resting')
          AND id IS DISTINCT FROM %(current_call)s::uuid
    ), call_turns AS (
        SELECT t.id, t.call_id, t.started_at, t.ended_at AS at, t.role, left(t.content,301) AS text
        FROM eligible_calls c JOIN {source} t ON t.call_id=c.id
        WHERE t.finalized AND NOT t.interrupted AND t.content ~ '[^[:space:]]'
          AND t.content <> ALL(%(signals)s) AND t.content NOT LIKE '[알림]%%'
        {private}{_source_guard("call_turn", "t.id")}{_forget_guard(marks, "call_turn", "t.id")}
    )"""


async def _rows(conn, sql, params):
    return await (await conn.execute(sql, params)).fetchall()


def _turns(rows, origin):
    return [Turn(row["id"], origin, row["at"], row["role"], row["text"], row.get("question")) for row in rows]


async def read_previous(conn, scope, identity, now, current_call, *, voice, marks):
    params = {**identity, "cutoff": now - LOOKBACK, "current_call": current_call, "signals": list(SIGNAL_TEXTS)}
    text_cte = _text_cte(scope, marks)
    call_cte = "WITH " + _call_cte(voice, marks)
    recent_text = await _rows(conn, text_cte + "SELECT * FROM text_turns ORDER BY at DESC,id DESC LIMIT 60", params)
    recent_call = await _rows(conn, call_cte + """
        SELECT * FROM call_turns WHERE at >= %(cutoff)s ORDER BY at DESC,id DESC LIMIT 60
    """, params)
    recent = recent_turns(_turns(recent_text, "text") + _turns(recent_call, "call"), now)
    spans = []
    text_offset = call_offset = 0
    text_more = call_more = True
    older = []
    while text_more or call_more:
        if text_more:
            rows = await _rows(conn, text_cte + """, boundaries AS (
                SELECT at, at - lag(at) OVER(ORDER BY at,id) > interval '30 minutes' AS starts
                FROM text_turns
            ), grouped AS (
                SELECT at, count(*) FILTER(WHERE starts) OVER(ORDER BY at) AS topic FROM boundaries
            )
            SELECT min(at) AS start,max(at) AS end FROM grouped GROUP BY topic
            ORDER BY max(at) DESC LIMIT 6 OFFSET %(offset)s
            """, {**params, "offset": text_offset})
            spans.extend(Span(row["start"], row["end"], "text") for row in rows)
            text_offset += len(rows)
            text_more = len(rows) == 6
        if call_more:
            rows = await _rows(conn, call_cte + """
                SELECT c.id,c.started_at AS start,max(t.at) AS end
                FROM eligible_calls c JOIN call_turns t ON t.call_id=c.id
                WHERE t.at >= %(cutoff)s GROUP BY c.id,c.started_at
                ORDER BY max(t.at) DESC,c.id DESC LIMIT 6 OFFSET %(offset)s
            """, {**params, "offset": call_offset})
            spans.extend(Span(row["start"], row["end"], "call", row["id"]) for row in rows)
            call_offset += len(rows)
            call_more = len(rows) == 6
        older = older_conversations(spans, now)
        if len(older) == 3:
            break
    summaries = [
        await _summarize(conn, text_cte, call_cte, params, group, now, identity["name"], voice, marks)
        for group in older
    ]
    return recent, fit_row_budget(summaries)


async def _summarize(conn, text_cte, call_cte, params, group, now, name, voice, marks):
    calls = [span for span in group if span.origin == "call"]
    has_text = any(span.origin == "text" for span in group)
    last_call = max(calls, key=lambda span: span.end) if calls else None
    start = last_call.start if last_call else group[0].start
    end = max(span.end for span in group)
    channel = "글·통화" if last_call and has_text else "통화" if last_call else "글"
    result = {"when": relative_time(start, now), "channel": channel}
    shown_turns = []
    if last_call:
        call_params = {**params, "id": last_call.call_id}
        result["length"] = length_label(last_call.start, last_call.end)
        source = "call.turns" if voice else "call.transcript_report"
        guard = "" if not marks else f"""
            AND NOT EXISTS (
                SELECT 1 FROM {source} t JOIN marong.forget_marks fm
                  ON fm.target_type='call_turn' AND fm.target_id=t.id WHERE t.call_id=k.call_id
            )
        """
        cards = await _rows(conn, "SELECT k.summary,k.ask_next FROM call.cards k "
                           "WHERE k.call_id=%(id)s AND k.forgotten_at IS NULL" + guard, call_params)
        if cards:
            card = cards[0]
            result["summary"] = shortened(card["summary"], 400)
            result["ask_next"] = [shortened(value, 100) for value in card["ask_next"][:3] if isinstance(value, str)]
        else:
            rows = await _rows(conn, call_cte + """
                SELECT * FROM call_turns WHERE call_id=%(id)s ORDER BY at DESC,id DESC LIMIT 4
            """, call_params)
            shown_turns += _turns(rows[::-1], "call")
    if has_text:
        rows = await _rows(conn, text_cte + """
            SELECT * FROM text_turns WHERE at BETWEEN %(start)s AND %(end)s
            ORDER BY at DESC,id DESC LIMIT 4
        """, {**params, "start": last_call.end if last_call else start, "end": end})
        shown_turns += _turns(rows[::-1], "text")
    if shown_turns:
        result["turns"] = display_turns(shown_turns, name, mark_question=True)
    return result


async def read_recent_call(conn, caller, now: datetime, *, marks: bool):
    params = {"caller": caller, "current_call": None, "signals": list(SIGNAL_TEXTS)}
    rows = await _rows(conn, "WITH " + _call_cte(False, marks) + """,
        latest_call AS (SELECT id FROM eligible_calls ORDER BY started_at DESC,id DESC LIMIT 1)
        SELECT *,min(started_at) OVER() AS first_at,max(at) OVER() AS last_at
        FROM call_turns WHERE call_id=(SELECT id FROM latest_call)
        ORDER BY at DESC,id DESC LIMIT 20
    """, params)
    if not rows:
        return None
    recent = recent_turns(_turns(rows, "call"), now)
    return (recent, rows[0]["first_at"], rows[0]["last_at"]) if recent else None
