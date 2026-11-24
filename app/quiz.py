"""문제 검증과 채점. DB와 네트워크를 모르는 순수 로직이다.

LLM이 만든 문제는 그대로 믿지 않는다. 여기의 검증을 통과한 것만 저장한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

WORD = re.compile(r"[0-9A-Za-z가-힣]+")
SENTENCE_END = re.compile(r"(?<=[.?!。])\s+|\n+")
PARTICLES = ("으로", "에서", "에게", "까지", "부터", "을", "를", "은", "는", "이", "가", "의", "에", "로", "와", "과", "도")
KEYWORD_THRESHOLD = 0.6
CLOZE_MIN_TEXT = 30
CLOZE_MIN_WORD = 4
BLANK = "____"


@dataclass(frozen=True)
class Question:
    kind: str  # "mcq" | "short" | "cloze"
    prompt: str
    answer: str
    chunk_id: int
    choices: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


def _squash(text: str) -> str:
    """대소문자와 모든 공백을 무시하고 비교하기 위한 형태."""
    return re.sub(r"\s+", "", str(text)).lower()


def _clean(text: object) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def _evidence(raw: dict, chunks: dict[int, str]) -> str | None:
    chunk_id = raw.get("chunk_id")
    if isinstance(chunk_id, bool) or not isinstance(chunk_id, int):
        return None
    return chunks.get(chunk_id)


def validate_question(raw: object, chunks: dict[int, str]) -> tuple[Question | None, str]:
    """LLM이 준 문제 하나를 검사한다. (문제, "") 또는 (None, 버린 이유)."""
    if not isinstance(raw, dict):
        return None, "bad_shape"
    kind = raw.get("kind")
    if kind not in ("mcq", "short"):
        return None, "bad_kind"
    prompt = _clean(raw.get("prompt", ""))
    if not prompt:
        return None, "bad_prompt"
    evidence = _evidence(raw, chunks)
    if evidence is None:
        return None, "no_evidence"
    answer = _clean(raw.get("answer", ""))
    if kind == "mcq":
        return _validate_mcq(raw, prompt, answer, evidence)
    return _validate_short(raw, prompt, answer, evidence)


def _validate_mcq(raw: dict, prompt: str, answer: str, evidence: str) -> tuple[Question | None, str]:
    choices = raw.get("choices")
    if not isinstance(choices, list):
        return None, "bad_choices"
    choices = [_clean(c) for c in choices]
    if len(choices) != 4 or len({_squash(c) for c in choices}) != 4 or not all(choices):
        return None, "bad_choices"
    if _squash(answer) not in {_squash(c) for c in choices} or not answer:
        return None, "bad_answer"
    words = [w.lower() for w in WORD.findall(answer) if len(w) >= 2]
    if not any(w in evidence.lower() for w in words):
        return None, "answer_not_in_evidence"
    return Question("mcq", prompt, answer, raw["chunk_id"], choices=choices), ""


def _validate_short(raw: dict, prompt: str, answer: str, evidence: str) -> tuple[Question | None, str]:
    if not answer:
        return None, "bad_answer"
    keywords = raw.get("keywords")
    if not isinstance(keywords, list):
        return None, "bad_keywords"
    keywords = [_clean(k) for k in keywords if _clean(k)]
    if not 2 <= len(keywords) <= 5:
        return None, "bad_keywords"
    squashed = _squash(evidence)
    if not all(_squash(k) in squashed for k in keywords):
        return None, "keyword_not_in_evidence"
    return Question("short", prompt, answer, raw["chunk_id"], keywords=keywords), ""


def filter_valid(raws: list, chunks: dict[int, str]) -> tuple[list[Question], int]:
    """통과한 문제 목록과 버린 개수."""
    questions: list[Question] = []
    discarded = 0
    for raw in raws:
        question, _reason = validate_question(raw, chunks)
        if question is None:
            discarded += 1
        else:
            questions.append(question)
    return questions, discarded


def grade_mcq(q: Question, selected: str) -> bool:
    return _squash(selected) == _squash(q.answer)


def grade_by_keywords(answer: str, keywords: list[str], threshold: float = KEYWORD_THRESHOLD) -> bool:
    """학생 답에 핵심어가 threshold 비율 이상 들어 있으면 정답."""
    squashed = _squash(answer)
    if not squashed or not keywords:
        return False
    hits = sum(1 for k in keywords if _squash(k) in squashed)
    return hits >= threshold * len(keywords) - 1e-9


def _strip_particle(word: str) -> str:
    if not re.search(r"[가-힣]$", word):
        return word
    for particle in PARTICLES:
        if word.endswith(particle) and len(word) - len(particle) >= CLOZE_MIN_WORD:
            return word[: -len(particle)]
    return word


def make_cloze(chunk_id: int, text: str) -> Question | None:
    """LLM을 쓸 수 없을 때의 대체 문제. 가장 긴 단어를 가린다."""
    text = text.strip()
    if len(text) < CLOZE_MIN_TEXT:
        return None
    words = [_strip_particle(w) for w in WORD.findall(text)]
    words = [w for w in words if len(w) >= CLOZE_MIN_WORD and not w.isdigit()]
    if not words:
        return None
    answer = max(words, key=len)  # 길이가 같으면 먼저 나온 단어
    sentences = [s.strip() for s in SENTENCE_END.split(text) if answer in s]
    sentence = sentences[0] if sentences else text
    sentence = re.sub(r"\s+", " ", sentence)[:400]
    prompt = "빈칸에 들어갈 말을 쓰세요.\n" + sentence.replace(answer, BLANK)
    return Question("cloze", prompt, answer, chunk_id)


def make_clozes(chunk_id: int, text: str, limit: int) -> list[Question]:
    """한 조각에서 문장마다 빈칸 문제를 하나씩, 최대 limit개 만든다."""
    questions: list[Question] = []
    seen: set[str] = set()
    for sentence in SENTENCE_END.split(text):
        question = make_cloze(chunk_id, sentence)
        if question is None or question.answer.lower() in seen:
            continue
        seen.add(question.answer.lower())
        questions.append(question)
        if len(questions) >= limit:
            break
    return questions
