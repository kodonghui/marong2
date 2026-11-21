"""TC-510–512: migration 022 on a temporary database with synthetic rows."""

from pathlib import Path
import sys
import unittest

import psycopg
from psycopg import errors, sql
from psycopg.types.json import Jsonb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pg import TestDB


TABLE_ROWS = {
    "decor_items": ("id, kind, slot", "('hat-one', 'hat', 'head'), ('paper-one', 'paper', NULL)"),
    "scene_pictures": ("friend_id, character_id, purpose, topic", "(1, 1, 'topic', 'v1/snow')"),
    "decor_owned": ("friend_id, item_id", "(1, 'hat-one')"),
    "outfits": ("character_id, head", "(1, 'hat-one')"),
    "outfit_firsts": ("friend_id, character_id, item_id, next_at", "(1, 1, 'hat-one', now())"),
    "diary_decor": ("friend_id, background_id, paper_id, font_id", "(1, 'paper-one', 'paper-one', 'paper-one')"),
    "diary_stickers": ("diary_id, friend_id, item_id, x, y, z", "(1, 1, 'hat-one', 0, 0, 0)"),
}


class PetAppSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = TestDB()
        cls.addClassCleanup(cls.db.close)
        cls.db.apply_unified_prerequisites()
        cls.db.apply_unified()
        cls.db.apply_pet_app_prerequisites()
        cls.db.admin("INSERT INTO marong.friends(name) VALUES ('시험친구 가'), ('시험친구 나')")
        cls.db.admin("""
            INSERT INTO marong.friend_profiles(friend_id, friend_code, voice, tickets)
            VALUES (1, 'ABC234', 'Sulafat', 3), (2, 'ABC235', NULL, 0)
        """)
        cls.db.admin("""
            INSERT INTO marong.characters(friend_id, kind, template, name, traits, stage, status, ready_at)
            VALUES (1, 'dog', 'dog_small', '콩이', '{}', 'done', 'ready', now())
        """)
        cls.db.admin("INSERT INTO marong.diaries(friend_id, diary_date) VALUES (1, current_date)")
        cls.before = cls.db.admin("SELECT friend_id, bot_name, voice, friend_code, tickets, updated_at "
                                  "FROM marong.friend_profiles ORDER BY friend_id")
        cls.db.apply_pet_app()

    def test_022_backfill_and_reapplication(self):
        for reapplied in (False, True):
            if reapplied:
                self.db.apply_pet_app()
            profiles = self.db.admin("SELECT friend_id, bot_name, voice, friend_code, tickets, updated_at, voice_source "
                                     "FROM marong.friend_profiles ORDER BY friend_id")
            self.assertEqual(profiles, [self.before[0] + ("chosen",), self.before[1] + (None,)])
            self.assertEqual(self.db.admin("SELECT personality, likes, dislikes, owner_call, intro_at, photo_pick "
                                          "FROM marong.characters"), [([], "", "", None, None, None)])
            self.assertEqual(self.db.admin("SELECT character_id FROM marong.diaries"), [(None,)])
            self.assertEqual([self.db.admin(f"SELECT count(*) FROM marong.{table}")[0][0]
                              for table in TABLE_ROWS], [0] * len(TABLE_ROWS))

    def test_checks_accept_valid_rows_and_reject_invalid_changes(self):
        with psycopg.connect(self.db.app_url) as conn:
            for table, (columns, values) in TABLE_ROWS.items():
                conn.execute(f"INSERT INTO marong.{table}({columns}) VALUES {values}")
            conn.execute("""
                UPDATE marong.characters SET personality=%s, owner_call='누나', intro_at=now(), photo_pick=%s
                WHERE id=1
            """, (["먹보"], Jsonb({"photo": "photo_2", "box": [0.2, 0.1, 0.5, 0.8]})))
            invalid = [
                ("UPDATE marong.characters SET personality=%s", (["목록 밖"],)),
                ("UPDATE marong.characters SET personality=%s", (["먹보", "얌전함", "활발함", "느긋함"],)),
                ("UPDATE marong.characters SET owner_call=NULL", ()),
                ("UPDATE marong.characters SET likes=%s", ("가" * 61,)),
                ("UPDATE marong.characters SET photo_pick=%s", (Jsonb({"photo": "photo_4", "box": [0, 0, 1, 1]}),)),
                ("UPDATE marong.characters SET photo_pick=%s", (Jsonb({"photo": "photo_2", "box": [0, 0, 1]}),)),
                ("UPDATE marong.characters SET photo_pick=%s", (Jsonb([1, 2]),)),
                ("UPDATE marong.characters SET photo_pick=%s", (Jsonb({}),)),
                ("UPDATE marong.characters SET photo_pick=%s", (Jsonb({"photo": "photo_2", "box": {}}),)),
                ("UPDATE marong.decor_items SET slot='body' WHERE kind='hat'", ()),
                ("UPDATE marong.decor_items SET slot=NULL WHERE kind='hat'", ()),
                ("UPDATE marong.decor_items SET price_krw=100", ()),
                ("UPDATE marong.decor_items SET kind='gacha' WHERE kind='paper'", ()),
                ("UPDATE marong.decor_items SET kind='sticker', starter=true WHERE kind='paper'", ()),
                ("UPDATE marong.decor_items SET state='unlisted'", ()),
                ("UPDATE marong.scene_pictures SET topic=NULL", ()),
                ("UPDATE marong.scene_pictures SET purpose='reaction', item_id='hat-one'", ()),
                ("UPDATE marong.scene_pictures SET purpose='diary', topic=NULL", ()),
                ("UPDATE marong.scene_pictures SET state='budget'", ()),
                ("UPDATE marong.scene_pictures SET state='done', finished_at=now()", ()),
                ("UPDATE marong.scene_pictures SET state='drawing'", ()),
                ("""UPDATE marong.scene_pictures SET purpose='reaction', topic=NULL, item_id='hat-one',
                    state='done', finished_at=now(), fallback=true, cost_usd=0.025,
                    format='png', width=1024, height=1024, image=%s""", (b"picture",)),
                ("UPDATE marong.outfit_firsts SET state='sent', finished_at=now()", ()),
                ("UPDATE marong.outfit_firsts SET state='done', finished_at=now()", ()),
                ("UPDATE marong.friend_profiles SET voice_source='recommended' WHERE voice IS NULL", ()),
                ("UPDATE marong.diary_stickers SET x=1001", ()),
                ("UPDATE marong.diary_stickers SET scale=49", ()),
                ("UPDATE marong.diary_stickers SET rotation=181", ()),
            ]
            for stmt, params in invalid:
                with self.subTest(stmt=stmt, params=params), self.assertRaises(errors.CheckViolation), conn.transaction():
                    conn.execute(stmt, params)
            with self.assertRaises(errors.UniqueViolation), conn.transaction():
                conn.execute("INSERT INTO marong.outfit_firsts(friend_id, character_id, item_id, next_at) "
                             "VALUES (1, 1, 'hat-one', now())")
            conn.rollback()

    def test_roles_exercise_new_permissions(self):
        with psycopg.connect(self.db.app_url) as conn:
            for table, (columns, values) in TABLE_ROWS.items():
                key = columns.split(",")[0]
                name = sql.Identifier("marong", table)
                with self.subTest(table=table):
                    conn.execute(f"INSERT INTO marong.{table}({columns}) VALUES {values}")
                    self.assertTrue(conn.execute(sql.SQL("SELECT * FROM {}").format(name)).fetchall())
                    col = sql.Identifier(key)
                    conn.execute(sql.SQL("UPDATE {} SET {}={}").format(name, col, col))
                    with self.assertRaises(errors.InsufficientPrivilege), conn.transaction():
                        conn.execute(sql.SQL("DELETE FROM {}").format(name))
            conn.rollback()
        with psycopg.connect(self.db.admin_url, autocommit=True) as conn:
            conn.execute("SET ROLE marong_call")
            for statement in ("SELECT scene_picture_id FROM marong.app_rings",
                              "SELECT personality FROM marong.characters",
                              "SELECT voice_source FROM marong.friend_profiles"):
                conn.execute(statement)
            for table in TABLE_ROWS:
                name = sql.Identifier("marong", table)
                with self.subTest(table=table):
                    for command in ("SELECT * FROM {}", "INSERT INTO {} DEFAULT VALUES"):
                        with self.assertRaises(errors.InsufficientPrivilege):
                            conn.execute(sql.SQL(command).format(name))


if __name__ == "__main__":
    unittest.main()
