"""认证与授权工具：密码哈希（pbkdf2_hmac）+ JWT（HS256）+ FastAPI 依赖。

设计目标：
- 零额外依赖：仅用 Python 标准库（hashlib / hmac / json / base64 / time）
- 自包含 JWT：服务端与后台各自签发与校验，无需共享 session 存储
- 密码哈希：pbkdf2_hmac(sha256)，自带 salt，抗彩虹表

用法（服务端 / 后台）：
    from gpm_common.auth import hash_password, verify_password, create_token, decode_token

    # 登录
    if verify_password(input_pwd, stored_hash):
        token = create_token({"sub": username, "role": "admin"}, secret, expires_seconds=86400)

    # 校验（FastAPI 依赖）
    from gpm_common.auth import require_token
    @router.post("...", dependencies=[Depends(require_token(secret))])
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Optional

from pydantic import BaseModel, Field


# 默认 token 有效期：24 小时
DEFAULT_TOKEN_EXPIRES_SECONDS = 86400

# pbkdf2 迭代次数
_PBKDF2_ITERATIONS = 200_000


class AuthError(Exception):
    """认证失败异常。"""

    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class TokenPayload(BaseModel):
    """JWT 载荷。"""

    sub: str = Field(..., description="用户名 / 主体标识")
    role: str = Field(default="admin", description="角色")
    iat: int = Field(..., description="签发时间（unix 秒）")
    exp: int = Field(..., description="过期时间（unix 秒）")


# ----------------------------- 密码哈希 -----------------------------

def hash_password(password: str, iterations: int = _PBKDF2_ITERATIONS) -> str:
    """对密码做 pbkdf2_hmac(sha256) 哈希。返回格式：pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>。"""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码是否匹配存储的哈希。使用恒定时间比较防侧信道。"""
    try:
        algo, iter_str, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(expected, actual)
    except (ValueError, TypeError):
        return False


# ----------------------------- JWT (HS256) -----------------------------

def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _segment(obj: dict) -> str:
    return _b64encode(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def create_token(
    payload: dict[str, Any],
    secret: str,
    expires_seconds: int = DEFAULT_TOKEN_EXPIRES_SECONDS,
) -> str:
    """签发 JWT。payload 至少应包含 sub（用户名）。自动注入 iat / exp。"""
    now = int(time.time())
    full = {
        "sub": payload.get("sub", ""),
        "role": payload.get("role", "admin"),
        "iat": now,
        "exp": now + expires_seconds,
        **{k: v for k, v in payload.items() if k not in ("sub", "role", "iat", "exp")},
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = f"{_segment(header)}.{_segment(full)}"
    sig = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64encode(sig)}"


def decode_token(token: str, secret: str) -> TokenPayload:
    """校验并解码 JWT。失败抛 AuthError。"""
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
    except ValueError:
        raise AuthError("令牌格式错误")
    # 验签
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        actual_sig = _b64decode(sig_b64)
    except Exception:
        raise AuthError("令牌签名无效")
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise AuthError("令牌签名不匹配")
    # 解析载荷
    try:
        payload = json.loads(_b64decode(payload_b64).decode("utf-8"))
    except Exception:
        raise AuthError("令牌载荷无效")
    now = int(time.time())
    if payload.get("exp", 0) < now:
        raise AuthError("令牌已过期", status_code=401)
    return TokenPayload(**payload)


# ----------------------------- FastAPI 依赖 -----------------------------

def require_token(secret: str):
    """返回一个 FastAPI 依赖项：从 Authorization: Bearer <token> 解析并校验令牌。

    用法：
        from fastapi import Depends
        @router.post(..., dependencies=[Depends(require_token(secret))])

    或取当前用户：
        @router.get(...)
        def me(user = Depends(require_token(secret))):
            return user
    """
    from fastapi import Header  # 局部导入，避免 gpm_common 强依赖 fastapi

    def _dependency(authorization: Optional[str] = Header(default=None)) -> TokenPayload:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise AuthError("缺少认证令牌", status_code=401)
        token = authorization.split(" ", 1)[1].strip()
        return decode_token(token, secret)

    return _dependency


def require_admin(secret: str):
    """返回一个 FastAPI 依赖项：要求当前登录用户为管理员（role == "admin"）。

    在 require_token 基础上额外校验角色：令牌缺失/无效 → 401；非管理员 → 403。
    用于后台管理类写操作（上传/删除/修改、用户管理、系统更新、配置修改、仪表盘），
    使普通用户（role=user）即使登录拿到 token 也无法调用这些接口。
    普通用户仍可登录客户端、改自己的密码、浏览整合包/模组列表（读操作开放）。

    用法：
        from fastapi import Depends
        @router.post(..., dependencies=[Depends(require_admin(secret))])
    """
    from fastapi import Header  # 局部导入，避免 gpm_common 强依赖 fastapi

    def _dependency(authorization: Optional[str] = Header(default=None)) -> TokenPayload:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise AuthError("缺少认证令牌", status_code=401)
        token = authorization.split(" ", 1)[1].strip()
        payload = decode_token(token, secret)
        if payload.role != "admin":
            raise AuthError("需要管理员权限", status_code=403)
        return payload

    return _dependency


def generate_secret() -> str:
    """生成一个随机 secret（用于未配置时的兜底，生产环境应显式配置）。"""
    return secrets.token_urlsafe(48)
