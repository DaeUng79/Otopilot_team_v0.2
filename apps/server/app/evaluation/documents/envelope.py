"""응답 형식과 공통 오류 (인계서 v2 09장).

성공: {"data": ..., "meta": {"request_id", "version"?, "sync_status"?}}
실패: {"error": {"code", "message", "fields"?, "retryable"}, "meta": {"request_id"}}
"""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, *,
                 fields: dict[str, str] | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.fields = fields
        self.retryable = retryable


# 자주 쓰는 오류 생성기
def input_invalid(message: str, fields: dict[str, str] | None = None) -> ApiError:
    return ApiError("INPUT_INVALID", message, 400, fields=fields)


def auth_required() -> ApiError:
    return ApiError("AUTH_REQUIRED", "로그인이 필요해요.", 401)


def auth_failed() -> ApiError:
    # 결정 5: 불일치·미선정·취소·중복 모두 같은 문구·같은 상태코드
    return ApiError("AUTH_FAILED", "이름이나 휴대전화 뒤 4자리를 확인해 주세요.", 401)


def forbidden(message: str = "이 작업을 할 권한이 없어요.", code: str = "FORBIDDEN") -> ApiError:
    return ApiError(code, message, 403)


def not_found(message: str = "찾을 수 없어요.") -> ApiError:
    return ApiError("NOT_FOUND", message, 404)


def conflict(code: str, message: str) -> ApiError:
    return ApiError(code, message, 409)


def validation_failed(message: str, fields: dict[str, str] | None = None) -> ApiError:
    return ApiError("VALIDATION_FAILED", message, 422, fields=fields)


def rate_limited() -> ApiError:
    return ApiError("RATE_LIMITED", "잠시 뒤 다시 시도해 주세요.", 429, retryable=True)


def upstream_unavailable(message: str) -> ApiError:
    return ApiError("UPSTREAM_UNAVAILABLE", message, 503, retryable=True)


def success(data: Any, request_id: str, **meta: Any) -> dict[str, Any]:
    body = {"data": data, "meta": {"request_id": request_id}}
    for key, value in meta.items():
        if value is not None:
            body["meta"][key] = value
    return body


def failure(error: ApiError, request_id: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": error.code, "message": error.message, "retryable": error.retryable}
    if error.fields:
        payload["fields"] = error.fields
    return {"error": payload, "meta": {"request_id": request_id}}
