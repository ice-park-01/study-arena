from app.quiz import (
    Question,
    filter_valid,
    grade_by_keywords,
    grade_mcq,
    make_cloze,
    validate_question,
)

CHUNKS = {
    1: "Test-driven development (TDD)는 테스트를 먼저 작성하고 그 테스트를 통과하는 코드를 작성하는 개발 방법이다. "
    "TDD의 구호는 red, green, refactor 이다.",
    2: "Docker는 애플리케이션을 실행에 필요한 모든 것과 함께 컨테이너 이미지로 묶는다.",
}


def mcq(**over):
    raw = {
        "kind": "mcq",
        "prompt": "TDD의 구호로 알맞은 것은?",
        "choices": ["red, green, refactor", "plan, do, see", "build, ship, run", "read, eval, print"],
        "answer": "red, green, refactor",
        "chunk_id": 1,
    }
    raw.update(over)
    return raw


def short(**over):
    raw = {
        "kind": "short",
        "prompt": "TDD에서 코드를 작성하기 전에 먼저 하는 일은?",
        "answer": "테스트를 먼저 작성한다",
        "keywords": ["테스트", "먼저"],
        "chunk_id": 1,
    }
    raw.update(over)
    return raw


# --- 객관식 검증 ---------------------------------------------------------


def test_mcq_valid_passes():
    q, reason = validate_question(mcq(), CHUNKS)
    assert reason == ""
    assert isinstance(q, Question)
    assert q.kind == "mcq"
    assert q.chunk_id == 1
    assert len(q.choices) == 4


def test_missing_chunk_id_is_discarded():
    raw = mcq()
    del raw["chunk_id"]
    q, reason = validate_question(raw, CHUNKS)
    assert q is None
    assert reason == "no_evidence"


def test_unknown_chunk_id_is_discarded():
    q, reason = validate_question(mcq(chunk_id=99), CHUNKS)
    assert q is None
    assert reason == "no_evidence"


def test_mcq_needs_four_distinct_choices():
    three = mcq(choices=["red, green, refactor", "a", "b"])
    assert validate_question(three, CHUNKS) == (None, "bad_choices")
    dup = mcq(choices=["red, green, refactor", "same", "same ", "other"])
    assert validate_question(dup, CHUNKS) == (None, "bad_choices")


def test_mcq_answer_must_be_a_choice():
    q, reason = validate_question(mcq(answer="green, red, refactor"), CHUNKS)
    assert (q, reason) == (None, "bad_answer")


def test_mcq_answer_must_appear_in_chunk():
    raw = mcq(
        choices=["waterfall", "plan, do, see", "build, ship, run", "read, eval, print"],
        answer="waterfall",
    )
    assert validate_question(raw, CHUNKS) == (None, "answer_not_in_evidence")


def test_empty_prompt_is_discarded():
    assert validate_question(mcq(prompt="  "), CHUNKS) == (None, "bad_prompt")


def test_unknown_kind_is_discarded():
    assert validate_question(mcq(kind="essay"), CHUNKS) == (None, "bad_kind")


def test_non_dict_is_discarded():
    assert validate_question("문제입니다", CHUNKS) == (None, "bad_shape")


# --- 주관식 검증 ---------------------------------------------------------


def test_short_valid_passes():
    q, reason = validate_question(short(), CHUNKS)
    assert reason == ""
    assert q.kind == "short"
    assert q.keywords == ["테스트", "먼저"]
    assert q.choices == []


def test_short_needs_2_to_5_keywords():
    assert validate_question(short(keywords=["테스트"]), CHUNKS) == (None, "bad_keywords")
    six = ["테스트", "먼저", "작성", "코드", "개발", "방법"]
    assert validate_question(short(keywords=six), CHUNKS) == (None, "bad_keywords")


def test_short_keywords_must_appear_in_chunk():
    raw = short(keywords=["테스트", "블록체인"])
    assert validate_question(raw, CHUNKS) == (None, "keyword_not_in_evidence")


def test_filter_valid_counts_discarded():
    raws = [mcq(), mcq(answer="보기에 없는 답"), short(), short(keywords=[])]
    questions, discarded = filter_valid(raws, CHUNKS)
    assert [q.kind for q in questions] == ["mcq", "short"]
    assert discarded == 2


# --- 채점 ---------------------------------------------------------------


def test_grade_mcq_ignores_surrounding_space():
    q, _ = validate_question(mcq(), CHUNKS)
    assert grade_mcq(q, "  red, green, refactor ") is True
    assert grade_mcq(q, "plan, do, see") is False


def test_keywords_60_percent_is_correct():
    keywords = ["테스트", "먼저", "작성", "통과", "코드"]
    assert grade_by_keywords("테스트를 먼저 작성한다", keywords) is True  # 3/5
    assert grade_by_keywords("테스트를 나중에 작성한다", keywords) is False  # 2/5


def test_keywords_ignore_case_and_spaces():
    assert grade_by_keywords("RED  Green refactor", ["red", "green", "re factor"]) is True


def test_keywords_empty_answer_is_wrong():
    assert grade_by_keywords("   ", ["테스트", "먼저"]) is False


# --- 빈칸 문제 (LLM 대체) -------------------------------------------------


def test_make_cloze_blanks_a_long_word():
    q = make_cloze(2, CHUNKS[2])
    assert q is not None
    assert q.kind == "cloze"
    assert q.chunk_id == 2
    assert "____" in q.prompt
    assert q.answer not in q.prompt
    assert q.answer in CHUNKS[2]
    assert len(q.answer) >= 4


def test_make_cloze_returns_none_for_short_text():
    assert make_cloze(1, "짧은 글") is None


def test_make_cloze_is_deterministic():
    assert make_cloze(2, CHUNKS[2]) == make_cloze(2, CHUNKS[2])


# --- 리뷰에서 나온 결함 ---------------------------------------------------


def test_null_fields_are_not_saved_as_the_word_none():
    assert validate_question(short(prompt=None), CHUNKS) == (None, "bad_prompt")
    assert validate_question(short(answer=None), CHUNKS) == (None, "bad_answer")
    assert validate_question(mcq(choices=["red, green, refactor", None, "b", "c"]), CHUNKS) == (None, "bad_choices")
    assert validate_question(short(keywords=["테스트", None, 3]), CHUNKS) == (None, "bad_keywords")


def test_mcq_answer_needs_most_of_its_words_in_the_chunk():
    # "TDD" 한 단어만 근거에 있고 나머지는 지어낸 정답
    raw = mcq(
        choices=["TDD는 배포 이후에 블록체인으로 검증한다", "plan, do, see", "build, ship, run", "read, eval, print"],
        answer="TDD는 배포 이후에 블록체인으로 검증한다",
    )
    assert validate_question(raw, CHUNKS) == (None, "answer_not_in_evidence")


def test_single_character_answer_can_be_valid():
    chunks = {1: "TDD cycle has 5 steps: add a test, run, write code, run tests, refactor."}
    raw = mcq(prompt="TDD cycle의 단계 수는?", choices=["3", "4", "5", "6"], answer="5")
    q, reason = validate_question(raw, chunks)
    assert reason == "" and q.answer == "5"


def test_one_letter_keywords_are_rejected():
    assert validate_question(short(keywords=["이", "다"]), CHUNKS) == (None, "bad_keywords")


def test_cloze_never_blanks_the_slide_label():
    q = make_cloze(3, "[슬라이드 3] 운영체제는 컴퓨터의 자원을 관리한다. 그 중심에는 커널이 있다.")
    assert q is not None
    assert q.answer != "슬라이드"
    assert "[슬라이드 3]" not in q.prompt


def test_cloze_prompt_always_contains_the_blank():
    text = "가나다 " * 150 + "Supercalifragilistic 라는 단어가 문장 끝에 있다"
    q = make_cloze(1, text)
    assert q is None or "____" in q.prompt
