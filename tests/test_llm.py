import json

import httpx
import pytest

from app.llm import LLMClient, LLMError, extract_json, generate_questions, grade_short
from app.quiz import Question

CHUNKS = {
    7: "[슬라이드 7] Test-driven development (TDD)는 테스트를 먼저 작성하는 개발 방법이다. 구호는 red, green, refactor 이다.",
}
GOOD = {
    "questions": [
        {
            "kind": "mcq",
            "prompt": "TDD의 구호는?",
            "choices": ["red, green, refactor", "plan, do, see", "build, ship, run", "read, eval, print"],
            "answer": "red, green, refactor",
            "quote": "구호는 red, green, refactor 이다",
            "chunk_id": 7,
        },
        {
            "kind": "short",
            "prompt": "TDD에서 먼저 작성하는 것은?",
            "answer": "테스트",
            "keywords": ["테스트", "먼저"],
            "quote": "테스트를 먼저 작성하는 개발 방법이다",
            "chunk_id": 7,
        },
    ]
}


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class FakePost:
    """실제 네트워크 대신 미리 정한 응답을 차례로 돌려준다."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, FakeResponse):
            return reply
        return FakeResponse(body={"output": [{"type": "message", "content": [{"type": "output_text", "text": reply}]}]})


def client(*replies, key="test-key"):
    post = FakePost(*replies)
    return LLMClient(api_key=key, base_url="https://llm.test/v1", model="test-model", post=post), post


# --- 호출 ---------------------------------------------------------------


def test_complete_sends_key_and_reads_responses_format():
    llm, post = client("안녕하세요")
    assert llm.complete("hi") == "안녕하세요"
    call = post.calls[0]
    assert call["url"] == "https://llm.test/v1/responses"
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["json"]["model"] == "test-model"


def test_complete_reads_chat_format_too():
    llm, _ = client(FakeResponse(body={"choices": [{"message": {"content": "chat 형식"}}]}))
    assert llm.complete("hi") == "chat 형식"


def test_no_key_means_disabled_and_no_call():
    llm, post = client(key=None)
    assert llm.enabled is False
    with pytest.raises(LLMError):
        llm.complete("hi")
    assert post.calls == []


def test_http_error_and_timeout_become_llm_error():
    llm, _ = client(FakeResponse(status_code=429, body={"error": "rate limit"}))
    with pytest.raises(LLMError):
        llm.complete("hi")
    llm, _ = client(httpx.TimeoutException("slow"))
    with pytest.raises(LLMError):
        llm.complete("hi")


# --- JSON 추출 ----------------------------------------------------------


def test_extract_json_strips_code_fence_and_chatter():
    text = '네, 문제입니다.\n```json\n{"questions": []}\n```\n도움이 되었길 바랍니다.'
    assert extract_json(text) == {"questions": []}


def test_extract_json_rejects_plain_text():
    with pytest.raises(ValueError):
        extract_json("문제를 만들 수 없습니다.")


# --- 문제 생성 ----------------------------------------------------------


def test_generate_keeps_only_valid_questions():
    bad = {"kind": "mcq", "prompt": "보기가 모자란 문제", "choices": ["a", "b"], "answer": "a", "chunk_id": 7}
    llm, post = client(json.dumps({"questions": GOOD["questions"] + [bad]}))
    result = generate_questions(CHUNKS, llm)
    assert [q.kind for q in result.questions] == ["mcq", "short"]
    assert result.discarded == 1
    assert result.used_fallback is False
    assert result.llm_calls == 1
    assert "[슬라이드 7]" in post.calls[0]["json"]["input"]


def test_generate_retries_once_when_reply_is_not_json():
    llm, post = client("죄송합니다, 다시 해볼게요.", json.dumps(GOOD))
    result = generate_questions(CHUNKS, llm)
    assert len(result.questions) == 2
    assert result.llm_calls == 2
    assert len(post.calls) == 2


def test_generate_falls_back_to_cloze_after_two_bad_replies():
    llm, post = client("JSON 아님", "여전히 JSON 아님")
    result = generate_questions(CHUNKS, llm)
    assert len(post.calls) == 2
    assert result.used_fallback is True
    assert [q.kind for q in result.questions] == ["cloze"]


def test_generate_without_key_uses_cloze_and_never_calls():
    llm, post = client(key=None)
    result = generate_questions(CHUNKS, llm)
    assert post.calls == []
    assert result.llm_calls == 0
    assert result.used_fallback is True
    assert result.questions[0].kind == "cloze"


def test_generate_falls_back_when_llm_is_down():
    llm, _ = client(httpx.ConnectError("down"))
    result = generate_questions(CHUNKS, llm)
    assert result.used_fallback is True
    assert result.questions


def test_generate_falls_back_when_every_question_is_discarded():
    bad = {"kind": "mcq", "prompt": "정답이 보기에 없음", "choices": ["a", "b", "c", "d"], "answer": "e", "chunk_id": 7}
    llm, _ = client(json.dumps({"questions": [bad]}))
    result = generate_questions(CHUNKS, llm)
    assert result.discarded == 1
    assert result.used_fallback is True
    assert result.questions[0].kind == "cloze"


# --- 주관식 채점 --------------------------------------------------------

SHORT = Question("short", "TDD에서 먼저 작성하는 것은?", "테스트를 먼저 작성한다", 7, keywords=["테스트", "먼저"])


def test_grade_short_uses_llm_verdict():
    llm, post = client(json.dumps({"correct": True, "feedback": "핵심을 정확히 짚었습니다."}))
    grade = grade_short(SHORT, "테스트 코드부터 쓴다", CHUNKS[7], llm)
    assert (grade.correct, grade.by) == (True, "llm")
    assert grade.feedback == "핵심을 정확히 짚었습니다."
    assert "테스트 코드부터 쓴다" in post.calls[0]["json"]["input"]


def test_grade_short_falls_back_when_verdict_is_not_boolean():
    llm, _ = client(json.dumps({"correct": "아마도", "feedback": "..."}))
    grade = grade_short(SHORT, "테스트를 먼저 쓴다", CHUNKS[7], llm)
    assert (grade.correct, grade.by) == (True, "keywords")


def test_grade_short_falls_back_when_llm_fails():
    llm, _ = client(httpx.TimeoutException("slow"))
    grade = grade_short(SHORT, "구현부터 한다", CHUNKS[7], llm)
    assert (grade.correct, grade.by) == (False, "keywords")
    assert "테스트를 먼저 작성한다" in grade.feedback


def test_blank_answer_is_wrong_without_calling_llm():
    llm, post = client()
    grade = grade_short(SHORT, "   ", CHUNKS[7], llm)
    assert grade.correct is False
    assert post.calls == []


def test_cloze_is_graded_without_llm():
    cloze = Question("cloze", "빈칸: ____ 는 컨테이너 도구다", "Docker", 7)
    llm, post = client()
    assert grade_short(cloze, " docker ", CHUNKS[7], llm).correct is True
    assert grade_short(cloze, "Podman", CHUNKS[7], llm).correct is False
    assert post.calls == []


def test_unexpected_response_shape_becomes_llm_error():
    llm, _ = client(FakeResponse(body=["목록", "형태"]))
    with pytest.raises(LLMError):
        llm.complete("hi")
    llm, _ = client(FakeResponse(body=["목록", "형태"]))
    assert generate_questions(CHUNKS, llm).used_fallback is True
