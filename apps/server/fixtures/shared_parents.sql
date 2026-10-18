-- Development fixture only. Production parent schemas belong to the common module.
CREATE TABLE IF NOT EXISTS departments (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    organization_name TEXT NOT NULL,
    name TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    deleted_at TEXT,
    deleted_by TEXT REFERENCES admin_users(id) ON DELETE RESTRICT ON UPDATE RESTRICT
);

CREATE TABLE IF NOT EXISTS admin_users (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    department_id TEXT REFERENCES departments(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    display_name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    password_changed_at TEXT NOT NULL,
    deleted_at TEXT,
    deleted_by TEXT REFERENCES admin_users(id) ON DELETE RESTRICT ON UPDATE RESTRICT
);

CREATE TABLE IF NOT EXISTS admin_permissions (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    admin_id TEXT NOT NULL REFERENCES admin_users(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    permission_code TEXT NOT NULL,
    granted_by TEXT NOT NULL REFERENCES admin_users(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    UNIQUE(admin_id,permission_code)
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT NOT NULL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
    department_id TEXT NOT NULL REFERENCES departments(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    name TEXT NOT NULL,
    contact_organization TEXT NOT NULL,
    contact_department TEXT NOT NULL,
    contact_position TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    contact_phone_cipher BLOB NOT NULL,
    contact_email_cipher BLOB,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    created_by TEXT NOT NULL REFERENCES admin_users(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    deleted_at TEXT,
    deleted_by TEXT REFERENCES admin_users(id) ON DELETE RESTRICT ON UPDATE RESTRICT
);