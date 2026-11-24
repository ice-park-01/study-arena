"""ChatKHU(OpenAI 호환 게이트웨이) 호출과, 응답을 믿지 않는 안전장치.

- 응답이 JSON이 아니면 한 번 재시도한다.
- 검증(app.quiz)을 통과한 문제만 남긴다.
- 키가 없거나 호출이 실패하면 규칙 기반 동작으로 대체한다. 서비스는 멈추지 않는다.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import httpx

from app.quiz import Question, filter_valid, grade_by_keywords, make_cloze

DEFAULT_BASE_URL = "https://factchat-cloud.mindlogic.ai/v1/gateway"
DEFAULT_MODEL = "gpt-5.6-luna"


class LLMError(Exception):
    """LLM을 쓸 수 없다(키 없음, 네트워크 오류, 오류 응답)."""


class LLMClient:
    def __init__(self, api_key: str | None, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL,
                 post=httpx.post, timeout: float = 60):
        self.api_key = (api_key or "").strip() or None
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._post = post
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "LLMClient":
        return cls(
            api_key=os.environ.get("FACTCHAT_API_KEY"),
            base_url=os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL),
            model=os.environ.get("LLM_MODEL", DEFAULT_MODEL),
        )

    @property
    def enabled(self) -> bool:
        return self.api_key is not None

    def complete(self, prompt: str) -> str:
        if not self.enabled:
            raise LLMError("API 키가 설정되지 않았습니다.")
        try:
            response = self._post(
                f"{self.base_url}/responses",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"model": self.model, "input": prompt},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM 호출 실패: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise LLMError(f"LLM 오류 응답: HTTP {response.status_code}")
        try:
            text = _read_text(response.json())
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM 응답 형식을 읽을 수 없습니다.") from exc
        if not text:
            raise LLMError("LLM 응답이 비어 있습니다.")
        return text


def _read_text(body: dict) -> str:
    """Responses 형식과 Chat Completions 형식을 모두 읽는다."""
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    if "output" in body:
        parts = []
        for item in body["output"]:
            for content in item.get("content") or []:
                if content.get("type") in ("output_text", "text") and content.get("text"):
                    parts.append(content["text"])
        return "".join(parts)
    return body["choices"][0]["message"]["content"]


def extract_json(text: str) -> object:
    """설명 문장이나 코드 블록 표시가 붙어 있어도 JSON 부분만 뽑는다."""
    candidates = [text.strip()]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ValueError("JSON을 찾을 수 없습니다.")


@dataclass
class GenResult:
    questions: list[Question]
    discarded: int = 0
    used_fallback: bool = False
    llm_calls: int = 0
    llm_failures: int = 0


def _generation_prompt(chunks: dict[int, str], n_mcq: int, n_short: int) -> str:
    material = "\n\n".join(f"<chunk id={cid}>\n{text}\n</chunk>" for cid, text in chunks.items())
    return f"""너는 대학 강의의 시험 문제 출제자다. 아래 강의자료 조각만 근거로 한국어 문제를 만들어라.

규칙:
- 객관식(mcq) {n_mcq}개, 주관식(short) {n_short}개를 만든다.
- 모든 문제에 근거가 된 조각의 id를 chunk_id(정수)로 적는다. 자료에 없는 내용은 출제하지 않는다.
- 객관식은 서로 다른 보기 4개(choices)와, 그중 하나와 글자까지 같은 정답(answer)을 적는다.
- 주관식은 모범답안(answer)과, 답에 꼭 들어가야 하는 핵심어(keywords) 2~5개를 적는다.
  핵심어는 근거 조각에 나오는 표현을 그대로 쓴다.
- 강의 진행 안내, 쪽 번호, 참고 링크처럼 학습 내용이 아닌 것은 묻지 않는다.
- JSON만 출력한다. 설명을 덧붙이지 않는다.

출력 형식:
{{"questions": [
  {{"kind": "mcq", "prompt": "...", "choices": ["...", "...", "...", "..."], "answer": "...", "chunk_id": 1}},
  {{"kind": "short", "prompt": "...", "answer": "...", "keywords": ["...", "..."], "chunk_id": 1}}
]}}

강의자료:
{material}"""


def _cloze_fallback(chunks: dict[int, str], limit: int) -> list[Question]:
    questions = []
    for chunk_id, text in chunks.items():
        question = make_cloze(chunk_id, text)
        if question is not None:
            questions.append(question)
        if len(questions) >= limit:
            break
    return questions


def generate_questions(chunks: dict[int, str], llm: LLMClient, n_mcq: int = 2, n_short: int = 1) -> GenResult:
    """조각들로 문제를 만든다. LLM을 쓸 수 없으면 빈칸 문제로 대체한다."""
    result = GenResult(questions=[])
    raws = None
    if llm.enabled:
        prompt = _generation_prompt(chunks, n_mcq, n_short)
        for _attempt in range(2):  # JSON이 아니면 한 번만 재시도
            result.llm_calls += 1
            try:
                parsed = extract_json(llm.complete(prompt))
            except LLMError:
                result.llm_failures += 1
                break
            except ValueError:
                result.llm_failures += 1
                continue
            raws = parsed.get("questions") if isinstance(parsed, dict) else parsed
            if isinstance(raws, list):
                break
            raws = None
            result.llm_failures += 1
    if raws is not None:
        result.questions, result.discarded = filter_valid(raws, chunks)
    if not result.questions:
        result.used_fallback = True
        result.questions = _cloze_fallback(chunks, limit=n_mcq + n_short)
    return result


@dataclass
class Grade:
    correct: bool
    feedback: str
    by: str  # "llm" | "keywords"


def _keyword_grade(q: Question, answer: str) -> Grade:
    if q.kind == "cloze":
        correct = grade_by_keywords(answer, [q.answer], threshold=1.0)
    else:
        correct = grade_by_keywords(answer, q.keywords or [q.answer])
    verdict = "핵심어가 들어 있습니다." if correct else "핵심어가 부족합니다."
    return Grade(correct, f"{verdict} 모범답안: {q.answer}", "keywords")


def grade_short(q: Question, answer: str, chunk_text: str, llm: LLMClient) -> Grade:
    """주관식 채점. LLM 판정이 참/거짓이 아니면 핵심어 채점으로 대체한다."""
    if not answer.strip():
        return Grade(False, f"답을 입력하지 않았습니다. 모범답안: {q.answer}", "keywords")
    if q.kind != "short" or not llm.enabled:
        return _keyword_grade(q, answer)
    prompt = f"""너는 대학 강의 조교다. 학생의 답이 모범답안과 뜻이 같은지 채점하라.
표현이 달라도 핵심 내용이 맞으면 정답이다. 근거 자료에 없는 내용으로 판단하지 않는다.
JSON만 출력한다: {{"correct": true 또는 false, "feedback": "한국어 한 문장"}}

문제: {q.prompt}
모범답안: {q.answer}
근거 자료: {chunk_text}
학생의 답: {answer}"""
    try:
        parsed = extract_json(llm.complete(prompt))
    except (LLMError, ValueError):
        return _keyword_grade(q, answer)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("correct"), bool):
        return _keyword_grade(q, answer)
    feedback = str(parsed.get("feedback") or "").strip() or f"모범답안: {q.answer}"
    return Grade(parsed["correct"], feedback, "llm")
