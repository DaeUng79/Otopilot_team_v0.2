-- foreign_keys=OFF
-- 정원 5~9명 (2026-10-18 사용자 결정). committee_rules(Lex6won 테이블)의
-- CHECK(target_count BETWEEN 7 AND 9)를 BETWEEN 5 AND 9로 바꾼다.
-- SQLite는 CHECK를 수정할 수 없어 표를 다시 만든다. 열·제약 이름은 그대로다.
-- 첫 줄의 "-- foreign_keys=OFF" 표식은 app/shared/db.py가 읽어 이 파일만
-- 외래키 검사 없이 적용하고, 적용 뒤 PRAGMA foreign_key_check로 다시 검증한다.
-- 새 DB에서는 lex_001보다 먼저 실행되므로 먼저 새 정의로 표를 만들어 둔다.
CREATE TABLE IF NOT EXISTS committee_rules (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    project_id TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    selection_mode TEXT NOT NULL CHECK(selection_mode IN ('POOL_RANDOM','DIRECT')),
    target_count INTEGER NOT NULL CHECK(target_count BETWEEN 5 AND 9),
    reserve_count INTEGER NOT NULL CHECK(reserve_count >= 0),
    policy_version INTEGER NOT NULL CHECK(policy_version > 0),
    approved_by TEXT REFERENCES admin_users(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    approved_at TEXT,
    UNIQUE(project_id,id)
);
CREATE TABLE committee_rules__v5 (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    project_id TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    selection_mode TEXT NOT NULL CHECK(selection_mode IN ('POOL_RANDOM','DIRECT')),
    target_count INTEGER NOT NULL CHECK(target_count BETWEEN 5 AND 9),
    reserve_count INTEGER NOT NULL CHECK(reserve_count >= 0),
    policy_version INTEGER NOT NULL CHECK(policy_version > 0),
    approved_by TEXT REFERENCES admin_users(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    approved_at TEXT,
    UNIQUE(project_id,id)
);
INSERT INTO committee_rules__v5 SELECT
    id,created_at,updated_at,version,project_id,selection_mode,target_count,
    reserve_count,policy_version,approved_by,approved_at FROM committee_rules;
DROP TABLE committee_rules;
ALTER TABLE committee_rules__v5 RENAME TO committee_rules;
