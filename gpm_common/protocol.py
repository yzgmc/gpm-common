"""协议常量：API 前缀、版本、错误码、统一错误异常。

所有端必须使用相同的协议版本，否则客户端与服务端无法互通。
"""

from typing import Any, Optional


API_PREFIX = "/api/v1"
API_VERSION = "1.0.0"


def route(path: str) -> str:
    """拼接完整 API 路由，例如 route("/modpacks") -> "/api/v1/modpacks"。"""
    if not path.startswith("/"):
        path = "/" + path
    return f"{API_PREFIX}{path}"


class ErrorCode:
    """统一错误码，便于客户端按码处理。"""

    UNKNOWN = "UNKNOWN"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    HASH_MISMATCH = "HASH_MISMATCH"
    ADAPTER_NOT_FOUND = "ADAPTER_NOT_FOUND"
    PROTOCOL_MISMATCH = "PROTOCOL_MISMATCH"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"


class GamePushError(Exception):
    """业务异常，携带错误码与可选的 HTTP 状态码。"""

    def __init__(
        self,
        message: str,
        code: str = ErrorCode.UNKNOWN,
        status_code: int = 400,
        details: Optional[Any] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details

    def to_dict(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }
