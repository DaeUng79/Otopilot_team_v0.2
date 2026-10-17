-- Frozen v2 fields and local foreign keys. Never attach another database.

PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS attendance_records (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "project_id" TEXT NOT NULL,
  "assignment_id" TEXT NOT NULL UNIQUE,
  "status" TEXT NOT NULL,
  "consent_version" TEXT NOT NULL,
  "consented_at" TEXT,
  "confirmed_at" TEXT,
  UNIQUE(project_id,id),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT,
  FOREIGN KEY(assignment_id) REFERENCES ref_committee_assignments(id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,assignment_id) REFERENCES ref_committee_assignments(project_id,id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS evaluation_sessions (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "project_id" TEXT NOT NULL,
  "round_no" INTEGER NOT NULL CHECK(round_no>0),
  "roster_id" TEXT NOT NULL,
  "approved_criteria_version_id" TEXT NOT NULL,
  "status" TEXT NOT NULL,
  "target_count" INTEGER NOT NULL CHECK(target_count BETWEEN 7 AND 9),
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

CREATE TABLE IF NOT EXISTS session_participants (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "project_id" TEXT NOT NULL,
  "session_id" TEXT NOT NULL,
  "assignment_id" TEXT NOT NULL,
  "attendance_id" TEXT NOT NULL,
  "locked_by" TEXT NOT NULL,
  UNIQUE(session_id,assignment_id),
  UNIQUE(session_id,id),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT,
  FOREIGN KEY(session_id) REFERENCES evaluation_sessions(id) ON DELETE RESTRICT,
  FOREIGN KEY(assignment_id) REFERENCES ref_committee_assignments(id) ON DELETE RESTRICT,
  FOREIGN KEY(attendance_id) REFERENCES attendance_records(id) ON DELETE RESTRICT,
  FOREIGN KEY(locked_by) REFERENCES ref_admin_users(id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,session_id) REFERENCES evaluation_sessions(project_id,id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,assignment_id) REFERENCES ref_committee_assignments(project_id,id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,attendance_id) REFERENCES attendance_records(project_id,id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS session_proposals (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "project_id" TEXT NOT NULL,
  "session_id" TEXT NOT NULL,
  "vendor_id" TEXT NOT NULL,
  "proposal_upload_id" TEXT NOT NULL,
  "display_code" TEXT NOT NULL,
  UNIQUE(session_id,display_code),
  UNIQUE(session_id,id),
  UNIQUE(session_id,vendor_id),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT,
  FOREIGN KEY(session_id) REFERENCES evaluation_sessions(id) ON DELETE RESTRICT,
  FOREIGN KEY(vendor_id) REFERENCES ref_project_vendors(id) ON DELETE RESTRICT,
  FOREIGN KEY(proposal_upload_id) REFERENCES ref_proposal_uploads(id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,session_id) REFERENCES evaluation_sessions(project_id,id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,vendor_id) REFERENCES ref_project_vendors(project_id,id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,proposal_upload_id) REFERENCES ref_proposal_uploads(project_id,id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS score_sheets (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "project_id" TEXT NOT NULL,
  "session_id" TEXT NOT NULL,
  "participant_id" TEXT NOT NULL,
  "session_proposal_id" TEXT NOT NULL,
  "approved_criteria_version_id" TEXT NOT NULL,
  "status" TEXT NOT NULL,
  "total_score" INTEGER,
  UNIQUE(project_id,id),
  UNIQUE(session_id,participant_id,session_proposal_id),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT,
  FOREIGN KEY(session_id) REFERENCES evaluation_sessions(id) ON DELETE RESTRICT,
  FOREIGN KEY(participant_id) REFERENCES session_participants(id) ON DELETE RESTRICT,
  FOREIGN KEY(session_proposal_id) REFERENCES session_proposals(id) ON DELETE RESTRICT,
  FOREIGN KEY(approved_criteria_version_id) REFERENCES ref_approved_criteria_versions(id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,session_id) REFERENCES evaluation_sessions(project_id,id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,approved_criteria_version_id) REFERENCES ref_approved_criteria_versions(project_id,id) ON DELETE RESTRICT,
  FOREIGN KEY(session_id,participant_id) REFERENCES session_participants(session_id,id) ON DELETE RESTRICT,
  FOREIGN KEY(session_id,session_proposal_id) REFERENCES session_proposals(session_id,id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS score_entries (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "project_id" TEXT NOT NULL,
  "sheet_id" TEXT NOT NULL,
  "approved_criteria_version_id" TEXT NOT NULL,
  "criterion_id" TEXT NOT NULL,
  "score" INTEGER CHECK(score>=0),
  "max_score_snapshot" INTEGER NOT NULL CHECK(max_score_snapshot>=0),
  "comment" TEXT,
  UNIQUE(sheet_id,criterion_id),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT,
  FOREIGN KEY(sheet_id) REFERENCES score_sheets(id) ON DELETE RESTRICT,
  FOREIGN KEY(approved_criteria_version_id) REFERENCES ref_approved_criteria_versions(id) ON DELETE RESTRICT,
  FOREIGN KEY(criterion_id) REFERENCES ref_approved_criteria_items(id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,sheet_id) REFERENCES score_sheets(project_id,id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,approved_criteria_version_id,criterion_id) REFERENCES ref_approved_criteria_items(project_id,approved_criteria_version_id,id) ON DELETE RESTRICT,
  CHECK(score IS NULL OR score<=max_score_snapshot)
);

CREATE TABLE IF NOT EXISTS signatures (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "project_id" TEXT NOT NULL,
  "session_id" TEXT NOT NULL,
  "signer_participant_id" TEXT NOT NULL,
  "purpose" TEXT NOT NULL,
  "payload_sha256" TEXT NOT NULL,
  "image_blob" BLOB NOT NULL,
  "image_sha256" TEXT NOT NULL,
  "consent_text_version" TEXT NOT NULL,
  "signed_at" TEXT NOT NULL,
  "expires_at" TEXT NOT NULL,
  UNIQUE(project_id,session_id,signer_participant_id,id),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT,
  FOREIGN KEY(session_id) REFERENCES evaluation_sessions(id) ON DELETE RESTRICT,
  FOREIGN KEY(signer_participant_id) REFERENCES session_participants(id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,session_id) REFERENCES evaluation_sessions(project_id,id) ON DELETE RESTRICT,
  FOREIGN KEY(session_id,signer_participant_id) REFERENCES session_participants(session_id,id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS evaluation_submissions (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "project_id" TEXT NOT NULL,
  "session_id" TEXT NOT NULL,
  "participant_id" TEXT NOT NULL,
  "signature_id" TEXT NOT NULL UNIQUE,
  "payload_sha256" TEXT NOT NULL,
  "submitted_at" TEXT NOT NULL,
  UNIQUE(session_id,participant_id),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT,
  FOREIGN KEY(session_id) REFERENCES evaluation_sessions(id) ON DELETE RESTRICT,
  FOREIGN KEY(participant_id) REFERENCES session_participants(id) ON DELETE RESTRICT,
  FOREIGN KEY(signature_id) REFERENCES signatures(id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,session_id) REFERENCES evaluation_sessions(project_id,id) ON DELETE RESTRICT,
  FOREIGN KEY(session_id,participant_id) REFERENCES session_participants(session_id,id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,session_id,participant_id,signature_id) REFERENCES signatures(project_id,session_id,signer_participant_id,id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS result_runs (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "project_id" TEXT NOT NULL,
  "session_id" TEXT NOT NULL,
  "revision_no" INTEGER NOT NULL CHECK(revision_no>0),
  "input_sha256" TEXT NOT NULL,
  "policy_snapshot_json" TEXT NOT NULL,
  "participant_count" INTEGER NOT NULL CHECK(participant_count>=3),
  "calculated_at" TEXT NOT NULL,
  UNIQUE(project_id,id),
  UNIQUE(session_id,id),
  UNIQUE(session_id,input_sha256),
  UNIQUE(session_id,revision_no),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT,
  FOREIGN KEY(session_id) REFERENCES evaluation_sessions(id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,session_id) REFERENCES evaluation_sessions(project_id,id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS result_inputs (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "project_id" TEXT NOT NULL,
  "result_run_id" TEXT NOT NULL,
  "session_proposal_id" TEXT NOT NULL,
  "participant_id" TEXT NOT NULL,
  "submission_id" TEXT NOT NULL,
  "total_score" INTEGER NOT NULL,
  "exclusion" TEXT NOT NULL,
  UNIQUE(result_run_id,session_proposal_id,participant_id),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT,
  FOREIGN KEY(result_run_id) REFERENCES result_runs(id) ON DELETE RESTRICT,
  FOREIGN KEY(session_proposal_id) REFERENCES session_proposals(id) ON DELETE RESTRICT,
  FOREIGN KEY(participant_id) REFERENCES session_participants(id) ON DELETE RESTRICT,
  FOREIGN KEY(submission_id) REFERENCES evaluation_submissions(id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,result_run_id) REFERENCES result_runs(project_id,id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS result_items (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "project_id" TEXT NOT NULL,
  "result_run_id" TEXT NOT NULL,
  "session_proposal_id" TEXT NOT NULL,
  "included_sum" INTEGER NOT NULL,
  "included_count" INTEGER NOT NULL CHECK(included_count>0),
  "average_decimal" TEXT NOT NULL,
  "rank" INTEGER NOT NULL CHECK(rank>0),
  UNIQUE(result_run_id,session_proposal_id),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT,
  FOREIGN KEY(result_run_id) REFERENCES result_runs(id) ON DELETE RESTRICT,
  FOREIGN KEY(session_proposal_id) REFERENCES session_proposals(id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,result_run_id) REFERENCES result_runs(project_id,id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS chair_confirmations (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "project_id" TEXT NOT NULL,
  "session_id" TEXT NOT NULL,
  "result_run_id" TEXT NOT NULL UNIQUE,
  "chair_participant_id" TEXT NOT NULL,
  "signature_id" TEXT NOT NULL UNIQUE,
  "payload_sha256" TEXT NOT NULL,
  "submitted_at" TEXT NOT NULL,
  UNIQUE(session_id),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT,
  FOREIGN KEY(session_id) REFERENCES evaluation_sessions(id) ON DELETE RESTRICT,
  FOREIGN KEY(result_run_id) REFERENCES result_runs(id) ON DELETE RESTRICT,
  FOREIGN KEY(chair_participant_id) REFERENCES session_participants(id) ON DELETE RESTRICT,
  FOREIGN KEY(signature_id) REFERENCES signatures(id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,session_id) REFERENCES evaluation_sessions(project_id,id) ON DELETE RESTRICT,
  FOREIGN KEY(session_id,chair_participant_id) REFERENCES session_participants(session_id,id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,session_id,chair_participant_id,signature_id) REFERENCES signatures(project_id,session_id,signer_participant_id,id) ON DELETE RESTRICT,
  FOREIGN KEY(session_id,result_run_id) REFERENCES result_runs(session_id,id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS auth_sessions (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "principal_id" TEXT NOT NULL,
  "token_hash" TEXT NOT NULL UNIQUE,
  "project_id" TEXT NOT NULL,
  "auth_method" TEXT NOT NULL,
  "expires_at" TEXT NOT NULL,
  "revoked_at" TEXT,
  FOREIGN KEY(principal_id) REFERENCES ref_committee_assignments(id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ref_admin_users (
  "id" TEXT NOT NULL PRIMARY KEY,
  "source_version" INTEGER NOT NULL CHECK(source_version>0),
  "snapshot_sha256" TEXT NOT NULL,
  "synced_at" TEXT NOT NULL,
  "is_deleted" INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1)),
  "department_id" TEXT,
  "role" TEXT NOT NULL,
  "display_name" TEXT NOT NULL,
  "active" INTEGER NOT NULL CHECK(active IN (0,1)),
  "permission_codes_json" TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_projects (
  "id" TEXT NOT NULL PRIMARY KEY,
  "source_version" INTEGER NOT NULL CHECK(source_version>0),
  "snapshot_sha256" TEXT NOT NULL,
  "synced_at" TEXT NOT NULL,
  "is_deleted" INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1)),
  "department_id" TEXT NOT NULL,
  "name" TEXT NOT NULL,
  "status" TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_project_vendors (
  "id" TEXT NOT NULL PRIMARY KEY,
  "source_version" INTEGER NOT NULL CHECK(source_version>0),
  "snapshot_sha256" TEXT NOT NULL,
  "synced_at" TEXT NOT NULL,
  "is_deleted" INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1)),
  "project_id" TEXT NOT NULL,
  "display_code" TEXT NOT NULL,
  "sort_order" INTEGER NOT NULL,
  "active" INTEGER NOT NULL CHECK(active IN (0,1)),
  UNIQUE(project_id,display_code),
  UNIQUE(project_id,id),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ref_committee_rosters (
  "id" TEXT NOT NULL PRIMARY KEY,
  "source_version" INTEGER NOT NULL CHECK(source_version>0),
  "snapshot_sha256" TEXT NOT NULL,
  "synced_at" TEXT NOT NULL,
  "is_deleted" INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1)),
  "project_id" TEXT NOT NULL,
  "revision_no" INTEGER NOT NULL,
  "status" TEXT NOT NULL,
  "roster_sha256" TEXT NOT NULL,
  UNIQUE(project_id,id),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ref_committee_assignments (
  "id" TEXT NOT NULL PRIMARY KEY,
  "source_version" INTEGER NOT NULL CHECK(source_version>0),
  "snapshot_sha256" TEXT NOT NULL,
  "synced_at" TEXT NOT NULL,
  "is_deleted" INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1)),
  "project_id" TEXT NOT NULL,
  "roster_id" TEXT NOT NULL,
  "member_kind" TEXT NOT NULL,
  "reserve_order" INTEGER,
  "name_snapshot" TEXT NOT NULL,
  "organization_snapshot" TEXT NOT NULL,
  "login_lookup_hmac" TEXT NOT NULL,
  "auth_key_version" INTEGER NOT NULL,
  "status" TEXT NOT NULL,
  UNIQUE(project_id,id),
  UNIQUE(project_id,roster_id,login_lookup_hmac),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT,
  FOREIGN KEY(roster_id) REFERENCES ref_committee_rosters(id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,roster_id) REFERENCES ref_committee_rosters(project_id,id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ref_rfp_bindings (
  "id" TEXT NOT NULL PRIMARY KEY,
  "source_version" INTEGER NOT NULL CHECK(source_version>0),
  "snapshot_sha256" TEXT NOT NULL,
  "synced_at" TEXT NOT NULL,
  "is_deleted" INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1)),
  "project_id" TEXT NOT NULL,
  "upload_revision" INTEGER NOT NULL,
  "document_id" TEXT NOT NULL,
  "parse_revision" TEXT NOT NULL,
  UNIQUE(project_id,id),
  UNIQUE(project_id,upload_revision),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ref_approved_criteria_versions (
  "id" TEXT NOT NULL PRIMARY KEY,
  "source_version" INTEGER NOT NULL CHECK(source_version>0),
  "snapshot_sha256" TEXT NOT NULL,
  "synced_at" TEXT NOT NULL,
  "is_deleted" INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1)),
  "project_id" TEXT NOT NULL,
  "rfp_binding_id" TEXT NOT NULL,
  "approval_no" INTEGER NOT NULL,
  "total_max_score" INTEGER NOT NULL,
  "status" TEXT NOT NULL,
  "approved_snapshot_json" TEXT NOT NULL,
  "approved_at" TEXT NOT NULL,
  UNIQUE(project_id,id),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT,
  FOREIGN KEY(rfp_binding_id) REFERENCES ref_rfp_bindings(id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,rfp_binding_id) REFERENCES ref_rfp_bindings(project_id,id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ref_approved_criteria_items (
  "id" TEXT NOT NULL PRIMARY KEY,
  "source_version" INTEGER NOT NULL CHECK(source_version>0),
  "snapshot_sha256" TEXT NOT NULL,
  "synced_at" TEXT NOT NULL,
  "is_deleted" INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1)),
  "project_id" TEXT NOT NULL,
  "approved_criteria_version_id" TEXT NOT NULL,
  "parent_id" TEXT,
  "code" TEXT NOT NULL,
  "title" TEXT NOT NULL,
  "description" TEXT,
  "is_scorable" INTEGER NOT NULL CHECK(is_scorable IN (0,1)),
  "max_score" INTEGER NOT NULL,
  "score_step" INTEGER NOT NULL,
  "sort_order" INTEGER NOT NULL,
  UNIQUE(approved_criteria_version_id,code),
  UNIQUE(project_id,approved_criteria_version_id,id),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT,
  FOREIGN KEY(approved_criteria_version_id) REFERENCES ref_approved_criteria_versions(id) ON DELETE RESTRICT,
  FOREIGN KEY(parent_id) REFERENCES ref_approved_criteria_items(id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,approved_criteria_version_id) REFERENCES ref_approved_criteria_versions(project_id,id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,approved_criteria_version_id,parent_id) REFERENCES ref_approved_criteria_items(project_id,approved_criteria_version_id,id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ref_proposal_uploads (
  "id" TEXT NOT NULL PRIMARY KEY,
  "source_version" INTEGER NOT NULL CHECK(source_version>0),
  "snapshot_sha256" TEXT NOT NULL,
  "synced_at" TEXT NOT NULL,
  "is_deleted" INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1)),
  "project_id" TEXT NOT NULL,
  "vendor_id" TEXT NOT NULL,
  "upload_revision" INTEGER NOT NULL,
  "document_id" TEXT NOT NULL,
  "parse_revision" TEXT NOT NULL,
  "format" TEXT NOT NULL,
  "status" TEXT NOT NULL,
  UNIQUE(project_id,id),
  UNIQUE(project_id,vendor_id,upload_revision),
  FOREIGN KEY(project_id) REFERENCES ref_projects(id) ON DELETE RESTRICT,
  FOREIGN KEY(vendor_id) REFERENCES ref_project_vendors(id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id,vendor_id) REFERENCES ref_project_vendors(project_id,id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS audit_events (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "actor_type" TEXT NOT NULL,
  "actor_id" TEXT,
  "project_id" TEXT,
  "action" TEXT NOT NULL,
  "entity_type" TEXT NOT NULL,
  "entity_id" TEXT NOT NULL,
  "detail_json" TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_records (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "actor_scope" TEXT NOT NULL,
  "operation" TEXT NOT NULL,
  "request_key" TEXT NOT NULL,
  "request_sha256" TEXT NOT NULL,
  "response_json" TEXT NOT NULL,
  "expires_at" TEXT NOT NULL,
  UNIQUE(actor_scope,operation,request_key)
);

CREATE TABLE IF NOT EXISTS sync_outbox (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "event_id" TEXT NOT NULL UNIQUE,
  "contract_name" TEXT NOT NULL,
  "schema_version" INTEGER NOT NULL,
  "aggregate_id" TEXT NOT NULL,
  "aggregate_version" INTEGER NOT NULL,
  "destination" TEXT NOT NULL,
  "payload_json" TEXT NOT NULL,
  "payload_sha256" TEXT NOT NULL,
  "status" TEXT NOT NULL,
  "retry_count" INTEGER NOT NULL DEFAULT 0,
  "last_error_code" TEXT
);

CREATE TABLE IF NOT EXISTS sync_inbox (
  "event_id" TEXT NOT NULL PRIMARY KEY,
  "source" TEXT NOT NULL,
  "contract_name" TEXT NOT NULL,
  "schema_version" INTEGER NOT NULL,
  "aggregate_id" TEXT NOT NULL,
  "aggregate_version" INTEGER NOT NULL,
  "payload_json" TEXT NOT NULL,
  "payload_sha256" TEXT NOT NULL,
  "status" TEXT NOT NULL,
  "applied_at" TEXT,
  "error_code" TEXT
);

CREATE TABLE IF NOT EXISTS schema_migrations (
  "migration_name" TEXT NOT NULL PRIMARY KEY,
  "checksum" TEXT NOT NULL,
  "applied_at" TEXT NOT NULL
);
