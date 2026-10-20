-- 평가항목별 제안서 AI 정리 결과. 위원 개인 정보 없이 회차 전체가 공유한다.
CREATE TABLE IF NOT EXISTS proposal_item_summaries (
  project_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  criterion_id TEXT NOT NULL,
  input_sha256 TEXT NOT NULL,
  processor_version TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('generating','complete')),
  owner_token TEXT,
  lease_until REAL,
  summaries_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(session_id, criterion_id, input_sha256),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT,
  FOREIGN KEY(session_id) REFERENCES evaluation_sessions(id) ON DELETE RESTRICT,
  FOREIGN KEY(criterion_id) REFERENCES ref_approved_criteria_items(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_proposal_item_summaries_project
  ON proposal_item_summaries(project_id, session_id, criterion_id);
