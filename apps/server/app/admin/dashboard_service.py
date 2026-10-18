"""DASH-01: aggregate authorized read services, never cross-database SQL."""

import sqlite3

from app.shared.db import DTO, Actor, Store, rows


def get_overview(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    s.admin(a, "VIEW_DASHBOARD")
    projects = rows(
        c,
        "SELECT id,name,status FROM projects WHERE deleted_at IS NULL AND (?='SUPER_ADMIN' OR department_id=?)",
        (a.role, a.department_id),
    )
    departments = rows(
        c,
        "SELECT id,name FROM departments WHERE active=1 AND (?='SUPER_ADMIN' OR id=?)",
        (a.role, a.department_id),
    )
    admins = rows(
        c,
        "SELECT id FROM admin_users WHERE active=1 AND (?='SUPER_ADMIN' OR department_id=?)",
        (a.role, a.department_id),
    )
    with s.connect() as e:
        sessions = rows(e, "SELECT id,project_id,status FROM evaluation_sessions")
        ids = {p["id"] for p in projects}
        sessions = [r for r in sessions if r["project_id"] in ids]
        material_count = sum(
            e.execute(
                "SELECT COUNT(*) FROM ref_proposal_uploads WHERE project_id=? AND is_deleted=0",
                (p,),
            ).fetchone()[0]
            for p in ids
        )
    return {
        "projects": projects,
        "departments": departments,
        "admin_count": len(admins),
        "sessions": sessions,
        "document_snapshot_count": material_count,
        "document_count_basis": "평가 DB에 수신된 제안서 버전 수; 전체 자료 통계는 문서 모듈 연계 필요",
    }
