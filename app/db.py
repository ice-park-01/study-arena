"""SQLite 저장소. 요청마다 연결을 새로 열어 스레드 문제를 피한다."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from app.quiz import Question
from app.timer import credit_seconds, split_by_day

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    # --- 구조 변경 --------------------------------------------------------

    def schema_version(self) -> int:
        with self.conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT)")
            row = c.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            return row["v"] or 0

    def migrate(self) -> int:
        """migrations/ 의 SQL 파일을 번호순으로 한 번씩만 적용한다."""
        current = self.schema_version()
        with self.conn() as c:
            c.execute("PRAGMA journal_mode = WAL")
        for path in sorted(MIGRATIONS.glob("*.sql")):
            version = int(path.name.split("_")[0])
            if version <= current:
                continue
            with self.conn() as c:
                c.executescript(path.read_text(encoding="utf-8"))
                c.execute("INSERT INTO schema_version VALUES (?, ?)", (version, _iso(datetime.now(timezone.utc))))
            current = version
        return current

    def get_meta(self, key: str) -> str | None:
        with self.conn() as c:
            row = c.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.conn() as c:
            c.execute("INSERT INTO meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                      (key, value))

    # --- 사용자 -----------------------------------------------------------

    def create_user(self, name: str, pw_hash: str, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        try:
            with self.conn() as c:
                cur = c.execute("INSERT INTO users (name, pw_hash, created_at) VALUES (?, ?, ?)",
                                (name, pw_hash, _iso(now)))
                return cur.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError("이미 사용 중인 닉네임입니다.") from exc

    def get_user(self, user_id: int):
        with self.conn() as c:
            return c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def get_user_by_name(self, name: str):
        with self.conn() as c:
            return c.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()

    # --- 자료, 조각, 문제 --------------------------------------------------

    def add_material(self, user_id: int, filename: str, data: bytes, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        with self.conn() as c:
            cur = c.execute("INSERT INTO materials (user_id, filename, created_at) VALUES (?, ?, ?)",
                            (user_id, filename, _iso(now)))
            c.execute("INSERT INTO uploads VALUES (?, ?)", (cur.lastrowid, data))
            return cur.lastrowid

    def get_material(self, material_id: int):
        with self.conn() as c:
            return c.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()

    def list_materials(self, user_id: int):
        with self.conn() as c:
            return c.execute(
                "SELECT m.*, (SELECT COUNT(*) FROM questions q WHERE q.material_id = m.id) AS n_questions "
                "FROM materials m WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()

    def get_upload(self, material_id: int) -> bytes:
        with self.conn() as c:
            return c.execute("SELECT data FROM uploads WHERE material_id = ?", (material_id,)).fetchone()["data"]

    def set_material_status(self, material_id: int, status: str, error: str | None = None,
                            n_chunks: int | None = None, discarded: int | None = None,
                            used_fallback: bool | None = None) -> None:
        with self.conn() as c:
            c.execute("UPDATE materials SET status = ?, error = ? WHERE id = ?", (status, error, material_id))
            for column, value in (("n_chunks", n_chunks), ("discarded", discarded),
                                  ("used_fallback", None if used_fallback is None else int(used_fallback))):
                if value is not None:
                    c.execute(f"UPDATE materials SET {column} = ? WHERE id = ?", (value, material_id))

    def add_chunks(self, material_id: int, texts: list[str]) -> list[int]:
        ids = []
        with self.conn() as c:
            for seq, text in enumerate(texts, start=1):
                cur = c.execute("INSERT INTO chunks (material_id, seq, text) VALUES (?, ?, ?)",
                                (material_id, seq, text))
                ids.append(cur.lastrowid)
        return ids

    def get_chunks(self, material_id: int) -> dict[int, str]:
        with self.conn() as c:
            rows = c.execute("SELECT id, text FROM chunks WHERE material_id = ? ORDER BY seq", (material_id,))
            return {row["id"]: row["text"] for row in rows}

    def get_chunk(self, chunk_id: int):
        with self.conn() as c:
            return c.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()

    def add_questions(self, material_id: int, questions: list[Question]) -> None:
        with self.conn() as c:
            for q in questions:
                c.execute(
                    "INSERT INTO questions (material_id, chunk_id, kind, prompt, choices, answer, keywords, quote) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (material_id, q.chunk_id, q.kind, q.prompt, json.dumps(q.choices, ensure_ascii=False),
                     q.answer, json.dumps(q.keywords, ensure_ascii=False), q.quote))

    def list_questions(self, material_id: int):
        with self.conn() as c:
            return c.execute("SELECT * FROM questions WHERE material_id = ? ORDER BY id", (material_id,)).fetchall()

    def get_question(self, question_id: int):
        with self.conn() as c:
            return c.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()

    @staticmethod
    def to_question(row) -> Question:
        return Question(row["kind"], row["prompt"], row["answer"], row["chunk_id"],
                        choices=json.loads(row["choices"]), keywords=json.loads(row["keywords"]), quote=row["quote"])

    # --- 풀이 -------------------------------------------------------------

    def add_attempt(self, user_id: int, question_id: int, answer: str, correct: bool, feedback: str,
                    graded_by: str, now: datetime) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO attempts (user_id, question_id, answer, correct, feedback, graded_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, question_id, answer, int(correct), feedback, graded_by, _iso(now)))

    _LATEST = (
        "SELECT a.question_id, a.correct FROM attempts a "
        "WHERE a.user_id = :uid AND a.id = (SELECT MAX(id) FROM attempts "
        "WHERE user_id = :uid AND question_id = a.question_id)"
    )

    def next_question(self, user_id: int, material_id: int):
        """아직 안 푼 문제 → 마지막에 틀린 문제 순으로 고른다. 다 맞혔으면 None."""
        with self.conn() as c:
            return c.execute(
                f"SELECT q.* FROM questions q LEFT JOIN ({self._LATEST}) l ON l.question_id = q.id "
                "WHERE q.material_id = :mid AND (l.correct IS NULL OR l.correct = 0) "
                "ORDER BY (l.correct IS NOT NULL), q.id LIMIT 1",
                {"uid": user_id, "mid": material_id}).fetchone()

    def wrong_questions(self, user_id: int):
        with self.conn() as c:
            return c.execute(
                f"SELECT q.*, m.filename FROM questions q JOIN ({self._LATEST}) l ON l.question_id = q.id "
                "JOIN materials m ON m.id = q.material_id WHERE l.correct = 0 ORDER BY q.id",
                {"uid": user_id}).fetchall()

    def material_progress(self, user_id: int, material_id: int) -> dict:
        with self.conn() as c:
            total = c.execute("SELECT COUNT(*) AS n FROM questions WHERE material_id = ?",
                              (material_id,)).fetchone()["n"]
            solved = c.execute(
                f"SELECT COUNT(*) AS n FROM questions q JOIN ({self._LATEST}) l ON l.question_id = q.id "
                "WHERE q.material_id = :mid AND l.correct = 1", {"uid": user_id, "mid": material_id}).fetchone()["n"]
            attempts = c.execute(
                "SELECT COUNT(*) AS n FROM attempts a JOIN questions q ON q.id = a.question_id "
                "WHERE a.user_id = ? AND q.material_id = ?", (user_id, material_id)).fetchone()["n"]
        return {"total": total, "solved": solved, "attempts": attempts}

    # --- 공부 시간 ---------------------------------------------------------

    def last_tick(self, user_id: int) -> datetime | None:
        with self.conn() as c:
            row = c.execute("SELECT at FROM last_seen WHERE user_id = ?", (user_id,)).fetchone()
            return _parse(row["at"]) if row else None

    def record_tick(self, user_id: int, now: datetime) -> int:
        """신호 하나를 기록하고 인정된 초를 돌려준다. 시각은 서버가 정한다."""
        with self.conn() as c:
            c.execute("BEGIN IMMEDIATE")  # 탭 두 개가 동시에 보내도 순서대로 처리한다
            row = c.execute("SELECT at FROM last_seen WHERE user_id = ?", (user_id,)).fetchone()
            credited = credit_seconds(_parse(row["at"]) if row else None, now)
            for day, seconds in split_by_day(now, credited):
                c.execute("INSERT INTO ticks (user_id, at, day, credited) VALUES (?, ?, ?, ?)",
                          (user_id, _iso(now), day.isoformat(), seconds))
            c.execute("INSERT INTO last_seen VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET at = excluded.at",
                      (user_id, _iso(now)))
        return credited

    def clear_last_tick(self, user_id: int) -> None:
        """공부를 멈췄다. 다음 신호는 새 세션의 첫 신호가 된다."""
        with self.conn() as c:
            c.execute("DELETE FROM last_seen WHERE user_id = ?", (user_id,))

    def seconds_on(self, user_id: int, day: date) -> int:
        return self.seconds_between([user_id], day, day).get(user_id, 0)

    def seconds_between(self, user_ids: list[int], first: date, last: date) -> dict[int, int]:
        if not user_ids:
            return {}
        marks = ",".join("?" * len(user_ids))
        with self.conn() as c:
            rows = c.execute(
                f"SELECT user_id, SUM(credited) AS s FROM ticks WHERE user_id IN ({marks}) "
                "AND day BETWEEN ? AND ? GROUP BY user_id",
                (*user_ids, first.isoformat(), last.isoformat())).fetchall()
        totals = {uid: 0 for uid in user_ids}
        totals.update({row["user_id"]: row["s"] for row in rows})
        return totals

    def last_ticks(self, user_ids: list[int]) -> dict[int, datetime]:
        if not user_ids:
            return {}
        marks = ",".join("?" * len(user_ids))
        with self.conn() as c:
            rows = c.execute(f"SELECT user_id, at FROM last_seen WHERE user_id IN ({marks})", user_ids).fetchall()
        return {row["user_id"]: _parse(row["at"]) for row in rows}

    # --- 그룹 -------------------------------------------------------------

    def create_group(self, owner_id: int, name: str, code: str, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        with self.conn() as c:
            cur = c.execute("INSERT INTO groups (name, code, owner_id, created_at) VALUES (?, ?, ?, ?)",
                            (name, code, owner_id, _iso(now)))
            c.execute("INSERT INTO memberships VALUES (?, ?)", (cur.lastrowid, owner_id))
            return cur.lastrowid

    def get_group(self, group_id: int):
        with self.conn() as c:
            return c.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()

    def get_group_by_code(self, code: str):
        with self.conn() as c:
            return c.execute("SELECT * FROM groups WHERE code = ?", (code,)).fetchone()

    def join_group(self, group_id: int, user_id: int) -> bool:
        """새로 가입했으면 True, 이미 가입돼 있었으면 False."""
        with self.conn() as c:
            cur = c.execute("INSERT OR IGNORE INTO memberships VALUES (?, ?)", (group_id, user_id))
            return cur.rowcount == 1

    def list_groups(self, user_id: int):
        with self.conn() as c:
            return c.execute(
                "SELECT g.*, (SELECT COUNT(*) FROM memberships WHERE group_id = g.id) AS n_members "
                "FROM groups g JOIN memberships m ON m.group_id = g.id WHERE m.user_id = ? ORDER BY g.id",
                (user_id,)).fetchall()

    def members(self, group_id: int):
        with self.conn() as c:
            return c.execute(
                "SELECT u.id, u.name FROM users u JOIN memberships m ON m.user_id = u.id WHERE m.group_id = ?",
                (group_id,)).fetchall()

    def is_member(self, group_id: int, user_id: int) -> bool:
        with self.conn() as c:
            return c.execute("SELECT 1 FROM memberships WHERE group_id = ? AND user_id = ?",
                             (group_id, user_id)).fetchone() is not None

    # --- 작업 -------------------------------------------------------------

    def enqueue_job(self, material_id: int) -> None:
        with self.conn() as c:
            c.execute("INSERT INTO jobs (material_id) VALUES (?)", (material_id,))

    def claim_job(self) -> int | None:
        with self.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT id, material_id FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
            if row is None:
                return None
            c.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (row["id"],))
            return row["material_id"]

    def requeue_interrupted_jobs(self) -> int:
        """작업자가 처리 도중 교체돼 멈춘 작업을 처음부터 다시 하도록 되돌린다."""
        with self.conn() as c:
            rows = c.execute("SELECT material_id FROM jobs WHERE status = 'running'").fetchall()
            for row in rows:
                mid = row["material_id"]
                c.execute("DELETE FROM questions WHERE material_id = ?", (mid,))
                c.execute("DELETE FROM chunks WHERE material_id = ?", (mid,))
                c.execute("UPDATE materials SET status = 'queued', error = NULL WHERE id = ?", (mid,))
            c.execute("UPDATE jobs SET status = 'queued' WHERE status = 'running'")
            return len(rows)

    def finish_job(self, material_id: int) -> None:
        with self.conn() as c:
            c.execute("UPDATE jobs SET status = 'done' WHERE material_id = ?", (material_id,))

    # --- LLM 기록 ---------------------------------------------------------

    def log_llm(self, purpose: str, now: datetime, calls: int = 0, failures: int = 0, discarded: int = 0,
                fallback: bool = False) -> None:
        with self.conn() as c:
            c.execute("INSERT INTO llm_log (at, purpose, calls, failures, discarded, fallback) VALUES (?,?,?,?,?,?)",
                      (_iso(now), purpose, calls, failures, discarded, int(fallback)))

    def llm_summary(self) -> dict:
        with self.conn() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(calls),0) AS calls, COALESCE(SUM(failures),0) AS failures, "
                "COALESCE(SUM(discarded),0) AS discarded, COALESCE(SUM(fallback),0) AS fallbacks FROM llm_log"
            ).fetchone()
            recent = c.execute("SELECT * FROM llm_log ORDER BY id DESC LIMIT 15").fetchall()
            questions = c.execute("SELECT kind, COUNT(*) AS n FROM questions GROUP BY kind").fetchall()
        return {**dict(row), "recent": [dict(r) for r in recent], "questions": {r["kind"]: r["n"] for r in questions}}
