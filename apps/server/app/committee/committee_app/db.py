import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
 id TEXT PRIMARY KEY, payload TEXT NOT NULL, phone TEXT NOT NULL,
 active INTEGER NOT NULL, version INTEGER NOT NULL DEFAULT 0,
 source_key TEXT UNIQUE, created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS unique_candidate_phone ON candidates(phone) WHERE phone != '';
CREATE TABLE IF NOT EXISTS imports (
 id TEXT PRIMARY KEY, file_hash TEXT NOT NULL, filename TEXT NOT NULL,
 payload TEXT NOT NULL, expires_at REAL NOT NULL, committed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS unique_committed_file ON imports(file_hash)
 WHERE committed_at IS NOT NULL;
CREATE TABLE IF NOT EXISTS projects (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, fields TEXT NOT NULL, target INTEGER NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS draws (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL UNIQUE REFERENCES projects(id),
 pool_snapshot TEXT NOT NULL, shortlist TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL,
 method TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL,
 final_ids TEXT NOT NULL DEFAULT '[]', finalized_at TEXT, assigned_at TEXT,
 version INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS contacts (
 project_id TEXT NOT NULL REFERENCES projects(id),
 candidate_id TEXT NOT NULL REFERENCES candidates(id),
 status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 0,
 updated_at TEXT NOT NULL, PRIMARY KEY(project_id,candidate_id)
);
CREATE TABLE IF NOT EXISTS assignments (
 project_id TEXT NOT NULL REFERENCES projects(id),
 candidate_id TEXT NOT NULL REFERENCES candidates(id),
 created_at TEXT NOT NULL, PRIMARY KEY(project_id,candidate_id)
);
CREATE TABLE IF NOT EXISTS otp_requests (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 candidate_id TEXT NOT NULL REFERENCES candidates(id), code_hash TEXT NOT NULL,
 expires_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, used INTEGER NOT NULL DEFAULT 0,
 created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, kind TEXT NOT NULL, project_id TEXT, candidate_id TEXT,
 mode TEXT NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, subject TEXT NOT NULL,
 actor TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL
);
PRAGMA user_version=1;
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            revision = conn.execute("PRAGMA user_version").fetchone()[0]
            if revision > 2:
                raise RuntimeError(
                    "DB가 현재 코드보다 새 버전입니다. 해당 버전의 코드를 사용하세요."
                )
            conn.execute("PRAGMA journal_mode=WAL")
            if revision == 0:
                conn.executescript(SCHEMA)
            if revision < 2:
                conn.executescript("""
BEGIN IMMEDIATE;
ALTER TABLE projects ADD COLUMN configured INTEGER NOT NULL DEFAULT 1;
ALTER TABLE projects ADD COLUMN version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE draws ADD COLUMN reserve_ids TEXT NOT NULL DEFAULT '[]';
CREATE TABLE proposals (
 project_id TEXT PRIMARY KEY REFERENCES projects(id), filename TEXT NOT NULL,
 sha256 TEXT NOT NULL UNIQUE, content BLOB NOT NULL, created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX unique_candidate_email ON candidates(json_extract(payload,'$.email'))
 WHERE coalesce(json_extract(payload,'$.email'),'') != '';
PRAGMA user_version=2;
COMMIT;
""")

    @contextmanager
    def connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=20)) as conn:
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("PRAGMA busy_timeout=20000")
                if write:
                    conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            finally:
                if conn.in_transaction:
                    conn.rollback()
