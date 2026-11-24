# Study Arena Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 강의자료로 객관식·주관식 문제를 내 주고 친구와 공부 시간을 겨루는 웹 서비스를, HW6 조건(TDD·LLM·DevOps·Agent)을 모두 근거와 함께 보여주는 참조 구현으로 만든다.

**Architecture:** FastAPI 한 프로세스가 화면(Jinja2)과 API를 모두 제공하고, 같은 이미지를 명령만 바꿔 작업자로 실행한다. 저장은 SQLite 파일 하나다. 순수 로직(`quiz`, `timer`, `groups`)은 DB·네트워크와 분리하고 시계와 LLM을 인자로 주입한다.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, sqlite3(표준), httpx, python-pptx, pypdf, pytest, Docker Compose, GitHub Actions

**Spec:** `docs/2026-11-24-study-arena-design.md`

## Global Constraints

- 테스트는 실제 LLM·네트워크를 부르지 않는다.
- API 키는 환경 변수 `FACTCHAT_API_KEY`로만 받는다. 코드·이미지·커밋에 넣지 않는다.
- 기능마다 테스트 커밋(`test: …`)이 구현 커밋(`feat: …`)보다 먼저 온다.
- 강의자료 파일과 `data/`는 저장소에 넣지 않는다.
- 공부 시간: 신호 하나 최대 30초 인정, 90초 무신호면 세션 종료, 서버 시계만 사용, 날짜는 한국 시간.
- 주관식 핵심어 채점 기준은 60%.
- 개발은 로컬 디스크 `~/dev/study-arena`에서 하고(네트워크 드라이브에서 git 커밋 하나에 9초가 걸림), 결과물을 `hw6-demo/study-arena/`로 복사한다.

## Review Focus

1. 한글 파일명·한글 본문 pptx 업로드 → 깨지지 않고 조각으로 저장된다. (Task 4)
2. 본문이 없는 슬라이드(그림만 있는 장) → 조각을 만들지 않고 오류도 내지 않는다. (Task 4)
3. LLM이 JSON 앞뒤에 설명 문장이나 코드 블록 표시를 붙여 응답 → JSON만 뽑아 쓴다. (Task 5)
4. 같은 사용자가 탭 두 개에서 동시에 신호 → 시간이 두 배로 쌓이지 않는다. (Task 2)
5. 이미 가입한 그룹의 초대 코드를 다시 입력 → 중복 가입되지 않고 순위에 한 번만 나온다. (Task 7)

---

### Task 1: 문제 검증과 채점 (`app/quiz.py`)

**Files:** Create `app/quiz.py`, `tests/test_quiz.py`, `pyproject.toml`, `.gitignore`, `AGENTS.md`, `CLAUDE.md`

**Interfaces — Produces:**

```python
@dataclass(frozen=True)
class Question:
    kind: str            # "mcq" | "short" | "cloze"
    prompt: str
    choices: list[str]   # mcq만 4개, 나머지는 []
    answer: str
    keywords: list[str]  # short만 2~5개
    chunk_id: int

def validate_question(raw: dict, chunks: dict[int, str]) -> tuple[Question | None, str]  # (문제, 버린 이유)
def filter_valid(raws: list[dict], chunks: dict[int, str]) -> tuple[list[Question], int]  # (통과, 버린 수)
def grade_mcq(q: Question, selected: str) -> bool
def grade_by_keywords(answer: str, keywords: list[str], threshold: float = 0.6) -> bool
def make_cloze(chunk_id: int, text: str) -> Question | None
```

- [ ] 테스트 작성 (아래 이름과 기대값)
  - `test_mcq_valid_passes`
  - `test_missing_chunk_id_is_discarded` → 이유 `"no_evidence"` **(demo-start 브랜치에서는 이 테스트와 구현을 뺀다)**
  - `test_unknown_chunk_id_is_discarded` → `"no_evidence"`
  - `test_mcq_needs_four_distinct_choices` → `"bad_choices"`
  - `test_mcq_answer_must_be_a_choice` → `"bad_answer"`
  - `test_mcq_answer_must_appear_in_chunk` → `"answer_not_in_evidence"`
  - `test_short_needs_2_to_5_keywords` → `"bad_keywords"`
  - `test_short_keywords_must_appear_in_chunk` → `"keyword_not_in_evidence"`
  - `test_filter_valid_counts_discarded`
  - `test_grade_mcq_ignores_surrounding_space`
  - `test_keywords_60_percent_is_correct` (5개 중 3개 → True, 2개 → False)
  - `test_keywords_ignore_case_and_spaces`
  - `test_make_cloze_blanks_a_long_word`, `test_make_cloze_returns_none_for_short_text`
- [ ] 실패 확인 → `test:` 커밋 → 구현 → 통과 확인 → `feat:` 커밋

객관식 "정답이 근거에 있다"는 정답 문구에서 2글자 이상 단어 중 하나라도 조각 본문에 있으면 통과로 본다(대소문자 무시).

### Task 2: 공부 시간 (`app/timer.py`)

**Interfaces — Produces:**

```python
MAX_CREDIT = 30; IDLE_LIMIT = 90
def credit_seconds(prev: datetime | None, now: datetime) -> int   # 첫 신호·90초 초과면 0, 아니면 min(간격, 30)
def is_studying(last: datetime | None, now: datetime) -> bool      # 90초 이내
def kst_date(dt: datetime) -> date
def week_start(d: date) -> date                                     # 월요일
def format_duration(seconds: int) -> str                            # "1시간 05분"
```

- [ ] 테스트: 첫 신호 0초 / 30초 간격 30초 / 45초 간격 30초 / 91초 간격 0초 / 탭 두 개가 15초 간격으로 번갈아 보내도 2분간 합계 120초 이하 / 시각이 거꾸로면 0초 / UTC 15:30은 한국 날짜로 다음 날 / 일요일의 주 시작은 그 주 월요일

### Task 3: 그룹과 순위 (`app/groups.py`)

```python
def new_invite_code(rng: random.Random) -> str        # 6자, 헷갈리는 0 O 1 I L 제외
@dataclass
class RankRow: rank: int; name: str; seconds: int; studying: bool
def rank(totals: dict[str, int], studying: set[str]) -> list[RankRow]   # 시간 내림차순, 동점은 같은 순위, 이름순
```

- [ ] 테스트: 코드 길이·문자 집합 / 내림차순 / 동점 같은 순위 뒤 순위 건너뜀(1,1,3) / 0초 사용자도 포함 / 빈 그룹은 빈 목록

### Task 4: 자료 분해 (`app/ingest.py`)

```python
def split_text(text: str, max_chars: int = 1200) -> list[str]
def extract_chunks(filename: str, data: bytes) -> list[str]   # .pptx 슬라이드별, .pdf 페이지별, .txt 문단 묶음. 지원하지 않으면 ValueError
```

- [ ] 테스트: 테스트 안에서 python-pptx로 만든 한글 pptx / 빈 슬라이드 제외 / 20자 미만 조각 제외 / txt 긴 본문 분할 / `.hwp`는 ValueError

### Task 5: LLM (`app/llm.py`)

```python
class LLMError(Exception)
class LLMClient:
    def __init__(self, api_key: str | None, base_url: str, model: str, post=httpx.post, timeout: float = 30)
    @property
    def enabled(self) -> bool
    def complete(self, prompt: str) -> str      # 키 없음·HTTP 오류·타임아웃은 LLMError
def extract_json(text: str) -> object           # 코드 블록·앞뒤 설명 제거, 실패 시 ValueError
@dataclass
class GenResult: questions: list[Question]; discarded: int; used_fallback: bool; llm_calls: int
def generate_questions(chunks: dict[int, str], llm: LLMClient, n_mcq: int = 2, n_short: int = 1) -> GenResult
@dataclass
class Grade: correct: bool; feedback: str; by: str   # "llm" | "keywords"
def grade_short(q: Question, answer: str, chunk_text: str, llm: LLMClient) -> Grade
```

- [ ] 테스트(가짜 `post` 주입): Responses 형식 응답 파싱 / JSON 아님 → 1회 재시도 후 성공 / 두 번 다 실패 → 빈칸 문제로 대체하고 `used_fallback=True` / 키 없음 → 호출 0회, 빈칸 문제 / 검증 탈락 문제는 `discarded`에 집계 / 채점 응답의 `correct`가 불리언이 아니면 핵심어 채점 / LLM 오류 시 핵심어 채점 / 코드 블록으로 감싼 JSON 추출

### Task 6: 저장소 (`app/db.py`, `migrations/001_init.sql`)

`connect(path)`, `migrate(conn)`(번호순 SQL 적용, `schema_version` 기록), 그리고 사용자·자료·조각·문제·풀이·신호·그룹·작업·LLM 기록에 대한 함수들. 테이블 세부는 구현자 재량.

- [ ] 테스트: 구조 적용이 두 번 실행돼도 안전 / 신호 저장 시 `credit_seconds` 반영 / 날짜별·주별 합계 / 그룹 중복 가입 방지

### Task 7: 웹 (`app/main.py`, `app/auth.py`, `app/templates/`)

화면: 가입·로그인, 대시보드(타이머·오늘 시간), 자료 목록·업로드, 문제 풀이·결과, 오답 목록, 그룹(만들기·코드로 가입·순위), 운영 현황(LLM 호출·버린 문제 수). API: `POST /api/tick`, `GET /health`.

- [ ] 테스트(TestClient): 가입→로그인→업로드→문제 생성(키 없음, 빈칸 문제)→풀이→오답 목록 / 로그인 없이 접근 시 로그인 화면 / 남의 자료 접근 403 / `/api/tick` 연속 호출 시 시간 누적 / 초대 코드 가입과 순위 / 같은 코드 재입력 시 중복 없음 / `/health` 200

### Task 8: 작업자 (`app/worker.py`)

`run_once(conn, llm) -> int`(대기 작업 처리 수)와 반복 실행 진입점. `INLINE_JOBS=1`이면 업로드 요청 안에서 바로 처리.

### Task 9: 배포 구성

`Dockerfile`, `compose.yml`(web + worker, 볼륨 `arena-data`), `.github/workflows/ci.yml`(test → build·push → self-hosted deploy + `/health` 확인), `.env.example`, `README.md`, `scripts/seed_lectures.py`(강의자료 폴더를 지정해 일괄 등록).

### Task 10: 시연 준비

- [ ] `demo-start` 브랜치: Task 1의 `no_evidence` 테스트와 구현을 뺀 상태
- [ ] 실행 검증과 화면 캡처
- [ ] 튜토리얼 PPT
