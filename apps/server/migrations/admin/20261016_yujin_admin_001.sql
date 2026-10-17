-- Frozen v2 fields and local foreign keys. Never attach another database.

PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS departments (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "organization_name" TEXT NOT NULL,
  "name" TEXT NOT NULL,
  "code" TEXT NOT NULL UNIQUE,
  "active" INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  "deleted_at" TEXT,
  "deleted_by" TEXT,
  FOREIGN KEY(deleted_by) REFERENCES admin_users(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS admin_users (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "department_id" TEXT,
  "username" TEXT NOT NULL UNIQUE,
  "password_hash" TEXT NOT NULL,
  "role" TEXT NOT NULL,
  "display_name" TEXT NOT NULL,
  "active" INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  "password_changed_at" TEXT NOT NULL,
  "deleted_at" TEXT,
  "deleted_by" TEXT,
  FOREIGN KEY(department_id) REFERENCES departments(id) ON DELETE RESTRICT,
  FOREIGN KEY(deleted_by) REFERENCES admin_users(id) ON DELETE RESTRICT,
  CHECK((role='SUPER_ADMIN' AND department_id IS NULL) OR (role='DEPARTMENT_ADMIN' AND department_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS admin_permissions (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "admin_id" TEXT NOT NULL,
  "permission_code" TEXT NOT NULL,
  "granted_by" TEXT NOT NULL,
  UNIQUE(admin_id,permission_code),
  FOREIGN KEY(admin_id) REFERENCES admin_users(id) ON DELETE RESTRICT,
  FOREIGN KEY(granted_by) REFERENCES admin_users(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS projects (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "department_id" TEXT NOT NULL,
  "name" TEXT NOT NULL,
  "contact_organization" TEXT NOT NULL,
  "contact_department" TEXT NOT NULL,
  "contact_position" TEXT NOT NULL,
  "contact_name" TEXT NOT NULL,
  "contact_phone_cipher" BLOB NOT NULL,
  "contact_email_cipher" BLOB,
  "status" TEXT NOT NULL DEFAULT 'DRAFT',
  "created_by" TEXT NOT NULL,
  "deleted_at" TEXT,
  "deleted_by" TEXT,
  FOREIGN KEY(department_id) REFERENCES departments(id) ON DELETE RESTRICT,
  FOREIGN KEY(created_by) REFERENCES admin_users(id) ON DELETE RESTRICT,
  FOREIGN KEY(deleted_by) REFERENCES admin_users(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS project_vendors (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "project_id" TEXT NOT NULL,
  "display_code" TEXT NOT NULL,
  "legal_name" TEXT NOT NULL,
  "sort_order" INTEGER NOT NULL,
  "active" INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  "deleted_at" TEXT,
  "deleted_by" TEXT,
  UNIQUE(project_id,display_code),
  FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE RESTRICT,
  FOREIGN KEY(deleted_by) REFERENCES admin_users(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS auth_sessions (
  "id" TEXT NOT NULL PRIMARY KEY,
  "created_at" TEXT NOT NULL,
  "updated_at" TEXT NOT NULL,
  "version" INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  "principal_id" TEXT NOT NULL,
  "token_hash" TEXT NOT NULL UNIQUE,
  "project_id" TEXT,
  "auth_method" TEXT NOT NULL,
  "expires_at" TEXT NOT NULL,
  "revoked_at" TEXT,
  FOREIGN KEY(principal_id) REFERENCES admin_users(id) ON DELETE RESTRICT,
  FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE RESTRICT
);
