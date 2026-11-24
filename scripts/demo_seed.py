"""시연용 가짜 데이터: 친구 계정, 스터디 그룹, 이번 주 공부 기록을 만든다.

실제 공부 기록이 아니다. 화면 시연과 캡처에만 쓴다.

    docker compose exec -T web python - --me 성진 < scripts/demo_seed.py
    python scripts/demo_seed.py --me 성진            (Docker 없이 실행할 때)
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.getcwd())
if "__file__" in globals():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import auth  # noqa: E402
from app.db import Store  # noqa: E402

# (이름, 오늘 공부한 분, 지금 공부 중인지, 지난 며칠의 공부 분)
FRIENDS = [("가현", 130, True, [95, 120]), ("민수", 40, False, [150, 30]), ("지우", 75, False, [60, 80])]


def study(store: Store, uid: int, end: datetime, minutes: int) -> None:
    """end 시각에 끝나는 minutes분짜리 공부 세션을 30초 신호로 기록한다."""
    start = end - timedelta(minutes=minutes)
    for i in range(minutes * 2 + 1):
        store.record_tick(uid, start + timedelta(seconds=30 * i))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--me", required=True, help="이미 가입한 내 닉네임")
    parser.add_argument("--my-minutes", type=int, default=85)
    parser.add_argument("--group", default="오픈소스 기말 스터디")
    parser.add_argument("--password", default="demo-pass-1")
    parser.add_argument("--db", default=os.environ.get("DB_PATH", "data/arena.db"))
    args = parser.parse_args()

    store = Store(args.db)
    store.migrate()
    me = store.get_user_by_name(args.me)
    if me is None:
        sys.exit(f"'{args.me}' 계정이 없습니다. 먼저 가입하세요.")
    now = datetime.now(timezone.utc)

    group = next((g for g in store.list_groups(me["id"]) if g["name"] == args.group), None)
    group_id = group["id"] if group else store.create_group(me["id"], args.group, "KHU26A")
    for days_ago, minutes in ((2, 70), (1, 110)):
        study(store, me["id"], now - timedelta(days=days_ago), minutes)
    study(store, me["id"], now - timedelta(minutes=3), args.my_minutes)

    for name, today, studying, history in FRIENDS:
        user = store.get_user_by_name(name)
        uid = user["id"] if user else store.create_user(name, auth.hash_password(args.password))
        store.join_group(group_id, uid)
        for days_ago, minutes in zip((2, 1), history):
            study(store, uid, now - timedelta(days=days_ago), minutes)
        study(store, uid, now if studying else now - timedelta(minutes=20), today)
    print(f"group {group_id} ready, invite code {store.get_group(group_id)['code']}")


if __name__ == "__main__":
    main()
