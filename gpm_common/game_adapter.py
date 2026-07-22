"""游戏适配器抽象基类与注册中心。

每个游戏实现一个 GameAdapter 子类，负责：
1. 校验整合包/模组文件结构是否合法
2. 生成游戏启动命令
3. 返回该游戏支持的字段元信息（加载器列表等）

新增游戏时只需实现子类并在 GameAdapterRegistry 注册，
服务端 / 客户端核心代码无需修改。
"""

from __future__ import annotations

import abc
from typing import Optional

from gpm_common.models import GameInfo, LaunchConfig


class GameAdapter(abc.ABC):
    """游戏适配器抽象基类。"""

    game_name: str = ""
    display_name: str = ""

    @abc.abstractmethod
    def game_info(self) -> GameInfo:
        """返回该游戏的 GameInfo 注册信息。"""

    @abc.abstractmethod
    def validate_modpack(self, archive_path: str) -> bool:
        """校验整合包文件是否合法（结构、必要文件等）。返回 True 表示通过。"""

    def validate_mod(self, file_path: str) -> bool:
        """校验模组文件是否合法。默认实现仅检查文件存在且非空。"""
        import os

        return os.path.exists(file_path) and os.path.getsize(file_path) > 0

    @abc.abstractmethod
    def build_launch_command(
        self,
        install_dir: str,
        launch_config: LaunchConfig,
        modpack_meta: dict,
    ) -> list[str]:
        """根据安装目录、启动配置、整合包元数据生成启动命令（list[str] 形式）。"""

    def install_dir_hint(self, base_dir: str, modpack_meta: dict) -> str:
        """返回整合包安装目录建议路径。默认按 <base_dir>/<game>/<modpack_name> 组织。"""
        import os

        name = modpack_meta.get("name", "default")
        return os.path.join(base_dir, self.game_name, name)

    def supported_mod_loaders(self) -> list[str]:
        """返回该游戏支持的模组加载器列表。"""
        return []


class GameAdapterRegistry:
    """适配器注册中心，按 game_name 查找适配器实例。"""

    _adapters: dict[str, GameAdapter] = {}

    @classmethod
    def register(cls, adapter: GameAdapter) -> None:
        if not adapter.game_name:
            raise ValueError("Adapter must define game_name")
        cls._adapters[adapter.game_name] = adapter

    @classmethod
    def get(cls, game_name: str) -> Optional[GameAdapter]:
        return cls._adapters.get(game_name)

    @classmethod
    def require(cls, game_name: str) -> GameAdapter:
        adapter = cls._adapters.get(game_name)
        if adapter is None:
            from gpm_common.protocol import ErrorCode, GamePushError

            raise GamePushError(
                f"No adapter registered for game: {game_name}",
                code=ErrorCode.ADAPTER_NOT_FOUND,
                status_code=404,
            )
        return adapter

    @classmethod
    def all_games(cls) -> list[GameInfo]:
        return [a.game_info() for a in cls._adapters.values()]

    @classmethod
    def clear(cls) -> None:
        cls._adapters.clear()
