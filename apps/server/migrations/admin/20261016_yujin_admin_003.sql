CREATE TABLE admin_password_requirements (
    admin_id TEXT PRIMARY KEY REFERENCES admin_users(id) ON DELETE RESTRICT,
    must_change INTEGER NOT NULL DEFAULT 0 CHECK(must_change IN (0,1))
);
