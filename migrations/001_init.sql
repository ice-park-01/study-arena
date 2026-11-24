CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    pw_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE materials (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    filename TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',   -- queued | processing | ready | failed
    error TEXT,
    n_chunks INTEGER NOT NULL DEFAULT 0,
    discarded INTEGER NOT NULL DEFAULT 0,
    used_fallback INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE uploads (
    material_id INTEGER PRIMARY KEY REFERENCES materials(id),
    data BLOB NOT NULL
);

CREATE TABLE chunks (
    id INTEGER PRIMARY KEY,
    material_id INTEGER NOT NULL REFERENCES materials(id),
    seq INTEGER NOT NULL,
    text TEXT NOT NULL
);

CREATE TABLE questions (
    id INTEGER PRIMARY KEY,
    material_id INTEGER NOT NULL REFERENCES materials(id),
    chunk_id INTEGER NOT NULL REFERENCES chunks(id),
    kind TEXT NOT NULL,                      -- mcq | short | cloze
    prompt TEXT NOT NULL,
    choices TEXT NOT NULL DEFAULT '[]',      -- JSON
    answer TEXT NOT NULL,
    keywords TEXT NOT NULL DEFAULT '[]'      -- JSON
);

CREATE TABLE attempts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    question_id INTEGER NOT NULL REFERENCES questions(id),
    answer TEXT NOT NULL,
    correct INTEGER NOT NULL,
    feedback TEXT NOT NULL DEFAULT '',
    graded_by TEXT NOT NULL,                 -- exact | llm | keywords
    created_at TEXT NOT NULL
);
CREATE INDEX attempts_by_user ON attempts(user_id, question_id);

-- 공부 시간. 신호 하나가 인정받은 초를 한국 날짜별로 기록한다.
CREATE TABLE ticks (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    at TEXT NOT NULL,
    day TEXT NOT NULL,
    credited INTEGER NOT NULL
);
CREATE INDEX ticks_by_user_day ON ticks(user_id, day);

CREATE TABLE last_seen (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    at TEXT NOT NULL
);

CREATE TABLE groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);

CREATE TABLE memberships (
    group_id INTEGER NOT NULL REFERENCES groups(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (group_id, user_id)
);

CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    material_id INTEGER NOT NULL REFERENCES materials(id),
    status TEXT NOT NULL DEFAULT 'queued'    -- queued | running | done
);

CREATE TABLE llm_log (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    purpose TEXT NOT NULL,                   -- generate | grade
    calls INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    discarded INTEGER NOT NULL DEFAULT 0,
    fallback INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
