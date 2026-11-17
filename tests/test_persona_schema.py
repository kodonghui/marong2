"""TC-256 against a fresh Postgres with the migrations preceding 019."""

import psycopg
from psycopg import sql

from pg import ROOT, TestDB

PERMISSIONS = {
    "friend_cards": ("SIU", "S"),
    "friend_rules": ("SIU", "S"),
    "custom_instructions": ("SIU", "S"),
    "preference_signals": ("SIU", "SI"),
    "chat_cards": ("SIU", ""),
    "safety_states": ("SIU", "SIU"),
    "proactive_turns": ("SIU", ""),
    "proactive_drafts": ("SIU", ""),
    "memory_items": ("SIU", "SIU"),
    "open_loops": ("SIU", "SIU"),
    "memory_jobs": ("SIU", "SIU"),
    "forget_marks": ("SIU", "SIU"),
    "memory_forgets": ("SI", "SI"),
    "watches": ("SIU", ""),
    "relays": ("SIU", ""),
    "call_texts": ("SU", "SI"),
    "persona_ai_runs": ("SI", "SI"),
    "persona_tool_calls": ("SI", ""),
}
STATEMENTS = {
    "S": sql.SQL("SELECT * FROM {table} WHERE false"),
    "I": sql.SQL("INSERT INTO {table} OVERRIDING SYSTEM VALUE SELECT * FROM {table} WHERE false"),
    "U": sql.SQL("UPDATE {table} SET {column}=DEFAULT WHERE false"),
    "D": sql.SQL("DELETE FROM {table} WHERE false"),
}


def assert_sqlstate(db, role, query, expected=None):
    with psycopg.connect(db.admin_url) as conn:
        conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
        try:
            conn.execute(query)
        except psycopg.Error as error:
            if error.sqlstate != expected:
                raise AssertionError(f"{role}: expected {expected}, received {error.sqlstate}") from error
        else:
            assert expected is None, f"{role}: expected refusal {expected}"
        finally:
            conn.rollback()


def privileges(db):
    for table, flags in PERMISSIONS.items():
        [(column,)] = db.admin(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='marong' AND table_name=%s ORDER BY ordinal_position LIMIT 1", (table,)
        )
        for role, permitted in zip(("marong", "marong_call"), flags):
            for operation, statement in STATEMENTS.items():
                query = statement.format(table=sql.Identifier("marong", table), column=sql.Identifier(column))
                assert_sqlstate(db, role, query, None if operation in permitted else "42501")
    assert_sqlstate(db, "marong", "SELECT * FROM call.turns WHERE false", "42501")


def one_card_and_forget(db):
    db.admin("""
        INSERT INTO marong.friends(name) VALUES ('fixture');
        INSERT INTO marong.rooms(room_key,is_channel) VALUES ('fixture',true);
        INSERT INTO marong.messages(room_key,role,content) VALUES
            ('fixture','assistant','synthetic line a'),('fixture','assistant','synthetic line b');
        INSERT INTO marong.embeddings(room_key,source_type,source_id,model,embedding)
            SELECT room_key,'message',id,'fixture',array_fill(0.0::real, ARRAY[384])::vector
            FROM marong.messages;
        SET ROLE marong;
        INSERT INTO marong.chat_cards(friend_id,kind,step,room_key,expires_at)
            VALUES (1,'card_question',1,'fixture',now()+interval '1 hour');
        INSERT INTO marong.memory_forgets(friend_id,via,request_key) VALUES (1,'screen','fixture-forget');
        INSERT INTO marong.forget_marks(forget_id,friend_id,target_type,target_id,state)
            VALUES (1,1,'message',1,'forgotten');
        RESET ROLE;
    """, None)
    assert_sqlstate(db, "marong", "INSERT INTO marong.chat_cards(friend_id,kind,step,room_key,expires_at) "
                    "VALUES (1,'card_question',2,'fixture',now()+interval '1 hour')", "23505")
    assert_sqlstate(db, "marong", "DELETE FROM marong.embeddings WHERE false", "42501")
    with psycopg.connect(db.admin_url) as conn:
        conn.execute("SET LOCAL ROLE marong")
        assert conn.execute("SELECT marong.forget_embeddings(1)").fetchone() == (1,)
        assert conn.execute("SELECT marong.forget_embeddings(1)").fetchone() == (0,)
        assert conn.execute("SELECT source_id FROM marong.embeddings").fetchall() == [(2,)]
        assert conn.execute("SELECT count(*) FROM marong.messages").fetchone() == (2,)


def main():
    db = TestDB()
    bot = ROOT / "marong/migrations"
    call = ROOT / "marong/call/migrations"
    try:
        steps = (call.parent / "schema.sql", *sorted(call.glob("00[2-4]*.sql")), *sorted(bot.glob("01[0-3]*.sql")),
                 *sorted(call.glob("00[5-6]*.sql")), *sorted(bot.glob("01[4-8]*.sql")), *call.glob("007*.sql"))
        for file in steps:
            db.admin(file.read_text(encoding="utf-8"), None)
        migration = (bot / "019_persona.sql").read_text(encoding="utf-8")
        db.admin(migration, None)
        db.admin(migration, None)
        privileges(db)
        one_card_and_forget(db)
    finally:
        db.close()
    print("TC-256: 019 replay, 144 table permissions, card uniqueness, and scoped vector removal passed")


if __name__ == "__main__":
    main()
