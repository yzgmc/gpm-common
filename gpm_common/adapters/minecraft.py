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
import sys
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
        """根据版本 JSON 生成完整启动命令（支持 vanilla/fabric/forge/neoforge/quilt）。

        所有加载器安装后都遵循 Mojang 版本 JSON 规范：
        - versions/<version_id>/<version_id>.json 含 mainClass / libraries / arguments
        - 通过 inheritsFrom 继承原版 JSON
        正确启动方式：解析版本 JSON → 组装 classpath → 取 mainClass → 展开参数。

        找不到版本 JSON 时回退到旧的 -jar 方式（兼容未安装加载器的裸目录）。
        """
        java = launch_config.java_path or self._detect_java()
        loader = (modpack_meta.get("mod_loader") or "vanilla").lower()
        game_version = modpack_meta.get("game_version", "")
        loader_version = modpack_meta.get("mod_loader_version")

        # 1. 定位版本 JSON：优先用 modpack_meta["version_id"] 显式指定（版本管理器按版本启动），
        #    否则按加载器类型自动推断。
        version_id = ""
        explicit_vid = modpack_meta.get("version_id") or ""
        if explicit_vid and os.path.isfile(
            os.path.join(install_dir, "versions", explicit_vid, f"{explicit_vid}.json")
        ):
            version_id = explicit_vid
        if not version_id:
            version_id = self._resolve_version_id(install_dir, loader, game_version, loader_version)
        version_json = None
        if version_id:
            version_json = self._load_version_json(install_dir, version_id)

        # 2. 无版本 JSON → 回退旧逻辑（兼容裸目录/未完整安装）
        if not version_json:
            return self._legacy_launch_command(
                java, launch_config, loader, game_version, loader_version, install_dir
            )

        # 3. 合并 inheritsFrom 链（加载器 JSON 继承原版 JSON）
        merged = self._merge_inherited(install_dir, version_json)

        # 4. 组装 classpath（libraries + 主 jar）
        # 传入 game_version 与 version_json 的 inheritsFrom 链，确保原版 client jar 在 classpath
        classpath = self._build_classpath(install_dir, merged, game_version, version_json)

        # 5. 提取 natives（LWJGL 等 native 库到临时目录）
        natives_dir = self._extract_natives(install_dir, merged)

        # 6. 取 mainClass
        main_class = merged.get("mainClass") or "net.minecraft.client.main.Main"

        # 7. 组装命令
        cmd: list[str] = [java]
        cmd.extend(launch_config.jvm_args or ["-Xmx4G", "-Xms2G"])
        cmd.append(f"-Djava.library.path={natives_dir}")
        cmd.append("-cp")
        cmd.append(classpath)
        cmd.append(main_class)

        # 8. 游戏参数（从 arguments.game 或旧版 minecraftArguments 展开）
        # 正版账号信息由 LaunchConfig 透传：username/uuid/access_token 非空时用正版，
        # 否则回退离线模式（Player / 固定 UUID / 占位 token）
        game_args = self._expand_game_args(merged, install_dir, version_id, launch_config)
        cmd.extend(game_args)
        cmd.extend(launch_config.extra_args or [])
        return cmd

    # ---------- 版本 JSON 解析辅助 ----------

    @staticmethod
    def _resolve_version_id(
        install_dir: str, loader: str, game_version: str, loader_version: Optional[str]
    ) -> str:
        """根据加载器类型与目录实际内容推断 version_id。"""
        versions_dir = os.path.join(install_dir, "versions")
        if not os.path.isdir(versions_dir):
            return ""
        # 按加载器类型匹配版本目录名
        prefixes = {
            "fabric": ["fabric-loader"],
            "quilt": ["quilt-loader"],
            "forge": [f"{game_version}-forge", "forge"],
            "neoforge": [f"{game_version}-neoforge", "neoforge"],
            "vanilla": [game_version] if game_version else [],
        }
        candidates = prefixes.get(loader, [])
        # 优先精确匹配
        for prefix in candidates:
            if loader_version:
                target = f"{prefix}-{loader_version}" if not prefix.endswith(loader_version) else prefix
                if os.path.isfile(os.path.join(versions_dir, target, f"{target}.json")):
                    return target
            for name in os.listdir(versions_dir):
                if name.startswith(prefix) and os.path.isfile(
                    os.path.join(versions_dir, name, f"{name}.json")
                ):
                    return name
        # 兜底：取 versions 下任意一个含 .json 的目录
        for name in sorted(os.listdir(versions_dir)):
            if os.path.isfile(os.path.join(versions_dir, name, f"{name}.json")):
                return name
        return ""

    @staticmethod
    def _load_version_json(install_dir: str, version_id: str) -> Optional[dict]:
        """读取 versions/<id>/<id>.json。失败返回 None。"""
        import json

        path = os.path.join(install_dir, "versions", version_id, f"{version_id}.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def _merge_inherited(self, install_dir: str, version_json: dict) -> dict:
        """合并 inheritsFrom 链：子版本字段覆盖父版本。

        加载器版本 JSON 通常 inheritsFrom 原版版本 JSON，需递归合并
        libraries（追加）、arguments（追加）、assetIndex/mainClass（子覆盖）。
        """
        merged = {
            "mainClass": version_json.get("mainClass"),
            "assetIndex": version_json.get("assetIndex"),
            "libraries": list(version_json.get("libraries", [])),
            "arguments": {
                "game": list(version_json.get("arguments", {}).get("game", [])),
                "jvm": list(version_json.get("arguments", {}).get("jvm", [])),
            },
            "minecraftArguments": version_json.get("minecraftArguments", ""),
        }
        parent_id = version_json.get("inheritsFrom")
        if parent_id:
            parent = self._load_version_json(install_dir, parent_id)
            if parent:
                parent_merged = self._merge_inherited(install_dir, parent)
                # 父版本 libraries 在前，子版本追加在后
                merged["libraries"] = parent_merged["libraries"] + merged["libraries"]
                merged["arguments"]["game"] = parent_merged["arguments"]["game"] + merged["arguments"]["game"]
                merged["arguments"]["jvm"] = parent_merged["arguments"]["jvm"] + merged["arguments"]["jvm"]
                # 子版本未指定的字段用父版本兜底
                if not merged["mainClass"]:
                    merged["mainClass"] = parent_merged["mainClass"]
                if not merged["assetIndex"]:
                    merged["assetIndex"] = parent_merged["assetIndex"]
                if not merged["minecraftArguments"]:
                    merged["minecraftArguments"] = parent_merged["minecraftArguments"]
        return merged

    @staticmethod
    def _lib_path(install_dir: str, lib: dict) -> str:
        """把 library 的 name（group:artifact:version）转成 jar 路径。"""
        name = lib.get("name", "")
        parts = name.split(":")
        if len(parts) < 3:
            return ""
        group, artifact, version = parts[0], parts[1], parts[2]
        # group 的 . 转 /
        group_path = group.replace(".", "/")
        # 部分 library 有 classifier（如 natives-windows）：name 含第四段
        classifier = parts[3] if len(parts) > 3 else ""
        filename = f"{artifact}-{version}"
        if classifier:
            filename += f"-{classifier}"
        filename += ".jar"
        return os.path.join(install_dir, "libraries", group_path, artifact, version, filename)

    @staticmethod
    def _lib_allowed(lib: dict) -> bool:
        """按 rules 判断 library 是否适用于当前平台（Windows x64）。

        无 rules → 允许；有 rules 则所有 rule 的 action=allow 需满足。
        """
        import sys

        rules = lib.get("rules", [])
        if not rules:
            return True
        allowed = False
        for rule in rules:
            action = rule.get("action")
            os_rule = rule.get("os")
            if not os_rule:
                # 无 os 限制的规则：allow 直接允许，disallow 直接禁用
                if action == "allow":
                    allowed = True
                else:
                    return False
            else:
                # 检查 os 是否匹配（客户端在 Windows 运行）
                os_name = os_rule.get("name", "")
                if sys.platform == "win32" and os_name == "windows":
                    allowed = action == "allow"
                elif sys.platform.startswith("linux") and os_name == "linux":
                    allowed = action == "allow"
                elif sys.platform == "darwin" and os_name == "osx":
                    allowed = action == "allow"
        return allowed

    def _build_classpath(
        self, install_dir: str, merged: dict, game_version: str = "", version_json: Optional[dict] = None
    ) -> str:
        """从 merged libraries 组装 classpath 字符串（含原版 client jar）。

        原版 client jar 必须在 classpath 上，否则 Fabric/Quilt 的 game provider
        会报 "couldn't locate the game!"。

        查找顺序：
        1. version_json 的 inheritsFrom 链根版本 → versions/<root_id>/<root_id>.jar
        2. game_version → versions/<game_version>/<game_version>.jar
        3. 兜底：versions 下第一个含 .jar 的目录（优先无 - 后缀的）
        """
        sep = ";" if sys.platform == "win32" else ":"
        paths: list[str] = []
        for lib in merged.get("libraries", []):
            if not self._lib_allowed(lib):
                continue
            p = self._lib_path(install_dir, lib)
            if p and os.path.isfile(p):
                paths.append(p)

        # 主 jar：原版 client jar
        main_jar = self._find_vanilla_client_jar(install_dir, game_version, version_json)
        if main_jar:
            paths.append(main_jar)
        return sep.join(paths)

    def _find_vanilla_client_jar(
        self, install_dir: str, game_version: str, version_json: Optional[dict] = None
    ) -> str:
        """定位原版 client jar，返回绝对路径。找不到返回空串。

        1. 沿 inheritsFrom 链找根版本 → versions/<root_id>/<root_id>.jar
        2. game_version → versions/<game_version>/<game_version>.jar
        3. 兜底扫描 versions 目录
        """
        versions_dir = os.path.join(install_dir, "versions")

        # 1. 沿 inheritsFrom 链找根版本
        if version_json:
            root_id = self._find_inherits_root(install_dir, version_json)
            if root_id:
                jar = os.path.join(versions_dir, root_id, f"{root_id}.jar")
                if os.path.isfile(jar):
                    return jar

        # 2. 用 game_version 直接定位
        if game_version:
            jar = os.path.join(versions_dir, game_version, f"{game_version}.jar")
            if os.path.isfile(jar):
                return jar

        # 3. 兜底：扫描 versions 目录，优先无 - 后缀的（原版）
        if os.path.isdir(versions_dir):
            for name in sorted(os.listdir(versions_dir), key=lambda n: ("-" in n, len(n))):
                jar = os.path.join(versions_dir, name, f"{name}.jar")
                if os.path.isfile(jar):
                    return jar
        return ""

    def _find_inherits_root(self, install_dir: str, version_json: dict) -> str:
        """沿 inheritsFrom 链找根版本 id（没有 inheritsFrom 的那个）。"""
        seen: set[str] = set()
        current = version_json
        current_id = current.get("id", "")
        for _ in range(10):  # 防环
            parent_id = current.get("inheritsFrom")
            if not parent_id or parent_id in seen:
                return current_id or parent_id or ""
            seen.add(parent_id)
            parent = self._load_version_json(install_dir, parent_id)
            if not parent:
                return parent_id
            current = parent
            current_id = parent_id
        return current_id

    @staticmethod
    def _extract_natives(install_dir: str, merged: dict) -> str:
        """提取 native 库（LWJGL 等）到临时目录，返回路径。

        natives 字段在 library 里标记平台，需解压对应 jar 的 .dll/.so 到 natives 目录。
        无 native 库时返回 versions/<id>/<id>-natives 占位路径。
        """
        import sys
        import tempfile
        import zipfile

        # 固定 natives 目录（避免每次启动都解压）
        natives_dir = os.path.join(install_dir, "versions", "natives")
        os.makedirs(natives_dir, exist_ok=True)

        natives_ext = ".dll" if sys.platform == "win32" else (".so" if sys.platform.startswith("linux") else ".dylib")
        plat_key = "windows" if sys.platform == "win32" else ("linux" if sys.platform.startswith("linux") else "osx")

        for lib in merged.get("libraries", []):
            natives = lib.get("natives")
            if not natives:
                continue
            classifier = natives.get(plat_key)
            if not classifier:
                continue
            # 带 classifier 的 jar 路径
            name = lib.get("name", "")
            parts = name.split(":")
            if len(parts) < 3:
                continue
            group, artifact, version = parts[0], parts[1], parts[2]
            group_path = group.replace(".", "/")
            jar_name = f"{artifact}-{version}-{classifier}.jar"
            jar_path = os.path.join(install_dir, "libraries", group_path, artifact, version, jar_name)
            if not os.path.isfile(jar_path):
                continue
            # 解压 native 文件
            try:
                with zipfile.ZipFile(jar_path) as zf:
                    for member in zf.namelist():
                        # 只提取 native 文件，跳过 META-INF
                        if member.startswith("META-INF"):
                            continue
                        if member.endswith(natives_ext):
                            target = os.path.join(natives_dir, os.path.basename(member))
                            with open(target, "wb") as out:
                                out.write(zf.read(member))
            except (zipfile.BadZipFile, OSError):
                continue
        return natives_dir

    def _expand_game_args(
        self, merged: dict, install_dir: str, version_id: str, launch_config: "LaunchConfig"
    ) -> list[str]:
        """展开游戏参数：arguments.game（列表）或旧版 minecraftArguments（字符串）。

        账号信息取自 launch_config：
        - username/uuid/access_token 三者齐全 → 正版（msa）模式启动
        - 否则 → 离线模式（固定 Player 名 + uuid5 + 占位 token）
        """
        import uuid as _uuid

        if launch_config.username and launch_config.uuid and launch_config.access_token:
            # 微软正版账号
            player_name = launch_config.username
            player_uuid = launch_config.uuid
            access_token = launch_config.access_token
            user_type = "msa"
        else:
            # 离线模式：固定玩家名/UUID/Token（不依赖微软账号登录）
            player_name = "Player"
            player_uuid = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, player_name))
            access_token = "0"
            user_type = "offline"

        # 版本隔离：game_dir 由调用方指定（版本管理器隔离模式），None 时与 install_dir 共享。
        # saves/mods/config 落在 game_dir；libraries/assets 仍从 install_dir 解析（共享省磁盘）。
        game_dir = launch_config.game_dir or install_dir

        # 公共替换值
        replacements = {
            "${auth_player_name}": player_name,
            "${auth_uuid}": player_uuid,
            "${auth_access_token}": access_token,
            "${user_type}": user_type,
            "${version_name}": version_id,
            "${game_directory}": game_dir,
            "${assets_root}": os.path.join(install_dir, "assets"),
            "${assets_index_name}": str((merged.get("assetIndex") or {}).get("id", "")),
            "${version_type}": "release",
            "${user_properties}": "{}",
        }

        args: list[str] = []
        game_args = merged.get("arguments", {}).get("game", [])
        if game_args:
            for arg in game_args:
                if isinstance(arg, str):
                    args.append(self._apply_replacements(arg, replacements))
                elif isinstance(arg, dict):
                    # 带条件的参数，简化处理：符合条件则加入
                    rules = arg.get("rules", [])
                    value = arg.get("value", [])
                    if self._rules_pass(rules):
                        if isinstance(value, list):
                            for v in value:
                                args.append(self._apply_replacements(str(v), replacements))
                        else:
                            args.append(self._apply_replacements(str(value), replacements))
        else:
            # 旧版（1.12 及以下）：minecraftArguments 是空格分隔的字符串
            mc_args = merged.get("minecraftArguments", "")
            if mc_args:
                for a in mc_args.split():
                    args.append(self._apply_replacements(a, replacements))
        return args

    @staticmethod
    def _apply_replacements(s: str, replacements: dict) -> str:
        """对字符串应用所有占位符替换。"""
        for k, v in replacements.items():
            s = s.replace(k, v)
        return s

    @staticmethod
    def _rules_pass(rules: list) -> bool:
        """简化判断规则是否满足（Windows 平台优先）。"""
        import sys

        if not rules:
            return True
        for rule in rules:
            action = rule.get("action")
            os_rule = rule.get("os")
            if os_rule:
                os_name = os_rule.get("name", "")
                plat = "windows" if sys.platform == "win32" else ("linux" if sys.platform.startswith("linux") else "osx")
                if os_name != plat:
                    return False
            if action == "disallow":
                return False
        return True

    def _legacy_launch_command(
        self, java: str, launch_config: LaunchConfig,
        loader: str, game_version: str, loader_version: Optional[str],
        install_dir: str,
    ) -> list[str]:
        """无版本 JSON 时的回退启动命令（旧逻辑，兼容裸目录）。"""
        cmd: list[str] = [java]
        cmd.extend(launch_config.jvm_args or ["-Xmx4G", "-Xms2G"])
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
