# gpm-common

Game Push Manager 共享库，提供所有端（server / web-server / web-admin / client）共用的数据模型、协议常量、游戏适配器接口与具体适配器实现。

## 设计目标

- **统一数据契约**：所有端使用相同的 Pydantic 模型，避免字段不一致。
- **可扩展游戏支持**：通过 `GameAdapter` 抽象基类注册新游戏，无需改动核心代码。当前已实现 `MinecraftAdapter`，后续添加其它游戏只需在 `gpm_common/adapters/` 下新增模块并在 `GameAdapterRegistry` 注册。
- **零业务依赖**：仅依赖 `pydantic`，可被任意 Python 端引用。

## 安装

```bash
pip install -e .
# 或者直接安装到项目虚拟环境
pip install -r requirements.txt && pip install -e .
```

## 模块说明

| 模块 | 作用 |
|------|------|
| `gpm_common.models` | Pydantic 数据模型：Modpack / Mod / GameInfo / StatusResponse 等 |
| `gpm_common.protocol` | API 路径常量、版本号、错误码 |
| `gpm_common.game_adapter` | `GameAdapter` 抽象基类与 `GameAdapterRegistry` 注册中心 |
| `gpm_common.adapters.minecraft` | Minecraft 适配器（整合包校验、启动命令生成） |
| `gpm_common.storage` | 文件存储路径、元数据 JSON 读写工具 |
| `gpm_common.hashing` | sha256 文件哈希工具 |

## 游戏适配器扩展

新增游戏只需两步：

```python
from gpm_common.game_adapter import GameAdapter, GameAdapterRegistry
from gpm_common.models import GameInfo, LaunchConfig

class MyGameAdapter(GameAdapter):
    game_name = "my_game"

    def validate_modpack(self, archive_path: str) -> bool: ...
    def build_launch_command(self, install_dir: str, config: LaunchConfig) -> list[str]: ...

GameAdapterRegistry.register(MyGameAdapter())
```

## 协议版本

当前协议版本：`1.0.0`（见 `gpm_common/protocol.py`）。所有端必须使用相同协议版本。
