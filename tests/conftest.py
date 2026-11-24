import io
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.db import Store
from app.llm import LLMClient
from app.main import create_app


class Clock:
    """테스트가 시간을 마음대로 움직일 수 있는 시계."""

    def __init__(self):
        self.now = datetime(2026, 11, 24, 3, 0, 0, tzinfo=timezone.utc)  # 한국 시간 화요일 낮 12시

    def __call__(self):
        return self.now

    def tick(self, seconds):
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "test.db"))
    s.migrate()
    return s


@pytest.fixture
def app(tmp_path, clock):
    # 키가 없는 LLM: 실제 호출은 절대 일어나지 않고 빈칸 문제로 대체된다.
    return create_app(db_path=str(tmp_path / "web.db"), llm=LLMClient(api_key=None), now=clock, inline_jobs=True)


@pytest.fixture
def client(app):
    return TestClient(app)


def signup(app, name, password="pw-1234"):
    c = TestClient(app)
    r = c.post("/signup", data={"name": name, "password": password}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return c


NOTES = (
    "Test-driven development는 테스트를 먼저 작성하고 그 테스트를 통과하는 코드를 작성하는 개발 방법이다.\n\n"
    "Continuous integration은 코드를 올릴 때마다 자동으로 빌드하고 테스트해서 오류를 일찍 발견하게 한다.\n\n"
    "Docker는 애플리케이션을 실행에 필요한 모든 것과 함께 컨테이너 이미지로 묶는다."
)


def upload(c, text=NOTES, filename="강의노트.txt"):
    r = c.post("/materials", files={"file": (filename, io.BytesIO(text.encode("utf-8")), "text/plain")},
               follow_redirects=False)
    assert r.status_code == 303, r.text
    return int(r.headers["location"].rstrip("/").split("/")[-1])
