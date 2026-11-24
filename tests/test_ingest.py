import io

import pytest
from pptx import Presentation
from pptx.util import Inches

from app.ingest import extract_chunks, split_text


def make_pptx(slides: list[list[str]]) -> bytes:
    prs = Presentation()
    blank = prs.slide_layouts[6]
    for lines in slides:
        slide = prs.slides.add_slide(blank)
        for i, line in enumerate(lines):
            box = slide.shapes.add_textbox(Inches(1), Inches(1 + i), Inches(8), Inches(1))
            box.text_frame.text = line
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def test_pptx_makes_one_chunk_per_slide_with_korean_text():
    data = make_pptx(
        [
            ["TDD란 무엇인가", "테스트를 먼저 작성하고 그 테스트를 통과하는 코드를 작성한다."],
            ["Docker", "애플리케이션을 실행에 필요한 모든 것과 함께 이미지로 묶는다."],
        ]
    )
    chunks = extract_chunks("오픈소스 (Lecture8) 테스트.pptx", data)
    assert len(chunks) == 2
    assert "테스트를 먼저 작성" in chunks[0]
    assert chunks[0].startswith("[슬라이드 1]")
    assert chunks[1].startswith("[슬라이드 2]")


def test_slides_without_enough_text_are_skipped():
    data = make_pptx([[], ["Q&A"], ["Version control은 문서와 프로그램의 변경 이력을 관리하는 방법이다."]])
    chunks = extract_chunks("lecture.pptx", data)
    assert len(chunks) == 1
    assert chunks[0].startswith("[슬라이드 3]")


def test_txt_is_split_into_paragraph_groups():
    text = "\n\n".join(f"문단 {i}: " + "가나다라마바사 " * 20 for i in range(10))
    chunks = extract_chunks("notes.txt", text.encode("utf-8"))
    assert len(chunks) > 1
    assert all(len(c) <= 1200 for c in chunks)
    assert "문단 0" in chunks[0] and "문단 9" in chunks[-1]


def test_split_text_cuts_one_huge_paragraph():
    chunks = split_text("가" * 3000, max_chars=1200)
    assert [len(c) for c in chunks] == [1200, 1200, 600]


def test_unsupported_file_type_raises():
    with pytest.raises(ValueError, match="지원하지 않는"):
        extract_chunks("과제.hwp", b"...")


def test_broken_pptx_raises_value_error():
    with pytest.raises(ValueError, match="읽을 수 없는"):
        extract_chunks("broken.pptx", b"not a zip file")


def test_line_breaks_inside_a_paragraph_become_spaces():
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1))
    paragraph = box.text_frame.paragraphs[0]
    paragraph.add_run().text = "TDD is a software development"
    paragraph.add_line_break()
    paragraph.add_run().text = "process that relies on short cycles."
    buf = io.BytesIO()
    prs.save(buf)
    [chunk] = extract_chunks("lecture.pptx", buf.getvalue())
    assert "development process" in chunk
