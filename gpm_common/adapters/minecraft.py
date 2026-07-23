"""Minecraft 适配器。

整合包校验规则（兼容 CurseForge / Modrinth 导出格式的最小子集）：
- 文件为 zip 压缩包
- 包含 overrides/ 目录 或 manifest.json（CurseForge 风格）或 modrinth.index.json（Modrinth 风格）
  若都不包含也允许，但视为"裸 mods 整合包"，仅解压到 .minecraft/mods

启动命令生成：
- 优先使用 modpack_meta.mod_loader + mod_loader_version 信息
- vanilla：java -jar <minecraft_jar> （需要客户端已下载对应版本）
- forge：java -jar <forge_installer> --launchClient （简化版，实际项目可接入官方启动器库）
- fabric：java -jar <fabric-loader-jar> --gameDir <dir> --gameJar <jar>

注：完整版本清单下载、libraries、assets 校验等已超出本 Demo 范围，
此处给出可扩展的接口与最小可行实现，后续可逐步增强。
"""

from __future__ import annotations

import os
import zipfile
from typing import Optional

from gpm_common.game_adapter import GameAdapter
from gpm_common.models import GameInfo, LaunchConfig


class MinecraftAdapter(GameAdapter):
    game_name = "minecraft"
    display_name = "Minecraft"

    def game_info(self) -> GameInfo:
        return GameInfo(
            name=self.game_name,
            display_name=self.display_name,
            adapter=self.__class__.__name__,
            enabled=True,
        )

    def validate_modpack(self, archive_path: str) -> bool:
        if not os.path.exists(archive_path):
            return False
        if not zipfile.is_zipfile(archive_path):
            return False
        try:
            with zipfile.ZipFile(archive_path) as zf:
                names = zf.namelist()
        except zipfile.BadZipFile:
            return False
        # 兼容三种格式：CurseForge manifest.json / Modrinth modrinth.index.json / 裸整合包
        has_manifest = any(
            n in names
            for n in ("manifest.json", "modrinth.index.json", "./manifest.json", "./modrinth.index.json")
        )
        has_overrides = any(n.startswith("overrides/") or n.startswith("./overrides/") for n in names)
        has_jar = any(n.endswith(".jar") for n in names)
        return has_manifest or has_overrides or has_jar

    def detect_metadata(self, archive_path: str) -> Optional[dict]:
        """解析整合包内 manifest.json（CurseForge）或 modrinth.index.json（Modrinth），
        自动识别游戏版本、模组加载器及版本。裸整合包返回 None。

        CurseForge manifest.json 示例:
          {"minecraft": {"version": "1.20.1",
                         "modLoaders": [{"id": "fabric-loader-0.15.7", "primary": true}]}}
        Modrinth modrinth.index.json 示例:
          {"dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.7", "forge": "47.2.0"}}
        """
        import json

        if not os.path.exists(archive_path) or not zipfile.is_zipfile(archive_path):
            return None
        result: dict = {}
        try:
            with zipfile.ZipFile(archive_path) as zf:
                names = zf.namelist()
                # CurseForge 风格
                manifest_name = next(
                    (n for n in ("manifest.json", "./manifest.json") if n in names), None
                )
                if manifest_name:
                    try:
                        data = json.loads(zf.read(manifest_name).decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        data = {}
                    mc = data.get("minecraft", {}) or {}
                    if mc.get("version"):
                        result["game_version"] = str(mc["version"])
                    # modLoaders: [{"id": "fabric-loader-0.15.7", "primary": true}]
                    loaders = mc.get("modLoaders") or []
                    primary = next((l for l in loaders if l.get("primary")), None)
                    if primary is None and loaders:
                        primary = loaders[0]
                    if primary and primary.get("id"):
                        loader, ver = self._parse_cf_loader_id(str(primary["id"]))
                        if loader:
                            result["mod_loader"] = loader
                        if ver:
                            result["mod_loader_version"] = ver
                    if result:
                        return result
                # Modrinth 风格
                modrinth_name = next(
                    (n for n in ("modrinth.index.json", "./modrinth.index.json") if n in names), None
                )
                if modrinth_name:
                    try:
                        data = json.loads(zf.read(modrinth_name).decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        data = {}
                    deps = data.get("dependencies", {}) or {}
                    if deps.get("minecraft"):
                        result["game_version"] = str(deps["minecraft"])
                    # 依赖键名：fabric-loader / forge / quilt-loader
                    for key, loader in (
                        ("fabric-loader", "fabric"),
                        ("fabric", "fabric"),
                        ("forge", "forge"),
                        ("quilt-loader", "quilt"),
                        ("quilt", "quilt"),
                    ):
                        if deps.get(key):
                            result["mod_loader"] = loader
                            result["mod_loader_version"] = str(deps[key])
                            break
                    if result:
                        return result
        except (zipfile.BadZipFile, KeyError, OSError):
            return None
        return result or None

    @staticmethod
    def _parse_cf_loader_id(loader_id: str) -> tuple[str, str]:
        """解析 CurseForge modLoader id，如 'fabric-loader-0.15.7' -> ('fabric', '0.15.7')。

        id 格式：<loader>-<version>，loader 取已知前缀（fabric-loader/forge/quilt-loader）。
        """
        lid = loader_id.lower().strip()
        # 已知的加载器前缀，需按"更长的前缀"优先匹配，避免 fabric-loader 误匹配成 fabric
        for prefix, loader in (
            ("fabric-loader-", "fabric"),
            ("quilt-loader-", "quilt"),
            ("fabric-loader", "fabric"),
            ("quilt-loader", "quilt"),
            ("forge-", "forge"),
            ("forge", "forge"),
        ):
            if lid.startswith(prefix):
                ver = lid[len(prefix):].strip("-")
                return loader, ver
        # 兜底：取第一个 '-' 之前为 loader
        if "-" in lid:
            head, ver = lid.split("-", 1)
            return head, ver
        return lid, ""

    def validate_mod(self, file_path: str) -> bool:
        if not super().validate_mod(file_path):
            return False
        return file_path.lower().endswith(".jar")

    def supported_mod_loaders(self) -> list[str]:
        return ["vanilla", "forge", "fabric", "quilt"]

    def build_launch_command(
        self,
        install_dir: str,
        launch_config: LaunchConfig,
        modpack_meta: dict,
    ) -> list[str]:
        java = launch_config.java_path or self._detect_java()
        loader = (modpack_meta.get("mod_loader") or "vanilla").lower()
        game_version = modpack_meta.get("game_version", "")
        loader_version = modpack_meta.get("mod_loader_version")

        cmd: list[str] = [java]
        cmd.extend(launch_config.jvm_args or ["-Xmx4G", "-Xms1G"])

        if loader == "vanilla":
            jar = os.path.join(install_dir, f"minecraft_server.{game_version}.jar")
            cmd += ["-jar", jar, "--gameDir", install_dir]
        elif loader == "forge":
            forge_jar = self._find_forge_jar(install_dir, game_version, loader_version)
            cmd += ["-jar", forge_jar, "--gameDir", install_dir]
        elif loader in ("fabric", "quilt"):
            loader_jar = self._find_fabric_loader_jar(install_dir, loader)
            cmd += ["-jar", loader_jar, "--gameDir", install_dir, "--gameVersion", game_version]
        else:
            raise ValueError(f"Unsupported mod loader: {loader}")

        cmd.extend(launch_config.extra_args or [])
        return cmd

    def _detect_java(self) -> str:
        # Windows 优先 java.exe，否则 java
        for candidate in ("java.exe", "javaw.exe", "java"):
            path = self._which(candidate)
            if path:
                return path
        return "java"

    @staticmethod
    def _which(name: str) -> Optional[str]:
        from shutil import which

        return which(name)

    @staticmethod
    def _find_forge_jar(install_dir: str, game_version: str, loader_version: Optional[str]) -> str:
        # 在 install_dir 下查找 forge-<mcver>-<forgever>-universal.jar 或类似命名
        if not os.path.isdir(install_dir):
            raise FileNotFoundError(f"Install dir not found: {install_dir}")
        candidates = []
        for fn in os.listdir(install_dir):
            low = fn.lower()
            if low.endswith(".jar") and "forge" in low and game_version in fn:
                if loader_version and loader_version in fn:
                    return os.path.join(install_dir, fn)
                candidates.append(os.path.join(install_dir, fn))
        if candidates:
            return candidates[0]
        raise FileNotFoundError(
            f"Forge jar not found in {install_dir} for MC {game_version} / forge {loader_version}"
        )

    @staticmethod
    def _find_fabric_loader_jar(install_dir: str, loader: str) -> str:
        if not os.path.isdir(install_dir):
            raise FileNotFoundError(f"Install dir not found: {install_dir}")
        keyword = "fabric" if loader == "fabric" else "quilt"
        for fn in os.listdir(install_dir):
            low = fn.lower()
            if low.endswith(".jar") and keyword in low and "loader" in low:
                return os.path.join(install_dir, fn)
        raise FileNotFoundError(f"{loader} loader jar not found in {install_dir}")
