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
from gpm_common.auth import (
    AuthError,
    TokenPayload,
    create_token,
    decode_token,
    generate_secret,
    hash_password,
    require_admin,
    require_token,
    verify_password,
)
from gpm_common.game_adapter import GameAdapter, GameAdapterRegistry
from gpm_common.adapters.minecraft import MinecraftAdapter
from gpm_common.hashing import compute_sha256
from gpm_common.heartbeat import Heartbeat
from gpm_common.lights import Light, LightLevel, aggregate_light, compute_server_light
from gpm_common.reporter import Reporter
from gpm_common.storage import (
    build_meta_path,
    build_storage_path,
    dir_size,
    ensure_dir,
    safe_join,
)

__version__ = "1.0.0"
__all__ = [
    "API_PREFIX",
    "API_VERSION",
    "AuthError",
    "ErrorCode",
    "GameAdapter",
    "GameAdapterRegistry",
    "GameInfo",
    "GamePushError",
    "Heartbeat",
    "LaunchConfig",
    "Light",
    "LightLevel",
    "MinecraftAdapter",
    "Mod",
    "Modpack",
    "ModpackCreate",
    "ModCreate",
    "Reporter",
    "StatusResponse",
    "SyncResponse",
    "TokenPayload",
    "aggregate_light",
    "build_storage_path",
    "build_meta_path",
    "compute_server_light",
    "compute_sha256",
    "create_token",
    "decode_token",
    "dir_size",
    "ensure_dir",
    "generate_secret",
    "hash_password",
    "require_admin",
    "require_token",
    "route",
    "safe_join",
    "verify_password",
]
