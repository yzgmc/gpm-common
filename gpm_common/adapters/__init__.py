"""游戏适配器集合。导入此包时自动注册所有内置适配器。"""

from gpm_common.adapters.minecraft import MinecraftAdapter
from gpm_common.game_adapter import GameAdapterRegistry


def register_builtin_adapters() -> None:
    """注册所有内置适配器。可在服务端/客户端启动时调用。"""
    GameAdapterRegistry.register(MinecraftAdapter())


# 导入即注册，方便使用方只需 `import gpm_common` 即可使用所有适配器
register_builtin_adapters()

__all__ = ["MinecraftAdapter", "register_builtin_adapters"]
