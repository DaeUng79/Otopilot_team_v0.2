-- Defense in depth for frozen evaluation records.

CREATE TRIGGER signatures_immutable_update BEFORE UPDATE ON signatures BEGIN SELECT RAISE(ABORT,'immutable_record'); END;

CREATE TRIGGER signatures_immutable_delete BEFORE DELETE ON signatures BEGIN SELECT RAISE(ABORT,'immutable_record'); END;

CREATE TRIGGER evaluation_submissions_immutable_update BEFORE UPDATE ON evaluation_submissions BEGIN SELECT RAISE(ABORT,'immutable_record'); END;

CREATE TRIGGER evaluation_submissions_immutable_delete BEFORE DELETE ON evaluation_submissions BEGIN SELECT RAISE(ABORT,'immutable_record'); END;

CREATE TRIGGER result_runs_immutable_update BEFORE UPDATE ON result_runs BEGIN SELECT RAISE(ABORT,'immutable_record'); END;

CREATE TRIGGER result_runs_immutable_delete BEFORE DELETE ON result_runs BEGIN SELECT RAISE(ABORT,'immutable_record'); END;

CREATE TRIGGER result_inputs_immutable_update BEFORE UPDATE ON result_inputs BEGIN SELECT RAISE(ABORT,'immutable_record'); END;

CREATE TRIGGER result_inputs_immutable_delete BEFORE DELETE ON result_inputs BEGIN SELECT RAISE(ABORT,'immutable_record'); END;

CREATE TRIGGER result_items_immutable_update BEFORE UPDATE ON result_items BEGIN SELECT RAISE(ABORT,'immutable_record'); END;

CREATE TRIGGER result_items_immutable_delete BEFORE DELETE ON result_items BEGIN SELECT RAISE(ABORT,'immutable_record'); END;

CREATE TRIGGER chair_confirmations_immutable_update BEFORE UPDATE ON chair_confirmations BEGIN SELECT RAISE(ABORT,'immutable_record'); END;

CREATE TRIGGER chair_confirmations_immutable_delete BEFORE DELETE ON chair_confirmations BEGIN SELECT RAISE(ABORT,'immutable_record'); END;

CREATE TRIGGER session_participants_frozen_insert BEFORE INSERT ON session_participants WHEN (SELECT status FROM evaluation_sessions WHERE id=NEW.session_id)<>'PREPARING' BEGIN SELECT RAISE(ABORT,'session_frozen'); END;

CREATE TRIGGER session_participants_frozen_update BEFORE UPDATE ON session_participants WHEN (SELECT status FROM evaluation_sessions WHERE id=OLD.session_id)<>'PREPARING' BEGIN SELECT RAISE(ABORT,'session_frozen'); END;

CREATE TRIGGER session_participants_frozen_delete BEFORE DELETE ON session_participants WHEN (SELECT status FROM evaluation_sessions WHERE id=OLD.session_id)<>'PREPARING' BEGIN SELECT RAISE(ABORT,'session_frozen'); END;

CREATE TRIGGER session_proposals_frozen_insert BEFORE INSERT ON session_proposals WHEN (SELECT status FROM evaluation_sessions WHERE id=NEW.session_id)<>'PREPARING' BEGIN SELECT RAISE(ABORT,'session_frozen'); END;

CREATE TRIGGER session_proposals_frozen_update BEFORE UPDATE ON session_proposals WHEN (SELECT status FROM evaluation_sessions WHERE id=OLD.session_id)<>'PREPARING' BEGIN SELECT RAISE(ABORT,'session_frozen'); END;

CREATE TRIGGER session_proposals_frozen_delete BEFORE DELETE ON session_proposals WHEN (SELECT status FROM evaluation_sessions WHERE id=OLD.session_id)<>'PREPARING' BEGIN SELECT RAISE(ABORT,'session_frozen'); END;

CREATE TRIGGER score_sheets_lock_update BEFORE UPDATE ON score_sheets WHEN OLD.status='SUBMITTED' BEGIN SELECT RAISE(ABORT,'submitted_sheet'); END;

CREATE TRIGGER score_sheets_lock_delete BEFORE DELETE ON score_sheets WHEN OLD.status='SUBMITTED' BEGIN SELECT RAISE(ABORT,'submitted_sheet'); END;

CREATE TRIGGER score_entries_lock_insert BEFORE INSERT ON score_entries WHEN (SELECT status FROM score_sheets WHERE id=NEW.sheet_id)='SUBMITTED' BEGIN SELECT RAISE(ABORT,'submitted_entries'); END;

CREATE TRIGGER score_entries_lock_update BEFORE UPDATE ON score_entries WHEN (SELECT status FROM score_sheets WHERE id=OLD.sheet_id)='SUBMITTED' BEGIN SELECT RAISE(ABORT,'submitted_entries'); END;

CREATE TRIGGER score_entries_lock_delete BEFORE DELETE ON score_entries WHEN (SELECT status FROM score_sheets WHERE id=OLD.sheet_id)='SUBMITTED' BEGIN SELECT RAISE(ABORT,'submitted_entries'); END;

CREATE TRIGGER score_entry_valid BEFORE UPDATE OF score,max_score_snapshot,criterion_id ON score_entries WHEN NEW.score IS NOT NULL AND (NEW.score%(SELECT score_step FROM ref_approved_criteria_items WHERE id=NEW.criterion_id)<>0 OR NEW.max_score_snapshot<>(SELECT max_score FROM ref_approved_criteria_items WHERE id=NEW.criterion_id)) BEGIN SELECT RAISE(ABORT,'invalid_score'); END;

CREATE TRIGGER ref_approved_criteria_versions_snapshot_frozen BEFORE UPDATE ON ref_approved_criteria_versions WHEN OLD.snapshot_sha256<>NEW.snapshot_sha256 AND EXISTS(SELECT 1 FROM evaluation_sessions WHERE approved_criteria_version_id=OLD.id) BEGIN SELECT RAISE(ABORT,'frozen_snapshot_requires_new_id'); END;

CREATE TRIGGER ref_approved_criteria_items_snapshot_frozen BEFORE UPDATE ON ref_approved_criteria_items WHEN OLD.snapshot_sha256<>NEW.snapshot_sha256 AND EXISTS(SELECT 1 FROM evaluation_sessions WHERE approved_criteria_version_id=OLD.approved_criteria_version_id) BEGIN SELECT RAISE(ABORT,'frozen_snapshot_requires_new_id'); END;

CREATE TRIGGER ref_proposal_uploads_snapshot_frozen BEFORE UPDATE ON ref_proposal_uploads WHEN OLD.snapshot_sha256<>NEW.snapshot_sha256 AND EXISTS(SELECT 1 FROM session_proposals WHERE proposal_upload_id=OLD.id) BEGIN SELECT RAISE(ABORT,'frozen_snapshot_requires_new_id'); END;

CREATE TRIGGER evaluation_sessions_enum_insert BEFORE INSERT ON evaluation_sessions WHEN NEW.status NOT IN ('PREPARING','OPEN','ALL_SUBMITTED','FINALIZED','CANCELLED') BEGIN SELECT RAISE(ABORT,'invalid_status'); END;

CREATE TRIGGER evaluation_sessions_enum_update BEFORE UPDATE ON evaluation_sessions WHEN NEW.status NOT IN ('PREPARING','OPEN','ALL_SUBMITTED','FINALIZED','CANCELLED') BEGIN SELECT RAISE(ABORT,'invalid_status'); END;

CREATE TRIGGER attendance_records_enum_insert BEFORE INSERT ON attendance_records WHEN NEW.status NOT IN ('CONFIRMED','DECLINED') BEGIN SELECT RAISE(ABORT,'invalid_status'); END;

CREATE TRIGGER attendance_records_enum_update BEFORE UPDATE ON attendance_records WHEN NEW.status NOT IN ('CONFIRMED','DECLINED') BEGIN SELECT RAISE(ABORT,'invalid_status'); END;

CREATE TRIGGER score_sheets_enum_insert BEFORE INSERT ON score_sheets WHEN NEW.status NOT IN ('DRAFT','SUBMITTED') BEGIN SELECT RAISE(ABORT,'invalid_status'); END;

CREATE TRIGGER score_sheets_enum_update BEFORE UPDATE ON score_sheets WHEN NEW.status NOT IN ('DRAFT','SUBMITTED') BEGIN SELECT RAISE(ABORT,'invalid_status'); END;

CREATE TRIGGER signatures_enum_insert BEFORE INSERT ON signatures WHEN NEW.purpose NOT IN ('EVALUATION','CHAIR_RESULT') BEGIN SELECT RAISE(ABORT,'invalid_status'); END;

CREATE TRIGGER signatures_enum_update BEFORE UPDATE ON signatures WHEN NEW.purpose NOT IN ('EVALUATION','CHAIR_RESULT') BEGIN SELECT RAISE(ABORT,'invalid_status'); END;

CREATE TRIGGER result_inputs_enum_insert BEFORE INSERT ON result_inputs WHEN NEW.exclusion NOT IN ('NONE','LOWEST','HIGHEST') BEGIN SELECT RAISE(ABORT,'invalid_status'); END;

CREATE TRIGGER result_inputs_enum_update BEFORE UPDATE ON result_inputs WHEN NEW.exclusion NOT IN ('NONE','LOWEST','HIGHEST') BEGIN SELECT RAISE(ABORT,'invalid_status'); END;

CREATE INDEX auth_sessions_lookup ON auth_sessions(token_hash);

CREATE INDEX score_sheets_lookup ON score_sheets(session_id,participant_id);

CREATE INDEX ref_committee_assignments_lookup ON ref_committee_assignments(project_id,login_lookup_hmac);

CREATE INDEX sync_outbox_lookup ON sync_outbox(status,created_at);
