from typing import Literal

from pydantic import BaseModel


class CandidateCore(BaseModel):
    source_serial: str = ""
    organization: str
    position: str = ""
    name: str
    birth_date: str = ""
    region: str = ""
    category: str = ""
    department: str = ""
    specialty: str
    phone: str
    email: str = ""
    memo: str = ""
    legacy_first: str = ""
    legacy_final: str = ""
    legacy_project: str = ""
    fields: list[str]
    enabled: bool
    active: bool
    auth_ready: bool
    warnings: list[str]
    source_row: int | None = None
    source_sheet: str = ""


class CandidateRead(CandidateCore):
    id: str
    version: int


class ImportPreview(BaseModel):
    id: str
    filename: str
    rows: list[CandidateCore]
    total: int
    active: int
    drafts: int
    conflict_rows: list[int]
    expires_in: int


class ProjectRead(BaseModel):
    id: str
    name: str
    fields: list[str]
    target: Literal[7, 8, 9]
    created_at: str
    configured: bool = True
    version: int = 0


class SnapshotRead(BaseModel):
    id: str
    name: str
    organization: str
    position: str
    fields: list[str]
    phone: str
    version: int


class ContactRead(BaseModel):
    project_id: str
    candidate_id: str
    status: Literal["미연락", "연락 불가", "참여 가능", "참여 불가", "제척"]
    note: str
    version: int
    updated_at: str


class DrawRead(BaseModel):
    id: str
    project_id: str
    shortlist: list[SnapshotRead]
    snapshot_sha256: str
    method: str
    actor: str
    created_at: str
    final_ids: list[str]
    reserve_ids: list[str]
    finalized_at: str | None
    assigned_at: str | None
    version: int
    pool_count: int
    contacts: list[ContactRead]
    current_candidates: list[CandidateRead]
