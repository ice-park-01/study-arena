# Study Arena 프로젝트 규칙

강의자료로 문제를 풀고 친구와 공부 시간을 겨루는 FastAPI 서비스다.

## 개발 순서 (TDD)

1. 구현 전에 실패하는 테스트를 먼저 쓴다.
2. `pytest`로 **기대한 이유로** 실패하는지 확인한다.
3. 테스트만 먼저 커밋한다: `test: ...`
4. 테스트를 통과시키는 최소한의 구현을 쓴다.
5. 전체 테스트가 통과하면 커밋한다: `feat: ...` 또는 `fix: ...`
6. 정리가 필요하면 테스트가 통과하는 상태에서만 고치고 `refactor: ...`로 커밋한다.

## 반드시 지킬 것

- 테스트는 실제 LLM이나 네트워크를 부르지 않는다. `LLMClient`에 가짜 `post`를 주입한다.
- 현재 시각이 필요한 함수는 시각을 인자로 받는다. 함수 안에서 `datetime.now()`를 부르지 않는다.
- API 키는 환경 변수 `FACTCHAT_API_KEY`로만 읽는다. 코드, 테스트, 문서 예시에 실제 키를 쓰지 않는다.
- LLM 응답은 그대로 믿지 않는다. `app/quiz.py`의 검증을 통과한 것만 저장한다.
- `data/`, `materials/`, `.env`는 커밋하지 않는다.

## 구조

- `app/quiz.py`, `app/timer.py`, `app/groups.py`: DB와 네트워크를 모르는 순수 로직
- `app/llm.py`: ChatKHU 호출, 재시도, 대체 동작
- `app/db.py`: SQLite 저장소
- `app/main.py`: 화면과 API

## 명령

- 테스트: `python -m pytest -q`
- 실행: `uvicorn app.main:app --reload`
- 컨테이너 실행: `docker compose up --build`
