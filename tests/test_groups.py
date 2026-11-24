import random

from app.groups import INVITE_ALPHABET, RankRow, new_invite_code, rank


def test_invite_code_is_6_unambiguous_chars():
    code = new_invite_code(random.Random(1))
    assert len(code) == 6
    assert set(code) <= set(INVITE_ALPHABET)
    assert not set("0O1IL") & set(INVITE_ALPHABET)


def test_invite_code_depends_on_rng():
    assert new_invite_code(random.Random(1)) == new_invite_code(random.Random(1))
    assert new_invite_code(random.Random(1)) != new_invite_code(random.Random(2))


def test_rank_orders_by_seconds_desc():
    rows = rank({"가현": 600, "성진": 3600, "민수": 1200}, studying=set())
    assert [r.name for r in rows] == ["성진", "민수", "가현"]
    assert [r.rank for r in rows] == [1, 2, 3]


def test_ties_share_a_rank_and_skip_the_next():
    rows = rank({"b": 100, "a": 100, "c": 50}, studying=set())
    assert [(r.rank, r.name) for r in rows] == [(1, "a"), (1, "b"), (3, "c")]


def test_zero_second_members_are_listed():
    rows = rank({"가현": 0, "성진": 10}, studying={"가현"})
    assert rows[-1] == RankRow(rank=2, name="가현", seconds=0, studying=True)


def test_empty_group():
    assert rank({}, studying=set()) == []
