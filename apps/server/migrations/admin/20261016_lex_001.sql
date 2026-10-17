-- Lex6won v2 committee tables; shared parent rows must already exist.
CREATE TABLE IF NOT EXISTS evaluator_candidates (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    department_id TEXT NOT NULL REFERENCES departments(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    pool_member INTEGER NOT NULL DEFAULT 0 CHECK(pool_member IN (0,1)),
    organization_name TEXT NOT NULL,
    department_name TEXT,
    name TEXT NOT NULL,
    position TEXT,
    phone_cipher BLOB NOT NULL,
    phone_lookup_hmac TEXT NOT NULL,
    email_cipher BLOB,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    deleted_at TEXT,
    deleted_by TEXT REFERENCES admin_users(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    UNIQUE(department_id,phone_lookup_hmac)
);

CREATE TABLE IF NOT EXISTS specialties (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    aliases_json TEXT NOT NULL CHECK(json_valid(aliases_json)),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);

CREATE TABLE IF NOT EXISTS candidate_specialties (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    candidate_id TEXT NOT NULL REFERENCES evaluator_candidates(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    specialty_id TEXT NOT NULL REFERENCES specialties(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    UNIQUE(candidate_id,specialty_id)
);

CREATE TABLE IF NOT EXISTS candidate_imports (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    department_id TEXT NOT NULL REFERENCES departments(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    project_id TEXT REFERENCES projects(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    scope TEXT NOT NULL CHECK(scope IN ('DEPARTMENT_POOL','PROJECT')),
    source_sha256 TEXT NOT NULL,
    column_mapping_json TEXT NOT NULL CHECK(json_valid(column_mapping_json)),
    preview_cipher BLOB NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PREVIEW','COMMITTED','EXPIRED','FAILED')),
    expires_at TEXT NOT NULL,
    committed_at TEXT,
    created_by TEXT NOT NULL REFERENCES admin_users(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CHECK((scope='PROJECT' AND project_id IS NOT NULL) OR (scope='DEPARTMENT_POOL' AND project_id IS NULL))
);

CREATE TABLE IF NOT EXISTS committee_rules (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    project_id TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    selection_mode TEXT NOT NULL CHECK(selection_mode IN ('POOL_RANDOM','DIRECT')),
    target_count INTEGER NOT NULL CHECK(target_count BETWEEN 7 AND 9),
    reserve_count INTEGER NOT NULL CHECK(reserve_count >= 0),
    policy_version INTEGER NOT NULL CHECK(policy_version > 0),
    approved_by TEXT REFERENCES admin_users(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    approved_at TEXT,
    UNIQUE(project_id,id)
);

CREATE TABLE IF NOT EXISTS field_quotas (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    committee_rule_id TEXT NOT NULL REFERENCES committee_rules(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    specialty_id TEXT NOT NULL REFERENCES specialties(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    final_count INTEGER NOT NULL CHECK(final_count > 0),
    FOREIGN KEY(project_id,committee_rule_id) REFERENCES committee_rules(project_id,id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    UNIQUE(committee_rule_id,specialty_id)
);

CREATE TABLE IF NOT EXISTS committee_draws (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    rule_id TEXT NOT NULL REFERENCES committee_rules(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    revision_no INTEGER NOT NULL CHECK(revision_no > 0),
    policy_snapshot_json TEXT NOT NULL CHECK(json_valid(policy_snapshot_json)),
    eligible_pool_json TEXT NOT NULL CHECK(json_valid(eligible_pool_json)),
    pool_sha256 TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('CONFIRMED','SUPERSEDED')),
    drawn_by TEXT NOT NULL REFERENCES admin_users(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    FOREIGN KEY(project_id,rule_id) REFERENCES committee_rules(project_id,id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    UNIQUE(project_id,id)
);

CREATE TABLE IF NOT EXISTS draw_members (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    draw_id TEXT NOT NULL REFERENCES committee_draws(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    candidate_id TEXT NOT NULL REFERENCES evaluator_candidates(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    specialty_id TEXT NOT NULL REFERENCES specialties(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    draw_order INTEGER NOT NULL CHECK(draw_order > 0),
    FOREIGN KEY(project_id,draw_id) REFERENCES committee_draws(project_id,id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    UNIQUE(draw_id,candidate_id),
    UNIQUE(draw_id,draw_order),
    UNIQUE(project_id,id)
);

CREATE TABLE IF NOT EXISTS project_nominees (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    candidate_id TEXT NOT NULL REFERENCES evaluator_candidates(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    draw_member_id TEXT REFERENCES draw_members(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    source TEXT NOT NULL CHECK(source IN ('POOL_DRAW','DIRECT')),
    contact_status TEXT NOT NULL CHECK(contact_status IN ('NOT_CONTACTED','AVAILABLE','UNAVAILABLE','CALLBACK')),
    contact_note TEXT,
    contacted_at TEXT,
    contacted_by TEXT REFERENCES admin_users(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    exclusion_reason TEXT,
    FOREIGN KEY(project_id,draw_member_id) REFERENCES draw_members(project_id,id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    UNIQUE(project_id,candidate_id),
    UNIQUE(project_id,id),
    CHECK((source='POOL_DRAW' AND draw_member_id IS NOT NULL) OR (source='DIRECT' AND draw_member_id IS NULL))
);

CREATE TABLE IF NOT EXISTS committee_rosters (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    revision_no INTEGER NOT NULL CHECK(revision_no > 0),
    status TEXT NOT NULL CHECK(status IN ('CONFIRMED','SUPERSEDED')),
    roster_sha256 TEXT NOT NULL,
    confirmed_by TEXT NOT NULL REFERENCES admin_users(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    confirmed_at TEXT NOT NULL,
    UNIQUE(project_id,id),
    UNIQUE(project_id,revision_no)
);

CREATE TABLE IF NOT EXISTS committee_assignments (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    roster_id TEXT NOT NULL REFERENCES committee_rosters(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    nominee_id TEXT NOT NULL REFERENCES project_nominees(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    member_kind TEXT NOT NULL CHECK(member_kind IN ('PRIMARY','RESERVE')),
    reserve_order INTEGER CHECK(reserve_order > 0),
    name_snapshot TEXT NOT NULL,
    organization_snapshot TEXT NOT NULL,
    login_lookup_hmac TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('INVITED','REVOKED')),
    auth_key_version INTEGER NOT NULL CHECK(auth_key_version > 0),
    FOREIGN KEY(project_id,roster_id) REFERENCES committee_rosters(project_id,id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    FOREIGN KEY(project_id,nominee_id) REFERENCES project_nominees(project_id,id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    UNIQUE(roster_id,nominee_id),
    CHECK((member_kind='PRIMARY' AND reserve_order IS NULL) OR (member_kind='RESERVE' AND reserve_order > 0))
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    actor_type TEXT NOT NULL,
    actor_id TEXT,
    project_id TEXT,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    detail_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_records (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    actor_scope TEXT NOT NULL,
    operation TEXT NOT NULL,
    request_key TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    response_json TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    UNIQUE(actor_scope,operation,request_key)
);

CREATE TABLE IF NOT EXISTS sync_outbox (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    event_id TEXT NOT NULL UNIQUE,
    contract_name TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    aggregate_id TEXT NOT NULL,
    aggregate_version INTEGER NOT NULL,
    destination TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PENDING','SENT','FAILED')),
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error_code TEXT
);

CREATE TABLE IF NOT EXISTS sync_inbox (
    event_id TEXT NOT NULL PRIMARY KEY,
    source TEXT NOT NULL,
    contract_name TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    aggregate_id TEXT NOT NULL,
    aggregate_version INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    applied_at TEXT,
    error_code TEXT
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_name TEXT NOT NULL PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS lex_active_phone ON evaluator_candidates(department_id,phone_lookup_hmac) WHERE active=1 AND deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS lex_committed_import ON candidate_imports(department_id,scope,coalesce(project_id,''),source_sha256) WHERE status='COMMITTED';
CREATE UNIQUE INDEX IF NOT EXISTS lex_active_draw ON committee_draws(project_id) WHERE status='CONFIRMED';
CREATE UNIQUE INDEX IF NOT EXISTS lex_active_roster ON committee_rosters(project_id) WHERE status='CONFIRMED';
CREATE UNIQUE INDEX IF NOT EXISTS lex_roster_login ON committee_assignments(roster_id,login_lookup_hmac);
CREATE UNIQUE INDEX IF NOT EXISTS lex_reserve_order ON committee_assignments(roster_id,reserve_order) WHERE member_kind='RESERVE';
CREATE INDEX IF NOT EXISTS lex_candidate_department ON evaluator_candidates(department_id,active);
CREATE INDEX IF NOT EXISTS lex_nominee_project ON project_nominees(project_id,contact_status);
CREATE INDEX IF NOT EXISTS lex_pending_outbox ON sync_outbox(destination,status,created_at);
CREATE TRIGGER IF NOT EXISTS lex_nominee_department BEFORE INSERT ON project_nominees
WHEN NOT EXISTS(SELECT 1 FROM evaluator_candidates c JOIN projects p ON p.department_id=c.department_id WHERE c.id=NEW.candidate_id AND p.id=NEW.project_id)
BEGIN SELECT RAISE(ABORT,'nominee department mismatch'); END;
CREATE TRIGGER IF NOT EXISTS lex_nominee_draw_candidate BEFORE INSERT ON project_nominees
WHEN NEW.draw_member_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM draw_members d WHERE d.id=NEW.draw_member_id AND d.project_id=NEW.project_id AND d.candidate_id=NEW.candidate_id)
BEGIN SELECT RAISE(ABORT,'nominee draw mismatch'); END;
CREATE TRIGGER IF NOT EXISTS lex_committee_draws_update BEFORE UPDATE ON committee_draws BEGIN SELECT RAISE(ABORT,'immutable committee snapshot'); END;
CREATE TRIGGER IF NOT EXISTS lex_committee_draws_delete BEFORE DELETE ON committee_draws BEGIN SELECT RAISE(ABORT,'immutable committee snapshot'); END;
CREATE TRIGGER IF NOT EXISTS lex_draw_members_update BEFORE UPDATE ON draw_members BEGIN SELECT RAISE(ABORT,'immutable committee snapshot'); END;
CREATE TRIGGER IF NOT EXISTS lex_draw_members_delete BEFORE DELETE ON draw_members BEGIN SELECT RAISE(ABORT,'immutable committee snapshot'); END;
CREATE TRIGGER IF NOT EXISTS lex_committee_rosters_update BEFORE UPDATE ON committee_rosters BEGIN SELECT RAISE(ABORT,'immutable committee snapshot'); END;
CREATE TRIGGER IF NOT EXISTS lex_committee_rosters_delete BEFORE DELETE ON committee_rosters BEGIN SELECT RAISE(ABORT,'immutable committee snapshot'); END;
CREATE TRIGGER IF NOT EXISTS lex_committee_assignments_update BEFORE UPDATE ON committee_assignments BEGIN SELECT RAISE(ABORT,'immutable committee snapshot'); END;
CREATE TRIGGER IF NOT EXISTS lex_committee_assignments_delete BEFORE DELETE ON committee_assignments BEGIN SELECT RAISE(ABORT,'immutable committee snapshot'); END;
