"""The action IDs are the single button-to-service contract."""

from app.admin import admin_service as admins
from app.evaluation import attendance_service as attendance
from app.admin import dashboard_service as dashboard
from app.admin import department_service as departments
from app.evaluation import evaluation_service as evaluation
from app.admin import project_service as projects
from app.evaluation import result_service as results
from app.evaluation import signature_service as signatures

ACTIONS = {
    "ADM-DEPT-LIST": departments.list_departments,
    "ADM-DEPT-SAVE": departments.save_department,
    "ADM-DEPT-STATE": departments.set_department_state,
    "ADM-RESTORE": admins.restore_admin,
    "ADM-RESET": admins.reset_password,
    "ADM-01": admins.search_admins,
    "ADM-02": admins.create_admin,
    "ADM-03": admins.update_admin,
    "ADM-04": admins.deactivate_admin,
    "ADM-05": admins.set_permissions,
    "PRJ-01": projects.search_projects,
    "PRJ-02": projects.create_project,
    "PRJ-03": projects.update_project,
    "PRJ-04": projects.archive_project,
    "PRJ-05": projects.project_detail,
    "PRJ-08": projects.list_deleted_projects,
    "PRJ-09": projects.deleted_project_detail,
    "PRJ-06": projects.save_vendor,
    "PRJ-07": projects.archive_vendor,
    "DASH-01": dashboard.get_overview,
    "ATT-00": evaluation.prepare_session,
    "ATT-01": attendance.confirm_attendance,
    "ATT-02": attendance.list_attendance,
    "ATT-03": attendance.lock_participants,
    "ATT-04": attendance.designate_chair,
    "ATT-05": evaluation.open_session,
    "SCO-01": evaluation.get_sheets,
    "SCO-02": evaluation.save_scores,
    "SCO-03": evaluation.review_scores,
    "SCO-04": signatures.save_signature,
    "SCO-05": evaluation.submit_evaluation,
    "RES-01": results.get_results,
    "RES-02": results.aggregate_results,
    "RES-03": signatures.save_signature,
    "RES-04": results.confirm_results,
}
READS = {
    "ADM-DEPT-LIST",
    "ADM-01",
    "PRJ-01",
    "PRJ-05",
    "PRJ-08",
    "PRJ-09",
    "DASH-01",
    "ATT-02",
    "SCO-01",
    "SCO-03",
    "RES-01",
}
