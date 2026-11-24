"""폴더 안의 강의자료를 한 사용자 계정에 한꺼번에 등록한다.

    python scripts/seed_lectures.py --dir ~/lectures --user 성진 --password pw-1234

강의자료 파일은 저장소에 넣지 않는다. 이 스크립트는 DB에만 등록한다.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import auth  # noqa: E402
from app.db import Store  # noqa: E402
from app.ingest import SUPPORTED  # noqa: E402
from app.llm import LLMClient  # noqa: E402
from app.worker import process_material  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, help="강의자료 폴더")
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", default=None, help="계정이 없을 때 만들 비밀번호")
    parser.add_argument("--match", default="", help="파일명에 이 글자가 들어간 것만")
    parser.add_argument("--db", default=os.environ.get("DB_PATH", "data/arena.db"))
    args = parser.parse_args()

    store = Store(args.db)
    store.migrate()
    user = store.get_user_by_name(args.user)
    if user is None:
        if not args.password:
            sys.exit("계정이 없습니다. --password 를 함께 주세요.")
        uid = store.create_user(args.user, auth.hash_password(args.password))
    else:
        uid = user["id"]

    llm = LLMClient.from_env()
    print(f"LLM: {'enabled' if llm.enabled else 'disabled (빈칸 문제로 대체)'}")
    for path in sorted(Path(args.dir).expanduser().iterdir()):
        if not path.name.lower().endswith(SUPPORTED) or path.name.startswith("~") or args.match not in path.name:
            continue
        material_id = store.add_material(uid, path.name, path.read_bytes())
        process_material(store, llm, material_id)
        m = store.get_material(material_id)
        print(f"{m['status']:>7}  {len(store.list_questions(material_id)):>3}문제  {path.name}")


if __name__ == "__main__":
    main()
