# Study Arena

강의자료를 올리면 객관식·주관식 문제를 내 주고, 친구를 초대해 공부 시간을 겨루는 학습 도우미입니다.
「오픈소스SW개발방법및도구」 HW6(TDD + LLM + DevOps + Agent)의 참조 구현입니다.

## 할 수 있는 것

- **자료 업로드**: pptx, pdf, txt를 올리면 슬라이드·페이지 단위로 나눕니다.
- **문제 출제**: LLM(ChatKHU)이 객관식과 주관식 문제를 만듭니다. 근거 슬라이드가 없거나 형식이 틀린 문제는 저장하지 않습니다.
- **풀이와 채점**: 객관식은 즉시, 주관식은 LLM이 채점하고 근거 슬라이드를 보여 줍니다. 틀린 문제는 오답 노트에 모입니다.
- **공부 타이머**: "공부 시작"을 누르면 시간이 쌓입니다. 시간은 서버 시계로만 계산합니다.
- **스터디 그룹**: 초대 코드로 친구를 모아 오늘·이번 주 공부 시간 순위를 봅니다.

LLM 키가 없거나 호출이 실패해도 멈추지 않습니다. 빈칸 문제와 핵심어 채점으로 대체합니다.

## 실행

Docker가 있으면 한 줄입니다.

```bash
docker compose up --build
```

브라우저에서 http://127.0.0.1:8000 을 엽니다. 같은 Wi-Fi의 친구는 `http://<내 컴퓨터 IP>:8000` 으로 접속합니다.

LLM 출제를 쓰려면 `.env.example`을 `.env`로 복사하고 ChatKHU 키를 넣은 뒤 다시 실행합니다.
키는 Info21 → Sitemap → Other → ChatKHU → API Gateway에서 만듭니다.

Docker 없이 실행하려면:

```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

## 테스트

```bash
python -m pytest -q
```

테스트는 실제 LLM이나 네트워크를 부르지 않습니다. `LLMClient`에 가짜 `post`를 넣고, 시계도 인자로 넣습니다.

## 구조

| 파일 | 역할 |
|---|---|
| `app/quiz.py` | LLM이 만든 문제 검증, 채점, 빈칸 문제 생성 (순수 로직) |
| `app/timer.py` | 공부 시간 인정 규칙 (순수 로직) |
| `app/groups.py` | 초대 코드, 순위 계산 (순수 로직) |
| `app/ingest.py` | 파일을 조각으로 나누기 |
| `app/llm.py` | ChatKHU 호출, 재시도, 대체 동작 |
| `app/db.py` | SQLite 저장소 |
| `app/worker.py` | 문제 출제 백그라운드 작업 |
| `app/main.py` | 화면과 API |

## 규칙으로 고정한 것

| 규칙 | 테스트 |
|---|---|
| 근거 인용문은 그 슬라이드에 실제로 있는 문장이어야 한다 | `tests/test_quiz.py` |
| 객관식 보기는 서로 다른 4개, 정답은 그중 하나 | `tests/test_quiz.py` |
| LLM 응답이 JSON이 아니면 한 번 재시도, 그래도 안 되면 빈칸 문제 | `tests/test_llm.py` |
| 주관식 판정이 참/거짓이 아니면 핵심어 채점(60%) | `tests/test_llm.py` |
| 신호 하나는 최대 30초, 90초 끊기면 새 세션 | `tests/test_timer.py` |
| 탭을 두 개 열어도 시간은 한 번만 | `tests/test_timer.py` |
| 브라우저가 보낸 시간은 믿지 않는다 | `tests/test_web.py` |
| 남의 자료와 그룹은 볼 수 없다 | `tests/test_web.py` |

## 배포

`main`에 push하면 GitHub Actions가 다음 순서로 실행합니다.

1. **test**: `pytest`. 실패하면 여기서 멈추고 배포되지 않습니다.
2. **build**: Docker 이미지를 만들어 Docker Hub에 올립니다.
3. **deploy**: Self-hosted Runner가 새 이미지로 교체하고 `/health`를 확인합니다. 실패하면 이전 이미지로 되돌립니다.

저장소 Settings → Secrets and variables → Actions에 세 가지를 등록합니다.

| 이름 | 값 |
|---|---|
| `DOCKERHUB_USERNAME` | Docker Hub 아이디 |
| `DOCKERHUB_TOKEN` | Docker Hub Access Token (Read & Write) |
| `FACTCHAT_API_KEY` | ChatKHU API 키 (없어도 배포는 됩니다) |

계정과 공부 기록은 `arena-data` 볼륨에 있어서 재배포해도 남습니다.
Windows Runner에서는 배포 단계가 `bash`를 쓰므로 Git for Windows가 설치돼 있어야 합니다.

## 알아둘 점

- 강의자료 파일은 저장소에 넣지 않습니다(`materials/`, `data/`는 `.gitignore`).
- 올린 자료의 일부가 문제 출제를 위해 LLM 서버로 전송됩니다. 민감한 자료는 올리지 마세요.
- 수 명이 쓰는 스터디 그룹을 가정한 구성입니다(SQLite 파일 하나).
