"""Game Push Manager shared library.

提供所有端共用的数据模型、协议常量、游戏适配器接口与具体适配器实现。
"""

from gpm_common.models import (
    GameInfo,
    LaunchConfig,
    Mod,
    Modpack,
    ModpackCreate,
    ModCreate,
    StatusResponse,
    SyncResponse,
)
from gpm_common.protocol import (
    API_PREFIX,
    API_VERSION,
    ErrorCode,
    GamePushError,
    route,
)
from gpm_common.game_adapter import GameAdapter, GameAdapterRegistry
from gpm_common.adapters.minecraft import MinecraftAdapter
from gpm_common.hashing import compute_sha256
from gpm_common.storage import build_storage_path, safe_join

__version__ = "1.0.0"
__all__ = [
    "API_PREFIX",
    "API_VERSION",
    "ErrorCode",
    "GameAdapter",
    "GameAdapterRegistry",
    "GameInfo",
    "GamePushError",
    "LaunchConfig",
    "MinecraftAdapter",
    "Mod",
    "Modpack",
    "ModpackCreate",
    "ModCreate",
    "StatusResponse",
    "SyncResponse",
    "build_storage_path",
    "compute_sha256",
    "route",
    "safe_join",
]
