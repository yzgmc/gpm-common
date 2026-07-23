"""Pydantic 数据模型，所有端共用。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class GameInfo(BaseModel):
    """游戏注册信息。每个适配器对应一个 GameInfo。"""

    name: str = Field(..., description="游戏唯一标识，例如 minecraft")
    display_name: str = Field(..., description="展示名称，例如 Minecraft")
    adapter: str = Field(..., description="适配器类名")
    enabled: bool = Field(default=True, description="是否启用")


class LaunchConfig(BaseModel):
    """启动配置，客户端根据此配置生成启动命令。"""

    java_path: Optional[str] = Field(default=None, description="java 可执行文件路径，None 时使用系统默认")
    jvm_args: list[str] = Field(default_factory=list, description="JVM 参数，例如 -Xmx4G")
    extra_args: list[str] = Field(default_factory=list, description="额外的启动参数")


class ModpackBase(BaseModel):
    """整合包元数据公共字段。"""

    name: str = Field(..., description="整合包名称")
    version: str = Field(..., description="整合包版本号")
    game: str = Field(..., description="游戏标识，例如 minecraft")
    game_version: str = Field(..., description="游戏版本，例如 1.20.1")
    mod_loader: str = Field(default="vanilla", description="模组加载器：vanilla/forge/fabric/quilt")
    mod_loader_version: Optional[str] = Field(default=None, description="模组加载器版本")
    description: str = Field(default="", description="整合包描述")
    enabled: bool = Field(default=True, description="是否上架（下架后客户端同步不到）")


class ModpackCreate(ModpackBase):
    """上传整合包时提交的元数据（不含服务端生成的字段）。"""


class Modpack(ModpackBase):
    """整合包完整模型，包含服务端生成的字段。"""

    id: str
    file_name: str
    file_size: int
    file_hash: str
    created_at: datetime
    updated_at: datetime


class ModBase(BaseModel):
    """模组元数据公共字段。"""

    name: str
    version: str
    game: str
    game_version: str = Field(default="", description="游戏版本，例如 1.20.1（可由模组 jar 自动识别）")
    mod_loader: str = Field(default="vanilla", description="模组加载器：vanilla/forge/fabric/quilt")
    mod_loader_version: Optional[str] = Field(default=None, description="模组加载器版本")
    modpack_id: Optional[str] = Field(default=None, description="所属整合包 ID（可选）")
    description: str = ""
    enabled: bool = Field(default=True, description="是否上架（下架后客户端同步不到）")


class ModCreate(ModBase):
    """上传模组时提交的元数据。"""


class Mod(ModBase):
    """模组完整模型。"""

    id: str
    file_name: str
    file_size: int
    file_hash: str
    created_at: datetime
    updated_at: datetime


class SyncResponse(BaseModel):
    """客户端同步响应：返回当前所有整合包与模组列表，客户端据此判断需要下载/更新的条目。"""

    protocol_version: str
    server_name: str
    modpacks: list[Modpack]
    mods: list[Mod]
    games: list[GameInfo]
    server_time: datetime


class StatusResponse(BaseModel):
    """服务端状态响应，供 web-admin 监测。"""

    server_name: str
    server_kind: str = Field(..., description="windows-server / web-server")
    status: str = Field(default="online", description="online/offline/degraded")
    protocol_version: str
    uptime_seconds: float
    modpack_count: int
    mod_count: int
    storage_used_bytes: int
    started_at: datetime
