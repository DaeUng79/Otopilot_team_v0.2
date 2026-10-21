"""Validated, frontend-independent input contracts (Action IDs COM/DRAW/ROS)."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ID = Annotated[str, Field(min_length=1, max_length=100)]
Version = Annotated[int, Field(ge=1, strict=True)]
Scope = Literal["DEPARTMENT_POOL", "PROJECT"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Scoped(Input):
    department_id: ID
    scope: Scope = "DEPARTMENT_POOL"
    project_id: ID | None = None

    @model_validator(mode="after")
    def check_scope(self) -> "Scoped":
        if (self.scope == "PROJECT") != (self.project_id is not None):
            raise ValueError("PROJECT requires project_id; DEPARTMENT_POOL excludes it")
        return self


class CandidateData(Input):
    name: str = Field(min_length=1, max_length=100)
    organization_name: str = Field(min_length=1, max_length=200)
    department_name: str | None = Field(default=None, max_length=200)
    position: str | None = Field(default=None, max_length=100)
    phone: str = Field(min_length=1, max_length=30)
    email: str | None = Field(default=None, max_length=254)
    specialty_ids: list[ID] = Field(min_length=1, max_length=30)


class CandidateCreate(CandidateData, Scoped):
    pass


class CandidateUpdate(CandidateData):
    candidate_id: ID
    version: Version


class CandidateDelete(Input):
    candidate_id: ID
    version: Version


class CandidateQuery(Scoped):
    search: str = Field(default="", max_length=200)
    specialty_id: ID | None = None
    active: bool | None = None
    page: int = Field(default=1, ge=1, strict=True)
    page_size: int = Field(default=50, ge=1, le=200, strict=True)


class ProjectQuery(Input):
    project_id: ID


class Quota(Input):
    specialty_id: ID
    final_count: int = Field(ge=1, le=9, strict=True)


class Rules(ProjectQuery):
    selection_mode: Literal["POOL_RANDOM", "DIRECT"]
    # 정원 5~9명 (2026-10-18 사용자 결정; 기존 7~9에서 하한 확대)
    target_count: int = Field(ge=5, le=9, strict=True)
    reserve_count: int = Field(ge=0, le=27, strict=True)
    quotas: list[Quota] = Field(default_factory=list, max_length=9)
    version: int = Field(default=0, ge=0, strict=True)
    # 선정 방식을 바꿀 때 이전 방식으로 등록한 사업 후보를 함께 정리할지(추첨·명단 확정 전에만).
    clear_nominees: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def check_quotas(self) -> "Rules":
        if len({q.specialty_id for q in self.quotas}) != len(self.quotas):
            raise ValueError("duplicate specialties")
        if self.selection_mode == "POOL_RANDOM":
            if sum(q.final_count for q in self.quotas) != self.target_count:
                raise ValueError("quota sum must equal target_count")
            if self.reserve_count > self.target_count * 2:
                raise ValueError("reserves cannot exceed remaining shortlist")
        elif self.quotas:
            raise ValueError("DIRECT does not use random field quotas")
        return self


class Draw(ProjectQuery):
    rule_version: Version


class AddNominee(ProjectQuery):
    candidate_id: ID


class Contact(ProjectQuery):
    nominee_id: ID
    version: Version
    contact_status: Literal["NOT_CONTACTED", "AVAILABLE", "UNAVAILABLE", "CALLBACK"]
    contact_note: str = Field(default="", max_length=1000)


class Exclude(ProjectQuery):
    nominee_id: ID
    version: Version
    reason: str | None = Field(min_length=1, max_length=500)


class NomineeQuery(ProjectQuery):
    contact_status: Literal["NOT_CONTACTED", "AVAILABLE", "UNAVAILABLE", "CALLBACK"] | None = None
    specialty_id: ID | None = None


class Member(Input):
    nominee_id: ID
    version: Version
    member_kind: Literal["PRIMARY", "RESERVE"]
    reserve_order: int | None = Field(default=None, ge=1, strict=True)

    @model_validator(mode="after")
    def check_reserve(self) -> "Member":
        if (self.member_kind == "RESERVE") != (self.reserve_order is not None):
            raise ValueError("only reserves have reserve_order")
        return self


class ConfirmRoster(ProjectQuery):
    rule_version: Version
    # 본위원 5~9명 + 예비위원 1~3명 → 6~12명
    members: list[Member] = Field(min_length=6, max_length=12)
    # The original screen chooses reserve positions at final confirmation.
    reserve_count: int | None = Field(default=None, ge=0, le=27, strict=True)


class Preview(Scoped):
    filename: str = Field(min_length=1, max_length=255)


class CommitImport(Input):
    preview_id: ID
    version: Version


class ExportDraw(ProjectQuery):
    draw_id: ID


class ExportRoster(ProjectQuery):
    roster_id: ID
