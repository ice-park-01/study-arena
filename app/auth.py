"""비밀번호 해시. 표준 라이브러리의 scrypt를 쓴다."""
from __future__ import annotations

import hashlib
import hmac
import secrets

MIN_PASSWORD = 6
MAX_NAME = 20


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _scheme, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def check_signup(name: str, password: str) -> str | None:
    """가입 입력의 문제를 한국어 문장으로 돌려준다. 문제가 없으면 None."""
    if not 1 <= len(name) <= MAX_NAME:
        return f"닉네임은 1~{MAX_NAME}자로 입력하세요."
    if len(password) < MIN_PASSWORD:
        return f"비밀번호는 {MIN_PASSWORD}자 이상이어야 합니다."
    return None
