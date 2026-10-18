"""Internal dispatch only. The existing FastAPI host handles HTTP and authentication."""
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .auth import Principal
from .envelope import ApiError
from .settings import API_PREFIX, Settings


@dataclass
class Response:
    status: int = 200
    data: Any = None
    meta: dict = field(default_factory=dict)
    headers: list = field(default_factory=list)
    raw: bytes | None = None
    content_type: str = "application/json"
    cache_control: str = "no-store"


@dataclass
class Request:
    method: str
    path: str
    query: dict
    headers: dict
    body: bytes
    request_id: str
    params: dict
    settings: Settings
    _principal: Principal

    def json(self):
        try:
            value = json.loads(self.body or b"{}")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ApiError("INPUT_INVALID", "JSON 본문을 확인하세요.", 400) from exc
        if not isinstance(value, dict):
            raise ApiError("INPUT_INVALID", "JSON 객체가 필요합니다.", 400)
        return value

    def arg(self, name, default=None):
        return self.query.get(name, [default])[0]

    def principal(self, conn, *, touch=True):
        return self._principal


class App:
    def __init__(self, settings):
        self.settings = settings
        self.routes = []

    def route(self, method, pattern, handler):
        self.routes.append((method, re.compile('^' + API_PREFIX + pattern + '$'), handler))

    def dispatch(self, request):
        for method, pattern, handler in self.routes:
            match = pattern.fullmatch(request.path)
            if match and method == request.method:
                request.params = match.groupdict()
                return handler(request)
        raise ApiError("NOT_FOUND", "없는 주소 또는 허용되지 않은 메서드입니다.", 404)
