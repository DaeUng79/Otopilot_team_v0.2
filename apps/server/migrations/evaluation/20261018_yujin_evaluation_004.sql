-- foreign_keys=OFF
-- 정원 5~9명 (2026-10-18 사용자 결정). evaluation_sessions의
-- CHECK(target_count BETWEEN 7 AND 9)를 BETWEEN 5 AND 9로 바꾼다.
-- SQLite는 CHECK를 수정할 수 없어 표를 다시 만든다. 열·외래키·트리거 이름은 그대로다.
-- 첫 줄의 "-- foreign_keys=OFF" 표식은 app/shared/db.py가 읽어 이 파일만
-- 외래키 검사 없이 적용하고, 적용 뒤 PRAGMA foreign_key_check로 다시 검증한다.
CREATE TABLE evaluation_sessions__v5 (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "project_id" TEXT NOT NULL,
  "round_no" INTEGER NOT NULL CHECK(round_no>0),
  "roster_id" TEXT NOT NULL,
  "approved_criteria_version_id" TEXT NOT NULL,
  "status" TEXT NOT NULL,
  "target_count" INTEGER NOT NULL CHECK(target_count BETWEEN 5 AND 9),
  "minimum_attendees" INTEGER CHECK(minimum_attendees>=3),
  "chair_participant_id" TEXT,
  "aggregation_policy_json" TEXT NOT NULL,
  "policy_approved_by" TEXT,
  "locked_at" TEXT,
  "closed_at" TEXT,
  UNIQUE(project_id,id),
  UNIQUE(project_id,round_no),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT,
  FOREIGN KEY(roster_id) REFERENCES ref_committee_rosters(id) ON DELETE RESTRICT,
  FOREIGN KEY(approved_criteria_version_id) REFERENCES ref_approved_criteria_versions(id) ON DELETE RESTRICT,
  FOREIGN KEY(chair_participant_id) REFERENCES session_participants(id) ON DELETE RESTRICT,
  FOREIGN KEY(policy_approved_by) REFERENCES ref_admin_users(id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,roster_id) REFERENCES ref_committee_rosters(project_id,id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,approved_criteria_version_id) REFERENCES ref_approved_criteria_versions(project_id,id) ON DELETE RESTRICT,
  FOREIGN KEY(id,chair_participant_id) REFERENCES session_participants(session_id,id) ON DELETE RESTRICT
);
INSERT INTO evaluation_sessions__v5 SELECT
  id,created_at,updated_at,version,project_id,round_no,roster_id,approved_criteria_version_id,
  status,target_count,minimum_attendees,chair_participant_id,aggregation_policy_json,
  policy_approved_by,locked_at,closed_at FROM evaluation_sessions;
DROP TABLE evaluation_sessions;
ALTER TABLE evaluation_sessions__v5 RENAME TO evaluation_sessions;
-- 표와 함께 지워진 상태값 트리거를 같은 이름으로 다시 만든다(002 원문과 동일).
CREATE TRIGGER evaluation_sessions_enum_insert BEFORE INSERT ON evaluation_sessions WHEN NEW.status NOT IN ('PREPARING','OPEN','ALL_SUBMITTED','FINALIZED','CANCELLED') BEGIN SELECT RAISE(ABORT,'invalid_status'); END;
CREATE TRIGGER evaluation_sessions_enum_update BEFORE UPDATE ON evaluation_sessions WHEN NEW.status NOT IN ('PREPARING','OPEN','ALL_SUBMITTED','FINALIZED','CANCELLED') BEGIN SELECT RAISE(ABORT,'invalid_status'); END;
