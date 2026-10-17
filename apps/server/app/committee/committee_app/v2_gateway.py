"""Button action dispatcher for the team's authenticated API adapter; no HTTP server."""

from collections.abc import Awaitable, Callable

from app.committee import candidate_import
from app.committee import candidate_pool
from app.committee import committee_roster
from app.committee import committee_selection

from .v2_core import DTO, Context, ExportFile, ModuleError, Runtime

Action = Callable[..., Awaitable[DTO | ExportFile]]
ACTIONS: dict[str, Action] = {
    "COM-01": candidate_pool.search_candidates,
    "COM-02": candidate_import.download_template,
    "COM-04": candidate_import.commit_import,
    "COM-05": candidate_pool.create_candidate,
    "COM-06": candidate_pool.update_candidate,
    "COM-07": candidate_pool.deactivate_candidate,
    "COM-CATALOG": candidate_pool.list_specialties,
    "DRAW-01": committee_selection.save_rules,
    "DRAW-02": committee_selection.draw_shortlist,
    "DRAW-03": committee_selection.export_shortlist,
    "ROS-01": committee_roster.list_nominees,
    "ROS-02": committee_roster.add_nominee,
    "ROS-03": committee_roster.save_contact,
    "ROS-04": committee_roster.exclude_nominee,
    "ROS-05": committee_roster.confirm_roster,
    "ROS-06": committee_roster.export_roster,
}


async def dispatch_action(
    ctx: Context,
    action: str,
    command: DTO,
    *,
    runtime: Runtime,
    raw: bytes | None = None,
    password: str = "",
) -> DTO | ExportFile:
    """ctx must come from server authentication; never construct it from client JSON.

    The hosting HTTP adapter enforces sessions, CSRF when using cookies, upload size
    before reading multipart, and maps ModuleError.status to the HTTP status code.
    """
    if action not in ACTIONS and action != "COM-03":
        raise ModuleError("ACTION_UNKNOWN", "지원하지 않는 기능입니다.", 404)
    if action == "COM-03":
        if raw is None:
            raise ModuleError("FILE_REQUIRED", "엑셀 파일이 필요합니다.", 422)
        result: DTO | ExportFile = await candidate_import.preview_import(
            ctx, command, raw=raw, password=password, runtime=runtime
        )
    else:
        result = await ACTIONS[action](ctx, command, runtime=runtime)
    if isinstance(result, ExportFile):
        return result
    return {
        "data": result,
        "meta": {
            "request_id": ctx.request_key,
            **{k: result[k] for k in ("version", "sync_status") if k in result},
        },
    }


def error_response(ctx: Context, error: ModuleError) -> DTO:
    return {
        "error": {"code": error.code, "message": error.message, "retryable": error.status == 503},
        "meta": {"request_id": ctx.request_key},
    }
