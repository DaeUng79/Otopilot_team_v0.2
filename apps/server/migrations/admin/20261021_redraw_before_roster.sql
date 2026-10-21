-- Preserve immutable draw evidence while allowing an unconfirmed draw to be superseded.
DROP TRIGGER IF EXISTS lex_committee_draws_update;
CREATE TRIGGER lex_committee_draws_update BEFORE UPDATE ON committee_draws
WHEN NOT (
  OLD.status='CONFIRMED' AND NEW.status='SUPERSEDED'
  AND NEW.version=OLD.version+1
  AND NEW.id IS OLD.id AND NEW.created_at IS OLD.created_at
  AND NEW.project_id IS OLD.project_id AND NEW.rule_id IS OLD.rule_id
  AND NEW.revision_no IS OLD.revision_no
  AND NEW.policy_snapshot_json IS OLD.policy_snapshot_json
  AND NEW.eligible_pool_json IS OLD.eligible_pool_json
  AND NEW.pool_sha256 IS OLD.pool_sha256
  AND NEW.algorithm_version IS OLD.algorithm_version
  AND NEW.drawn_by IS OLD.drawn_by
)
BEGIN SELECT RAISE(ABORT,'immutable committee snapshot'); END;
