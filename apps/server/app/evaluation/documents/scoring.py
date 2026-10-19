"""Read-only evaluation references for document comparison."""
import sqlite3
from typing import Any

def display_name(code: str) -> str:
    return code if code.endswith("사") else f"{code}사"

def criteria_items(conn: sqlite3.Connection, version_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, parent_id, code, title, description, is_scorable, max_score, score_step, sort_order "
        "FROM ref_approved_criteria_items WHERE approved_criteria_version_id = ? AND is_deleted = 0 ORDER BY sort_order, code",
        (version_id,)).fetchall()
    return [dict(r) for r in rows]

def proposals_of(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT id, display_code, vendor_id, proposal_upload_id FROM session_proposals WHERE session_id = ? ORDER BY display_code",
                        (session_id,)).fetchall()
    return [{"session_proposal_id": r["id"], "display_code": r["display_code"], "display_name": display_name(r["display_code"]),
             "vendor_id": r["vendor_id"], "proposal_upload_id": r["proposal_upload_id"]} for r in rows]
