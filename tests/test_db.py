from datetime import date, datetime, timedelta, timezone

import pytest

from app.quiz import Question

T0 = datetime(2026, 11, 24, 3, 0, 0, tzinfo=timezone.utc)


def test_migrate_twice_is_safe(store):
    store.migrate()
    store.migrate()
    assert store.schema_version() >= 1


def test_duplicate_name_is_rejected(store):
    store.create_user("성진", "hash")
    with pytest.raises(ValueError):
        store.create_user("성진", "hash2")


def test_ticks_accumulate_by_the_credit_rules(store):
    uid = store.create_user("성진", "hash")
    credited = [store.record_tick(uid, T0 + timedelta(seconds=s)) for s in (0, 30, 60, 300, 330)]
    assert credited == [0, 30, 30, 0, 30]
    assert store.seconds_on(uid, date(2026, 11, 24)) == 90


def test_totals_are_grouped_by_korean_date(store):
    uid = store.create_user("성진", "hash")
    late = datetime(2026, 11, 24, 14, 59, 30, tzinfo=timezone.utc)  # 한국 시간 23:59:30
    for s in (0, 30, 60):
        store.record_tick(uid, late + timedelta(seconds=s))
    assert store.seconds_on(uid, date(2026, 11, 24)) == 30
    assert store.seconds_on(uid, date(2026, 11, 25)) == 30
    totals = store.seconds_between([uid], date(2026, 11, 23), date(2026, 11, 29))
    assert totals == {uid: 60}


def test_joining_a_group_twice_keeps_one_membership(store):
    owner = store.create_user("성진", "h")
    friend = store.create_user("가현", "h")
    gid = store.create_group(owner, "오픈소스 스터디", "ABC234")
    assert store.join_group(gid, friend) is True
    assert store.join_group(gid, friend) is False
    assert sorted(m["name"] for m in store.members(gid)) == ["가현", "성진"]


def test_a_job_is_claimed_only_once(store):
    uid = store.create_user("성진", "h")
    mid = store.add_material(uid, "a.txt", b"data")
    store.enqueue_job(mid)
    assert store.claim_job() == mid
    assert store.claim_job() is None


def test_next_question_prefers_unanswered_then_wrong(store):
    uid = store.create_user("성진", "h")
    mid = store.add_material(uid, "a.txt", b"data")
    [cid] = store.add_chunks(mid, ["조각 본문"])
    store.add_questions(mid, [Question("cloze", "Q1", "a", cid), Question("cloze", "Q2", "b", cid)])
    q1 = store.next_question(uid, mid)
    store.add_attempt(uid, q1["id"], "a", True, "", "keywords", T0)
    q2 = store.next_question(uid, mid)
    assert q2["id"] != q1["id"]
    store.add_attempt(uid, q2["id"], "x", False, "", "keywords", T0)
    assert store.next_question(uid, mid)["id"] == q2["id"]  # 틀린 문제를 다시 낸다
    assert [w["id"] for w in store.wrong_questions(uid)] == [q2["id"]]
    assert store.material_progress(uid, mid) == {"total": 2, "solved": 1, "attempts": 2}
