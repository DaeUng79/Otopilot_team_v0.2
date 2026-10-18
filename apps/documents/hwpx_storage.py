"""파싱 JSON과 이미지 바이너리를 하나의 SQLite 파일에 저장한다.

예: python apps/documents/hwpx_storage.py output/json/parsed.json \
        --database documents.sqlite3 --source 원본.hwpx

JSON을 원본 그대로 보관하고 조회에 필요한
페이지·블록·셀을 별도 테이블에 투영한다. 이미지는 SHA256 기준 BLOB으로 중복 제거한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import closing, contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    active_revision TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parse_snapshots (
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    revision TEXT NOT NULL,
    parser_version TEXT,
    schema_version TEXT,
    document_json TEXT NOT NULL,
    stored_at TEXT NOT NULL,
    PRIMARY KEY (document_id, revision)
);
CREATE TABLE IF NOT EXISTS pages (
    document_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    physical_page_number INTEGER NOT NULL,
    page_number INTEGER,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY (document_id, revision, physical_page_number),
    FOREIGN KEY (document_id, revision) REFERENCES parse_snapshots(document_id, revision)
);
CREATE TABLE IF NOT EXISTS blocks (
    document_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    block_id TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    type TEXT NOT NULL,
    parent_block_id TEXT,
    parent_cell_id TEXT,
    text TEXT,
    physical_page_numbers_json TEXT NOT NULL,
    block_json TEXT NOT NULL,
    PRIMARY KEY (document_id, revision, block_id),
    FOREIGN KEY (document_id, revision) REFERENCES parse_snapshots(document_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_blocks_order ON blocks(document_id, revision, order_index);
CREATE TABLE IF NOT EXISTS table_cells (
    document_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    block_id TEXT NOT NULL,
    cell_id TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    col_index INTEGER NOT NULL,
    row_span INTEGER NOT NULL,
    col_span INTEGER NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (document_id, revision, block_id, cell_id),
    FOREIGN KEY (document_id, revision, block_id) REFERENCES blocks(document_id, revision, block_id)
);
CREATE TABLE IF NOT EXISTS assets (
    sha256 TEXT PRIMARY KEY,
    byte_size INTEGER NOT NULL,
    data BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshot_assets (
    document_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    sha256 TEXT NOT NULL REFERENCES assets(sha256),
    metadata_json TEXT NOT NULL,
    PRIMARY KEY (document_id, revision, asset_id),
    FOREIGN KEY (document_id, revision) REFERENCES parse_snapshots(document_id, revision)
);
CREATE TABLE IF NOT EXISTS source_files (
    sha256 TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    data BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_documents (
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    added_at TEXT NOT NULL,
    PRIMARY KEY (project_id, document_id)
);
"""

PROJECT_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_profiles (
    project_id TEXT PRIMARY KEY REFERENCES projects(project_id),
    org TEXT NOT NULL DEFAULT '', dept TEXT NOT NULL DEFAULT '',
    pos TEXT NOT NULL DEFAULT '', owner TEXT NOT NULL DEFAULT '',
    tel TEXT NOT NULL DEFAULT '', mail TEXT NOT NULL DEFAULT '',
    date TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT '준비'
        CHECK(status IN ('준비', '평가 중', '완료')),
    updated_at TEXT NOT NULL, deleted_at TEXT, deletion_reason TEXT
);
"""
PROJECT_FIELDS = ('name', 'org', 'dept', 'pos', 'owner', 'tel', 'mail', 'date')


class ProjectError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


@contextmanager
def connect(path: str | Path):
    """SQLite 연결에 공통 row mapping, foreign key, transaction 처리를 적용한다."""
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _project_select() -> str:
    return """SELECT p.project_id AS id, p.name, p.created_at,
        COALESCE(m.org,'') AS org, COALESCE(m.dept,'') AS dept,
        COALESCE(m.pos,'') AS pos, COALESCE(m.owner,'') AS owner,
        COALESCE(m.tel,'') AS tel, COALESCE(m.mail,'') AS mail,
        COALESCE(m.date,'') AS date, COALESCE(m.status,'준비') AS status,
        COALESCE(m.updated_at,p.created_at) AS updated_at,
        (SELECT COUNT(*) FROM project_rfp_uploads u WHERE u.project_id=p.project_id) AS rfp_revisions,
        (SELECT j.status FROM requirement_jobs j WHERE j.project_id=p.project_id
         AND j.revision=(SELECT MAX(u.revision) FROM project_rfp_uploads u
                         WHERE u.project_id=p.project_id)) AS requirements_status
        FROM projects p LEFT JOIN project_profiles m ON m.project_id=p.project_id
        WHERE m.deleted_at IS NULL"""


def list_projects(path: str | Path) -> list[dict[str, Any]]:
    with connect(path) as connection:
        return [
            dict(row)
            for row in connection.execute(
                _project_select() + ' ORDER BY p.created_at DESC, p.project_id'
            )
        ]


def _get_project(connection: sqlite3.Connection, project_id: str) -> dict[str, Any]:
    row = connection.execute(
        _project_select() + ' AND p.project_id=?', (project_id,)
    ).fetchone()
    if row is None:
        raise ProjectError('사업을 찾을 수 없습니다. 삭제 여부를 확인해 주세요.', 404)
    return dict(row)


def get_project(path: str | Path, project_id: str) -> dict[str, Any]:
    with connect(path) as connection:
        return _get_project(connection, project_id)


def _validate_project(
    payload: Any, current: dict[str, Any] | None = None
) -> dict[str, str]:
    if not isinstance(payload, dict) or set(payload) - set(PROJECT_FIELDS):
        raise ProjectError('사업 정보의 필드를 확인해 주세요.')
    data = {key: (current or {}).get(key, '') for key in PROJECT_FIELDS}
    for key, value in payload.items():
        if not isinstance(value, str) or len(value) > (300 if key == 'name' else 150):
            raise ProjectError('입력값의 형식 또는 길이를 확인해 주세요.')
        data[key] = value.strip()
    if current and current['status'] != '준비':
        if any(data[key] != current[key] for key in ('name', 'org', 'dept', 'date')):
            raise ProjectError('평가가 시작된 사업의 식별 정보와 평가일은 변경할 수 없습니다.', 409)
    labels = dict(name='사업명', org='소속', dept='부서', pos='직책/직급', owner='성명', tel='전화')
    for key, label in labels.items():
        if not data[key]:
            raise ProjectError(f'{label}을(를) 입력해 주세요.')
    if not re.fullmatch(r'[0-9+() .-]{7,30}', data['tel']) or len(re.sub(r'\D', '', data['tel'])) < 7:
        raise ProjectError('전화번호를 확인해 주세요.')
    if data['mail'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', data['mail']):
        raise ProjectError('이메일 주소를 확인해 주세요.')
    if data['date']:
        try:
            if date.fromisoformat(data['date']).isoformat() != data['date']:
                raise ValueError()
        except ValueError:
            raise ProjectError('평가일은 YYYY-MM-DD 형식의 유효한 날짜여야 합니다.') from None
    return data


def save_project(
    path: str | Path, payload: Any, project_id: str | None = None
) -> dict[str, Any]:
    with connect(path) as connection:
        connection.execute('BEGIN IMMEDIATE')
        current = _get_project(connection, project_id) if project_id else None
        data = _validate_project(payload, current)
        now = datetime.now(timezone.utc).isoformat()
        project_id = project_id or uuid.uuid4().hex
        connection.execute(
            'INSERT INTO projects VALUES (?, ?, ?) ON CONFLICT(project_id) '
            'DO UPDATE SET name=excluded.name',
            (project_id, data['name'], now),
        )
        connection.execute(
            '''INSERT INTO project_profiles
            (project_id, org, dept, pos, owner, tel, mail, date, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(project_id) DO UPDATE SET
            org=excluded.org, dept=excluded.dept, pos=excluded.pos, owner=excluded.owner,
            tel=excluded.tel, mail=excluded.mail, date=excluded.date, updated_at=excluded.updated_at''',
            (project_id, *(data[key] for key in PROJECT_FIELDS[1:]), now),
        )
        return _get_project(connection, project_id)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _file_bytes(path: Path, expected_sha: str, expected_size: int | None = None) -> bytes:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha:
        raise ValueError(f"파일 SHA256이 파싱 결과와 다릅니다: {path}")
    if expected_size is not None and len(data) != expected_size:
        raise ValueError(f"파일 크기가 파싱 결과와 다릅니다: {path}")
    return data


def _asset_path(asset: dict[str, Any], document_id: str, asset_root: Path | None) -> Path:
    """기존 절대 경로가 낡았을 때 명시한 이미지 폴더에서 찾는다."""
    original = Path(asset["local_path"])
    candidates = [original]
    if asset_root is not None:
        candidates.extend((asset_root / document_id / original.name,
                           asset_root / original.name))
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(f"이미지 파일을 찾을 수 없습니다: {original.name}; --asset-root를 지정하세요.")


def save_to_sqlite(
    document: dict[str, Any], db_path: str | Path, *,
    source_path: str | Path | None = None,
    asset_root: str | Path | None = None,
    project_id: str | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    """파싱 결과·이미지를 원자적으로 저장하고 활성 revision을 갱신한다.

    원본 HWPX까지 한 DB 파일로 옮기려면 source_path를 전달한다. 반환된 revision은
    정렬된 JSON의 SHA256이며, 같은 JSON을 재저장해도 중복 snapshot을 만들지 않는다.
    """
    document_id = document["document_id"]
    source_sha = document["source_sha256"]
    if document_id != source_sha:
        raise ValueError("document_id와 source_sha256이 다릅니다.")
    if not isinstance(document.get("blocks"), list) or not isinstance(document.get("assets", []), list):
        raise ValueError("blocks와 assets는 배열이어야 합니다.")
    for key, values, id_key in (
        ("blocks", document["blocks"], "block_id"),
        ("assets", document.get("assets", []), "asset_id"),
        ("pages", document.get("pages", []), "physical_page_number"),
    ):
        ids = [value[id_key] for value in values]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{key}에 중복 ID가 있습니다.")
    if project_name and not project_id:
        raise ValueError("project_name을 지정할 때는 project_id도 필요합니다.")

    payload = _json(document)
    revision = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    root = Path(asset_root) if asset_root is not None else None
    image_data: dict[str, bytes] = {}
    for asset in document.get("assets", []):
        sha = asset["sha256"]
        if sha not in image_data:
            image_data[sha] = _file_bytes(
                _asset_path(asset, document_id, root), sha, asset.get("byte_size")
            )
    source_data = None
    if source_path is not None:
        source_data = _file_bytes(Path(source_path), source_sha)

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(path, timeout=30)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        with connection:
            connection.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(document_id) DO UPDATE SET "
                "filename=excluded.filename, source_sha256=excluded.source_sha256, "
                "active_revision=excluded.active_revision, updated_at=excluded.updated_at",
                (document_id, document.get("filename", ""), source_sha, revision, now, now),
            )
            snapshot = connection.execute(
                "INSERT OR IGNORE INTO parse_snapshots VALUES (?, ?, ?, ?, ?, ?)",
                (document_id, revision, document.get("parser_version"),
                 document.get("schema_version"), payload, now),
            )
            if snapshot.rowcount:
                connection.executemany(
                    "INSERT INTO pages VALUES (?, ?, ?, ?, ?)",
                    ((document_id, revision, page["physical_page_number"],
                      page.get("page_number"), _json(page)) for page in document.get("pages", [])),
                )
                connection.executemany(
                    "INSERT INTO blocks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ((document_id, revision, block["block_id"], block["order"], block["type"],
                      block.get("parent_block_id"), block.get("parent_cell_id"), block.get("text"),
                      _json(block.get("physical_page_numbers", [])), _json(block))
                     for block in document["blocks"]),
                )
                connection.executemany(
                    "INSERT INTO table_cells VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ((document_id, revision, block["block_id"], cell["cell_id"],
                      cell["row"], cell["col"], cell["row_span"], cell["col_span"], cell["text"])
                     for block in document["blocks"] if block["type"] == "table"
                     for row in block["table"]["cells"] for cell in row),
                )
            connection.executemany(
                "INSERT OR IGNORE INTO assets VALUES (?, ?, ?)",
                ((sha, len(data), sqlite3.Binary(data)) for sha, data in image_data.items()),
            )
            if snapshot.rowcount:
                connection.executemany(
                    "INSERT INTO snapshot_assets VALUES (?, ?, ?, ?, ?)",
                    ((document_id, revision, asset["asset_id"], asset["sha256"], _json(asset))
                     for asset in document.get("assets", [])),
                )
            if source_data is not None:
                connection.execute(
                    "INSERT OR IGNORE INTO source_files VALUES (?, ?, ?, ?)",
                    (source_sha, Path(source_path).name, len(source_data), sqlite3.Binary(source_data)),
                )
            if project_id:
                if project_name:
                    connection.execute(
                        "INSERT INTO projects VALUES (?, ?, ?) "
                        "ON CONFLICT(project_id) DO UPDATE SET name=excluded.name",
                        (project_id, project_name, now),
                    )
                else:
                    connection.execute(
                        "INSERT OR IGNORE INTO projects VALUES (?, ?, ?)",
                        (project_id, project_id, now),
                    )
                connection.execute(
                    "INSERT OR IGNORE INTO project_documents VALUES (?, ?, ?)",
                    (project_id, document_id, now),
                )
    return {
        "database": str(path.resolve()), "document_id": document_id,
        "revision": revision, "blocks": len(document["blocks"]),
        "pages": len(document.get("pages", [])), "assets": len(document.get("assets", [])),
        "source_stored": source_data is not None,
    }


def save_json_to_sqlite(
    json_path: str | Path, db_path: str | Path, *,
    source_path: str | Path | None = None,
    asset_root: str | Path | None = None,
    project_id: str | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    """파서 JSON 파일을 읽어 저장한다. 기본 이미지 위치는 JSON 폴더의 형제 images/."""
    path = Path(json_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    root = asset_root if asset_root is not None else path.parent.parent / "images"
    return save_to_sqlite(document, db_path, source_path=source_path, asset_root=root,
                          project_id=project_id, project_name=project_name)


def delete_document_from_sqlite(db_path: str | Path, document_id: str) -> bool:
    """문서와 그 파싱·AI 결과를 삭제하고 다른 문서가 쓰지 않는 BLOB만 정리한다."""
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"SQLite 파일을 찾지 못했습니다: {path}")
    with closing(sqlite3.connect(path, timeout=30)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            document = connection.execute(
                "SELECT source_sha256 FROM documents WHERE document_id=?", (document_id,)
            ).fetchone()
            if not document:
                return False
            image_hashes = [row[0] for row in connection.execute(
                "SELECT DISTINCT sha256 FROM snapshot_assets WHERE document_id=?", (document_id,)
            )]
            has_criteria = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='criteria_results'"
            ).fetchone()
            if has_criteria:
                connection.execute("DELETE FROM criteria_results WHERE document_id=?", (document_id,))
            has_results = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='requirement_results'"
            ).fetchone()
            if has_results:
                connection.execute("DELETE FROM requirement_results WHERE document_id=?", (document_id,))
            connection.execute("DELETE FROM project_documents WHERE document_id=?", (document_id,))
            for table in ("table_cells", "blocks", "pages", "snapshot_assets", "parse_snapshots"):
                connection.execute(f"DELETE FROM {table} WHERE document_id=?", (document_id,))
            connection.execute("DELETE FROM documents WHERE document_id=?", (document_id,))
            for sha256 in image_hashes:
                connection.execute(
                    "DELETE FROM assets WHERE sha256=? AND NOT EXISTS "
                    "(SELECT 1 FROM snapshot_assets WHERE snapshot_assets.sha256=?)",
                    (sha256, sha256),
                )
            connection.execute(
                "DELETE FROM source_files WHERE sha256=? AND NOT EXISTS "
                "(SELECT 1 FROM documents WHERE documents.source_sha256=?)",
                (document[0], document[0]),
            )
    return True


def load_document(db_path: str | Path, document_id: str, revision: str | None = None) -> dict[str, Any] | None:
    """활성 또는 지정한 revision의 원본 파싱 JSON을 돌려준다."""
    with closing(sqlite3.connect(db_path)) as connection:
        if revision is None:
            row = connection.execute(
                "SELECT s.document_json FROM parse_snapshots s "
                "JOIN documents d ON d.document_id=s.document_id AND d.active_revision=s.revision "
                "WHERE s.document_id=?", (document_id,),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT document_json FROM parse_snapshots WHERE document_id=? AND revision=?",
                (document_id, revision),
            ).fetchone()
    return json.loads(row[0]) if row else None


def load_asset(db_path: str | Path, sha256: str) -> bytes | None:
    """원본 JSON 안의 local_path 대신 SHA256으로 이미지 BLOB을 읽는다."""
    with closing(sqlite3.connect(db_path)) as connection:
        row = connection.execute("SELECT data FROM assets WHERE sha256=?", (sha256,)).fetchone()
    return row[0] if row else None


def load_source(db_path: str | Path, sha256: str) -> bytes | None:
    """source_path를 주고 저장한 경우 원본 HWPX/HWP 바이트를 읽는다."""
    with closing(sqlite3.connect(db_path)) as connection:
        row = connection.execute("SELECT data FROM source_files WHERE sha256=?", (sha256,)).fetchone()
    return row[0] if row else None


def main() -> None:
    parser = argparse.ArgumentParser(description="HWPX 파싱 JSON과 이미지를 SQLite에 저장")
    parser.add_argument("json_path", type=Path, help="hwpx_parser.py 결과 JSON")
    parser.add_argument("--database", type=Path, default=Path(__file__).resolve().parent / "documents.sqlite3")
    parser.add_argument("--source", type=Path, help="원본 HWPX/HWP도 BLOB으로 저장할 때 지정")
    parser.add_argument("--asset-root", type=Path, help="이미지 폴더 (기본: JSON 폴더의 형제 images/)")
    parser.add_argument("--project-id", help="프로젝트에 문서 연결")
    parser.add_argument("--project-name", help="새 프로젝트 이름")
    args = parser.parse_args()
    try:
        result = save_json_to_sqlite(
            args.json_path, args.database, source_path=args.source,
            asset_root=args.asset_root, project_id=args.project_id,
            project_name=args.project_name,
        )
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        parser.exit(1, f"SQLite 저장 실패: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
