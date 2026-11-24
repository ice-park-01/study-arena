"""올린 파일을 문제 출제 단위(조각)로 나눈다."""
from __future__ import annotations

import io
import re

MAX_CHARS = 1200
MIN_CHARS = 20
SUPPORTED = (".pptx", ".pdf", ".txt", ".md")


def split_text(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """문단을 max_chars 이하로 묶는다. 한 문단이 너무 길면 잘라 넣는다."""
    chunks: list[str] = []
    current = ""
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        while len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(paragraph[:max_chars])
            paragraph = paragraph[max_chars:]
        if not paragraph:
            continue
        if current and len(current) + 2 + len(paragraph) > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def _shape_lines(shape) -> list[str]:
    lines: list[str] = []
    if getattr(shape, "shapes", None) is not None:  # 그룹 도형
        for child in shape.shapes:
            lines.extend(_shape_lines(child))
    if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
        for paragraph in shape.text_frame.paragraphs:
            # 문단 안의 줄바꿈(\v)은 공백으로 바꾼다. 그냥 이으면 단어가 붙는다.
            line = re.sub(r"\s+", " ", paragraph.text.replace("\v", " ")).strip()
            if line:
                lines.append(line)
    if getattr(shape, "has_table", False) and shape.has_table:
        for row in shape.table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                lines.append(" | ".join(cells))
    return lines


def _from_pptx(data: bytes) -> list[str]:
    from pptx import Presentation

    chunks = []
    for number, slide in enumerate(Presentation(io.BytesIO(data)).slides, start=1):
        lines: list[str] = []
        for shape in slide.shapes:
            lines.extend(_shape_lines(shape))
        # 쪽 번호처럼 숫자만 있는 줄은 버린다.
        body = "\n".join(line for line in lines if not line.isdigit())
        if len(body) >= MIN_CHARS:
            chunks.append(f"[슬라이드 {number}] {body}"[: MAX_CHARS])
    return chunks


def _from_pdf(data: bytes) -> list[str]:
    from pypdf import PdfReader

    chunks = []
    for number, page in enumerate(PdfReader(io.BytesIO(data)).pages, start=1):
        body = (page.extract_text() or "").strip()
        if len(body) >= MIN_CHARS:
            for part in split_text(body, MAX_CHARS - 20):
                chunks.append(f"[페이지 {number}] {part}")
    return chunks


def _from_text(data: bytes) -> list[str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("cp949", errors="replace")
    return [c for c in split_text(text) if len(c) >= MIN_CHARS]


def extract_chunks(filename: str, data: bytes) -> list[str]:
    """파일 종류에 맞게 조각 목록을 만든다. 읽을 수 없으면 ValueError."""
    name = filename.lower()
    if not name.endswith(SUPPORTED):
        raise ValueError("지원하지 않는 파일 형식입니다. pptx, pdf, txt만 올릴 수 있습니다.")
    try:
        if name.endswith(".pptx"):
            return _from_pptx(data)
        if name.endswith(".pdf"):
            return _from_pdf(data)
        return _from_text(data)
    except ValueError:
        raise
    except Exception as exc:  # 손상된 파일 등
        raise ValueError(f"읽을 수 없는 파일입니다: {type(exc).__name__}") from exc
