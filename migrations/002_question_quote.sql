-- 문제마다 LLM이 근거로 인용한 슬라이드 문장을 함께 저장한다.
ALTER TABLE questions ADD COLUMN quote TEXT NOT NULL DEFAULT '';
