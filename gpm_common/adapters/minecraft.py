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
import re
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
                    # 依赖键名：fabric-loader / forge / quilt-loader / neoforge
                    for key, loader in (
                        ("fabric-loader", "fabric"),
                        ("fabric", "fabric"),
                        ("quilt-loader", "quilt"),
                        ("quilt", "quilt"),
                        ("neoforge", "neoforge"),
                        ("forge", "forge"),
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

        id 格式：<loader>-<version>，loader 取已知前缀（fabric-loader/forge/quilt-loader/neoforge）。
        """
        lid = loader_id.lower().strip()
        # 已知的加载器前缀，需按"更长的前缀"优先匹配，避免 neoforge 被误匹配成 forge
        for prefix, loader in (
            ("fabric-loader-", "fabric"),
            ("quilt-loader-", "quilt"),
            ("fabric-loader", "fabric"),
            ("quilt-loader", "quilt"),
            ("neoforge-", "neoforge"),
            ("neoforge", "neoforge"),
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

    def detect_mod_metadata(self, jar_path: str) -> Optional[dict]:
        """从单个模组 jar 自动识别游戏版本、模组加载器及版本。

        模组 jar 本质是 zip，按优先级解析内部元数据：
        1. fabric.mod.json（Fabric）：depends.fabric / depends.minecraft
        2. META-INF/neoforge.mods.toml（NeoForge）：loaderVersion / minecraft range
        3. META-INF/mods.toml（Forge 1.13+）：loaderVersion / minecraft range
        4. mcmod.info（Forge 1.12-）：mcversion
        5. quilt.mod.json（Quilt）：quilt_loader / minecraft

        返回 dict（如 {"game_version": "1.20.1", "mod_loader": "fabric", "mod_loader_version": "0.15.7"}）
        或 None。识别失败不抛异常。
        """
        import json

        if not os.path.exists(jar_path) or not zipfile.is_zipfile(jar_path):
            return None
        result: dict = {}
        try:
            with zipfile.ZipFile(jar_path) as zf:
                names = zf.namelist()

                # 1. Fabric: fabric.mod.json（通常在 jar 根目录）
                fab_name = next(
                    (n for n in names if n.endswith("fabric.mod.json")), None
                )
                if fab_name:
                    try:
                        data = json.loads(zf.read(fab_name).decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        data = {}
                    depends = data.get("depends", {}) or {}
                    if depends.get("fabric") or depends.get("fabric-loader"):
                        result["mod_loader"] = "fabric"
                        # fabric 依赖值可能是字符串范围如 ">=0.15.0" 或精确版本
                        fab_ver = depends.get("fabric") or depends.get("fabric-loader")
                        ver = self._extract_version(str(fab_ver))
                        if ver:
                            result["mod_loader_version"] = ver
                    if depends.get("minecraft"):
                        gv = self._extract_version(str(depends["minecraft"]))
                        if gv:
                            result["game_version"] = gv
                    if result:
                        return result

                # 2. Quilt: quilt.mod.json
                quilt_name = next(
                    (n for n in names if n.endswith("quilt.mod.json")), None
                )
                if quilt_name:
                    try:
                        data = json.loads(zf.read(quilt_name).decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        data = {}
                    ql = (data.get("quilt_loader") or {}).get("depends", {}) or {}
                    if ql.get("quilt_loader") or ql.get("quilt-base"):
                        result["mod_loader"] = "quilt"
                        qv = ql.get("quilt_loader") or ql.get("quilt-base")
                        ver = self._extract_version(str(qv))
                        if ver:
                            result["mod_loader_version"] = ver
                    if ql.get("minecraft"):
                        gv = self._extract_version(str(ql["minecraft"]))
                        if gv:
                            result["game_version"] = gv
                    if result:
                        return result

                # 3. NeoForge: META-INF/neoforge.mods.toml（格式同 mods.toml）
                #    Forge 1.13+: META-INF/mods.toml
                # NeoForge 优先匹配，避免误判为 forge；两者 mods.toml 格式一致，统一解析
                toml_name = next(
                    (n for n in names if n == "META-INF/neoforge.mods.toml"), None
                ) or next(
                    (n for n in names if n == "META-INF/mods.toml"), None
                )
                if toml_name:
                    loader = "neoforge" if "neoforge" in toml_name else "forge"
                    try:
                        raw = zf.read(toml_name).decode("utf-8")
                    except UnicodeDecodeError:
                        raw = ""
                    # 简易解析：找 loaderVersion
                    lv = re.search(r'loaderVersion\s*=\s*\[?\s*"([^"]+)"', raw)
                    if lv:
                        result["mod_loader"] = loader
                        ver = self._extract_version(lv.group(1))
                        if ver:
                            result["mod_loader_version"] = ver
                    # minecraft 游戏版本：两种 mods.toml 写法
                    # a) 依赖块格式：[[dependencies.xxx]] modId="minecraft" ... range="[1.18.2,1.19)"
                    # b) 内联格式：minecraft = { range = "[...]" }
                    mc_range = None
                    dep_block = re.search(
                        r'modId\s*=\s*"minecraft"[^]]*?range\s*=\s*"([^"]+)"',
                        raw, re.IGNORECASE | re.DOTALL,
                    )
                    if dep_block:
                        mc_range = dep_block.group(1)
                    else:
                        inline = re.search(
                            r'minecraft\s*=\s*\{[^}]*?range\s*=\s*"([^"]+)"',
                            raw, re.IGNORECASE,
                        )
                        if inline:
                            mc_range = inline.group(1)
                    if mc_range:
                        gv = self._extract_version(mc_range)
                        if gv:
                            result["game_version"] = gv
                    if result:
                        return result

                # 4. Forge 1.12-: mcmod.info
                info_name = next(
                    (n for n in names if n == "mcmod.info"), None
                )
                if info_name:
                    try:
                        data = json.loads(zf.read(info_name).decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        data = []
                    if isinstance(data, list) and data:
                        item = data[0] if isinstance(data[0], dict) else {}
                    elif isinstance(data, dict):
                        item = data.get("modList", [{}])
                        item = item[0] if item else {}
                    else:
                        item = {}
                    if item.get("mcversion"):
                        result["game_version"] = str(item["mcversion"])
                        result["mod_loader"] = "forge"
                    if result:
                        return result
        except (zipfile.BadZipFile, KeyError, OSError):
            return None
        return result or None

    @staticmethod
    def _extract_version(value: str) -> str:
        """从依赖范围字符串中提取版本号。

        Fabric/Forge 依赖值常见格式：
        - 精确版本："0.15.7"
        - 范围：">=0.15.0"、"[1.20,1.21)"、"(,1.20.1]"、"[1.19,)"
        取范围中出现的第一个版本号字符串；无版本号则返回原值去除范围符号。
        """
        if not value:
            return ""
        # 优先匹配形如 1.20.1 / 0.15.7 的版本号
        m = re.search(r"\d+\.\d+(?:\.\d+)?", value)
        if m:
            return m.group(0)
        # 兜底：去除范围符号
        return re.sub(r"[()\[\],>=<~ ]", "", value).strip()

    def validate_mod(self, file_path: str) -> bool:
        if not super().validate_mod(file_path):
            return False
        return file_path.lower().endswith(".jar")

    def supported_mod_loaders(self) -> list[str]:
        return ["vanilla", "forge", "neoforge", "fabric", "quilt"]

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
        elif loader == "neoforge":
            neo_jar = self._find_neoforge_jar(install_dir, loader_version)
            cmd += ["-jar", neo_jar, "--gameDir", install_dir]
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
    def _find_neoforge_jar(install_dir: str, loader_version: Optional[str]) -> str:
        # 在 install_dir 下查找 neoforge-<ver>-universal.jar 或类似命名
        if not os.path.isdir(install_dir):
            raise FileNotFoundError(f"Install dir not found: {install_dir}")
        candidates = []
        for fn in os.listdir(install_dir):
            low = fn.lower()
            if low.endswith(".jar") and "neoforge" in low:
                if loader_version and loader_version in fn:
                    return os.path.join(install_dir, fn)
                candidates.append(os.path.join(install_dir, fn))
        if candidates:
            return candidates[0]
        raise FileNotFoundError(
            f"NeoForge jar not found in {install_dir} / neoforge {loader_version}"
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
