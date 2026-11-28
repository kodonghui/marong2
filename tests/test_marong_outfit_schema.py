"""TC-770: default outfit migration and rollback drain on a disposable database."""
import unittest

import psycopg

from pg import TestDB, ROOT


class MarongOutfitSchemaTest(unittest.TestCase):
    def test_tc770_migration_and_rollback(self):
        db = TestDB()
        self.addCleanup(db.close)
        db.apply_unified_prerequisites()
        db.apply_unified()
        db.apply_pet_app_prerequisites()
        db.apply_pet_app()
        db.apply_sql(ROOT / 'marong' / 'migrations' / '023_app_update_events.sql')
        db.apply_marong_outfit()
        db.apply_marong_outfit()
        friend = db.admin("INSERT INTO marong.friends(name) VALUES ('fixture') RETURNING id")[0][0]
        db.admin("INSERT INTO marong.decor_items(id,kind,slot) VALUES ('fixture-hat','hat','head')")
        with psycopg.connect(db.app_url, autocommit=True) as conn:
            conn.execute("INSERT INTO marong.marong_outfits(friend_id,head) VALUES (%s,'fixture-hat')", (friend,))
            conn.execute("UPDATE marong.marong_outfits SET head=NULL WHERE friend_id=%s", (friend,))
            for query, params in (
                ("DELETE FROM marong.marong_outfits WHERE friend_id=%s", (friend,)),
                ("INSERT INTO marong.marong_outfits(friend_id) VALUES (%s)", (friend,)),
                ("UPDATE marong.marong_outfits SET head='missing-item' WHERE friend_id=%s", (friend,)),
            ):
                with self.assertRaises(psycopg.Error):
                    conn.execute(query, params)
        with psycopg.connect(db.admin_url, autocommit=True) as conn:
            conn.execute("SET ROLE marong_call")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute("SELECT * FROM marong.marong_outfits")
        db.admin("INSERT INTO marong.outfit_firsts(friend_id,item_id,next_at) VALUES (%s,'fixture-hat',now())", (friend,))
        with self.assertRaises(psycopg.errors.UniqueViolation):
            db.admin("INSERT INTO marong.outfit_firsts(friend_id,item_id,next_at) VALUES (%s,'fixture-hat',now())", (friend,))
        with self.assertRaises(psycopg.errors.CheckViolation):
            db.admin("INSERT INTO marong.scene_pictures(friend_id,purpose,topic) VALUES (%s,'topic','v1/topic')", (friend,))
        with self.assertRaises(psycopg.errors.CheckViolation):
            db.admin("INSERT INTO marong.scene_pictures(friend_id,purpose,item_id,state,fail_reason,finished_at) VALUES (%s,'reaction','fixture-hat','failed','unknown',now())", (friend,))
        for state in ("queued", "drawing"):
            db.admin("INSERT INTO marong.scene_pictures(friend_id,purpose,item_id,state,lease_until) VALUES (%s,'reaction','fixture-hat',%s,now()+interval '10 minutes')", (friend, state))
        def remaining():
            return db.admin("SELECT (SELECT count(*) FROM marong.outfit_firsts WHERE character_id IS NULL AND state='waiting') + (SELECT count(*) FROM marong.scene_pictures WHERE character_id IS NULL AND state IN ('queued','drawing'))")[0][0]
        self.assertEqual(remaining(), 3)
        claim = """WITH due AS (
            SELECT id FROM marong.scene_pictures WHERE state='queued' AND not_before<=now() AND attempts<3
            ORDER BY not_before,created_at,id LIMIT 2 FOR UPDATE SKIP LOCKED
        ) UPDATE marong.scene_pictures s SET state='drawing',lease_until=now()+interval '10 minutes',
            started_at=now(),attempts=s.attempts+1 FROM due WHERE s.id=due.id RETURNING s.id"""
        with psycopg.connect(db.app_url) as conn:
            self.assertEqual(len(conn.execute(claim).fetchall()), 1)
            due = conn.execute("""SELECT r.id FROM marong.outfit_firsts r
                JOIN marong.characters c ON c.id=r.character_id
                LEFT JOIN marong.friend_profiles p ON p.friend_id=r.friend_id
                LEFT JOIN marong.outfits o ON o.character_id=c.id
                WHERE r.state='waiting' AND r.next_at<=now() ORDER BY r.next_at,r.id LIMIT 40""").fetchall()
            self.assertEqual(due, [])
            conn.rollback()
        self.assertEqual(remaining(), 3)
        db.admin("UPDATE marong.outfit_firsts SET state='skipped',finished_at=now() WHERE character_id IS NULL AND state='waiting'")
        db.admin("UPDATE marong.scene_pictures SET state='failed',fail_reason='disabled',finished_at=now() WHERE character_id IS NULL AND state='queued'")
        self.assertEqual(remaining(), 1)
        db.admin("UPDATE marong.scene_pictures SET state='failed',fail_reason='model_error',finished_at=now() WHERE character_id IS NULL AND state='drawing'")
        self.assertEqual(remaining(), 0)
        self.assertEqual(db.admin(claim), [])
        db.apply_marong_outfit()


if __name__ == '__main__':
    unittest.main()
