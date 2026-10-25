"""시험용 Postgres. pgserver(pip 로 설치되는 Postgres 16 + pgvector)를 임시 폴더에 띄우고,
서버와 똑같이 marong DB 를 만들어 marong/schema.sql 을 슈퍼유저로 적용한다.
봇은 서버와 같은 'marong' 계정(지우기 권한 없음)으로 접속한다.
pgserver 는 시험에만 쓰므로 requirements.txt 에 없다: pip install pgserver"""
import tempfile
from pathlib import Path

import pgserver
import psycopg

ROOT = Path(__file__).resolve().parent.parent


class TestDB:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="marong-pg-")  # 경로에 빈칸이 없어야 함
        self.srv = pgserver.get_server(self.dir, cleanup_mode="stop")
        with psycopg.connect(self.srv.get_uri(), autocommit=True) as c:
            c.execute("CREATE DATABASE marong")
        self.admin_url = self.srv.get_uri("marong")
        self.apply_schema()
        self.app_url = self.admin_url.replace("postgres:@", "marong@", 1)

    def apply_schema(self) -> None:
        sql = (ROOT / "marong" / "schema.sql").read_text(encoding="utf-8")
        with psycopg.connect(self.admin_url, autocommit=True) as c:
            c.execute(sql)

    def admin(self, sql: str, params=()) -> list[tuple]:
        """슈퍼유저로 읽기(시험 확인용)."""
        with psycopg.connect(self.admin_url, autocommit=True) as c:
            cur = c.execute(sql, params)
            return cur.fetchall() if cur.description else []

    def close(self) -> None:
        self.srv.cleanup()
