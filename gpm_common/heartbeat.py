"""心跳上报协议：所有端（server / web-server / client）主动向 web-admin 上报状态。

Push 模型：web-admin 不再轮询，而是被动接收各端定期上报的 Heartbeat。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


class Heartbeat(BaseModel):
    """单次心跳上报载荷。所有端共用同一结构。"""

    reporter_id: str = Field(..., description="上报端唯一标识，建议 uuid 或稳定名称")
    kind: str = Field(..., description="上报端类型：windows-server / web-server / client")
    name: str = Field(..., description="展示名称")
    base_url: Optional[str] = Field(
        default=None,
        description="服务端可被外部访问的地址（客户端无）；web-admin 据此反向拉取 sync 等",
    )
    status: str = Field(default="online", description="online / degraded / offline")
    protocol_version: str = Field(..., description="协议版本，需与 web-admin 一致")
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="自由指标字段，例如 modpack_count / mod_count / storage_used_bytes / uptime_seconds / installed_modpacks",
    )
    extra: dict[str, Any] = Field(default_factory=dict, description="附加信息")
