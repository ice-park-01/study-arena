"""스터디 그룹의 초대 코드와 순위 계산."""
from __future__ import annotations

import random
from dataclasses import dataclass

# 헷갈리는 글자(0 O 1 I L)는 뺀다.
INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
INVITE_LENGTH = 6


@dataclass(frozen=True)
class RankRow:
    rank: int
    name: str
    seconds: int
    studying: bool


def new_invite_code(rng: random.Random) -> str:
    return "".join(rng.choice(INVITE_ALPHABET) for _ in range(INVITE_LENGTH))


def rank(totals: dict[str, int], studying: set[str]) -> list[RankRow]:
    """공부 시간이 많은 순서. 동점은 같은 순위이고 다음 순위는 건너뛴다."""
    ordered = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    rows: list[RankRow] = []
    for position, (name, seconds) in enumerate(ordered, start=1):
        if rows and rows[-1].seconds == seconds:
            place = rows[-1].rank
        else:
            place = position
        rows.append(RankRow(place, name, seconds, name in studying))
    return rows
