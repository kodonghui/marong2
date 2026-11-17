"""Diary rules with synthetic scenes (TC-163)."""

import sys
import unittest
import asyncio
import io
import os
import subprocess
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from marong.diary import DAY_LIMIT, KST, DiaryLine, bundle_lines, diary_day, read_day_bundle, scene_error
from marong.diary_admin import DiaryAdminError, command, setting
from pg import ROOT, TestDB


def at(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=KST)


class DayRules(unittest.TestCase):
    def test_time_exclusion_and_formatting(self):
        lines = [
            DiaryLine(at(16, 17, 56), "kakao", "user", "KEEP"),
            DiaryLine(at(16, 17, 58), "kakao", "assistant", "omit-answer"),
            DiaryLine(at(16, 17, 59), "kakao", "user", "omit-topic"),
            DiaryLine(at(16, 17, 59), "dm", "user", "DM-only"),
            DiaryLine(at(16, 18), "kakao", "user", "일기에는 쓰지 말아 줘"),
            DiaryLine(at(17, 3), "call", "assistant", "call-part-one", 13),
            DiaryLine(at(17, 3, 1), "call", "assistant", "call-part-two", 13),
        ]
        self.assertEqual(diary_day(at(17, 3, 59)), date(2026, 11, 16))
        self.assertEqual(diary_day(at(17, 4)), date(2026, 11, 17))
        data = bundle_lines(lines)
        self.assertIn("KEEP", data.value)
        self.assertIn("DM-only", data.value)
        self.assertIn("일기 제외 요청", data.value)
        self.assertIn("call-part-one call-part-two", data.value)
        self.assertNotIn("omit-", data.value)
        self.assertEqual(data.friend_chars, 11)

    def test_friend_count_before_trimming(self):
        self.assertFalse(bundle_lines([DiaryLine(at(16, 14), "kakao", "user", "가 " * 39)]).enough)
        self.assertTrue(bundle_lines([DiaryLine(at(16, 14), "kakao", "user", "가 " * 40)]).enough)
        lines = [DiaryLine(at(16, 4) + timedelta(minutes=i), "dm", "assistant", "O" * 320) for i in range(48)]
        lines.append(DiaryLine(at(16, 4), "dm", "user", "K" * 300))
        result = bundle_lines(lines)
        self.assertLessEqual(len(result.value), DAY_LIMIT)
        self.assertTrue(all(len(line) <= 300 for line in result.value.splitlines()))
        self.assertIn("앞의 대화", result.value)
        self.assertIn("K" * 40, result.value)
        self.assertEqual(result.friend_chars, 300)


class SceneRules(unittest.TestCase):
    def test_valid_scenes(self):
        for scene in (
            "The little white character carries a basket.",
            "Under the stars, a chestnut rolls! A basket tips. The sky is clear?",
            "A " + "x" * 397 + ".",
        ):
            with self.subTest(scene=scene):
                self.assertIsNone(scene_error(scene))

    def test_look_card_only_allows_the_friend(self):
        scene = "The friend holds a basket. The little white character sits near the friend."
        self.assertEqual(scene_error(scene), "person")
        self.assertIsNone(scene_error(scene, has_look=True))
        self.assertEqual(scene_error("A friend holds a basket.", has_look=True), "person")
        self.assertEqual(scene_error("The friend holds a basket for a child.", has_look=True), "person")

    def test_rejection_codes(self):
        cases = {
            "A " + "x" * 398 + ".": "too_long",
            "The 하늘 is clear.": "korean",
            "A 2nd basket tips.": "digits",
            "The phone rings at 010-0000-0000.": "digits",
            "On a plaque is test@example.com.": "contact",
            "The www.example.test address is visible.": "contact",
            "A sign says HTTP.": "contact",
            "": "first_word",
            "The sky is clear": "first_word",
            "A basket tips. The rain falls. A light shines. A cloud drifts.": "first_word",
            "Clouds roll past the window.": "first_word",
            "The чужое is clear.": "first_word",
            "A toy called Example is outside.": "capital",
            "The student carries a basket.": "person",
        }
        for scene, code in cases.items():
            with self.subTest(code=code, scene=scene):
                self.assertEqual(scene_error(scene, has_look=True), code)


class DiaryWithPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db = cls.db = TestDB()
        cls.addClassCleanup(db.close)
        call = ROOT / "marong" / "call"
        steps = [call / "schema.sql", *sorted((call / "migrations").glob("00[2-4]*.sql")),
                 ROOT / "marong/migrations/010_discord_dm.sql",
                 *sorted((call / "migrations").glob("00[5-6]*.sql"))]
        for path in steps:
            db.admin(path.read_text(encoding="utf-8"), None)
        db.admin("""
            INSERT INTO marong.friends(name) VALUES ('fixture-alpha'), ('fixture-beta');
            INSERT INTO marong.rooms(room_key,is_channel) VALUES
                ('fixture-kakao',true),('discord-dm:100000000000000001',true),('fixture-group',false);
            INSERT INTO marong.people(user_key,friend_id) VALUES
                ('fixture-a',1),('discord-user:100000000000000001',1),('fixture-b',2);
            INSERT INTO marong.discord_dm_links (
                discord_user_id, friend_id, room_key,kakao_room_key,user_key,channel_id,last_incoming_at,
                per_day,start_hour,end_hour
            ) VALUES (
                '100000000000000001',1,'discord-dm:100000000000000001','fixture-kakao',
                'discord-user:100000000000000001','100000000000000002',now(),1,8,22
            );
            INSERT INTO call.callers(friend_id) VALUES (1), (2);
            INSERT INTO marong.messages(room_key,user_key,role,content,created_at,meta) VALUES
                ('fixture-kakao','fixture-a','user','Kakao fixture','2026-11-16 04:00+09','{}'),
                ('discord-dm:100000000000000001','discord-user:100000000000000001','user',
                    '[사진] photo-caption-marker','2026-11-16 12:00+09','{}'),
                ('fixture-kakao',NULL,'assistant','not-delivered','2026-11-16 12:00+09','{"delivered":false}'),
                ('fixture-kakao',NULL,'assistant','notice-excluded','2026-11-16 12:00+09','{"diary":true}'),
                ('fixture-kakao','fixture-a','user','forgotten-kakao','2026-11-16 12:00+09','{}'),
                ('fixture-group','fixture-a','user','group-excluded','2026-11-16 12:00+09','{}'),
                ('fixture-kakao','fixture-a','user','next-day-only','2026-11-17 04:00+09','{}');
            INSERT INTO call.source_exclusions(caller_id,source_type,source_id)
                SELECT c.id,'kakao_message',m.id::text FROM call.callers c CROSS JOIN marong.messages m
                WHERE c.friend_id=1 AND m.content='forgotten-kakao';
            INSERT INTO call.calls (caller_id,status,client_id,prompt_version,voice,ended_at,end_reason,organize_status)
                SELECT id,'ended',gen_random_uuid(),'fixture','fixture',now(),'hangup','pending' FROM call.callers;
            INSERT INTO call.segments(call_id,mode,client_id)
                SELECT id,'start',client_id FROM call.calls;
            INSERT INTO call.turns(call_id,segment_id,seq,role,content,started_at,ended_at,finalized,interrupted,forgotten_at)
                SELECT s.call_id, s.id, v.seq,'user',v.content,'2026-11-17 02:30+09','2026-11-17 02:31+09',
                    v.finalized,v.interrupted,CASE WHEN v.forgotten THEN now() END
                FROM call.segments s JOIN call.calls c ON c.id=s.call_id JOIN call.callers owner ON owner.id=c.caller_id
                CROSS JOIN (VALUES (1,'Call fixture',true,false,false),
                                   (2,'unsaved-turn',false,false,false),
                                   (3,'interrupted-turn',true,true,false),
                                   (4,'forgotten-turn',true,false,true)) v(seq,content,finalized,interrupted,forgotten)
                WHERE owner.friend_id=1;
            INSERT INTO call.turns(call_id,segment_id,seq,role,content,started_at,ended_at)
                SELECT s.call_id,s.id,1,'user','other-friend','2026-11-16 13:00+09','2026-11-16 13:01+09'
                FROM call.segments s JOIN call.calls c ON c.id=s.call_id JOIN call.callers owner ON owner.id=c.caller_id
                WHERE owner.friend_id=2;
        """, None)

    def test_read_bundle_with_bot_permissions(self):
        async def read():
            async with await psycopg.AsyncConnection.connect(self.db.app_url) as conn:
                return await read_day_bundle(conn, 1, date(2026, 11, 16))

        value = asyncio.run(read()).value
        self.assertLess(value.index("Kakao fixture"), value.index("[사진]"))
        self.assertLess(value.index("[사진]"), value.index("Call fixture"))
        for private in ("photo-caption-marker", "not-delivered", "notice-excluded", "group-excluded",
                        "forgotten-kakao", "unsaved-turn", "interrupted-turn", "forgotten-turn",
                        "other-friend", "next-day-only"):
            self.assertNotIn(private, value)

    def test_diary_admin_on_off_rerun_and_month(self):
        output = io.StringIO()
        with psycopg.connect(self.db.app_url, row_factory=dict_row) as conn, redirect_stdout(output):
            def run(args, now):
                command(conn, args, lambda *_: 1, now, Decimal(5))

            run(["fixture", "off", "--now"], at(16, 14))
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM marong.diary_settings").fetchone()["n"], 0)
            with self.assertRaises(DiaryAdminError):
                run(["fixture", "on", "--now"], at(16, 14))
            run(["fixture", "on"], at(16, 15))
            run(["fixture", "on"], at(16, 16))
            self.assertIsNone(setting(conn, 1, date(2026, 11, 16)))
            self.assertTrue(setting(conn, 1, date(2026, 11, 17))["enabled"])
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM marong.diary_settings").fetchone()["n"], 1)
            with self.assertRaises(DiaryAdminError):
                run(["fixture", "run", "2026-11-16"], at(18, 12))
            with self.assertRaises(DiaryAdminError):
                run(["fixture", "run", "2026-11-17"], at(25, 12))
            run(["fixture", "run", "2026-11-17"], at(18, 12))
            conn.execute(
                """INSERT INTO marong.diary_revisions(diary_id,revision,source,title,weather,body)
                SELECT id,1,'weather','시험 일기','sunny',repeat('밤',60) FROM marong.diaries WHERE friend_id=1"""
            )
            conn.execute("UPDATE marong.diaries SET state='ready',revision=1,ready_at=now() WHERE friend_id=1")
            with self.assertRaises(DiaryAdminError):
                run(["fixture", "run", "2026-11-17"], at(18, 12))
            self.assertEqual(conn.execute("SELECT state FROM marong.diaries").fetchone()["state"], "ready")
            conn.execute("UPDATE marong.diaries SET state='writing',ready_at=NULL,lease_until=now() WHERE friend_id=1")
            run(["fixture", "off", "--now"], at(18, 4, 5))
            self.assertFalse(setting(conn, 1, date(2026, 11, 17))["enabled"])
            self.assertEqual(conn.execute("SELECT fail_reason FROM marong.diaries").fetchone()["fail_reason"], "off")
            run(["status"], at(18, 12))
            run(["month", "2026-11"], at(18, 12))
        self.assertIn("이미 켜져 있어요.", output.getvalue())
        self.assertIn("failed=1", output.getvalue())
        self.assertNotIn("Call fixture", output.getvalue())
        self.assertNotIn("시험 일기", output.getvalue())
        process = subprocess.run(
            [sys.executable, str(ROOT / "tools/admin.py"), "diary", "fixture-alpha", "run", "2000-01-01"],
            env={**os.environ, "DATABASE_URL": self.db.app_url}, cwd=ROOT,
            capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertIn("최근 7일", process.stderr)


if __name__ == "__main__":
    unittest.main()
