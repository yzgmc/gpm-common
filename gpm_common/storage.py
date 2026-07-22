"""文件存储路径工具，统一服务端存储目录组织方式。

存储目录结构：
    <storage_root>/
        modpacks/
            <modpack_id>/
                meta.json
                <file_name>
        mods/
            <mod_id>/
                meta.json
                <file_name>
"""

from __future__ import annotations

import os
from pathlib import Path


def build_storage_path(storage_root: str, kind: str, item_id: str, file_name: str) -> str:
    """构建存储文件路径。kind 为 'modpacks' 或 'mods'。"""
    safe_id = _sanitize(item_id)
    safe_name = _sanitize_filename(file_name)
    return os.path.join(storage_root, kind, safe_id, safe_name)


def build_meta_path(storage_root: str, kind: str, item_id: str) -> str:
    """构建元数据文件路径。"""
    safe_id = _sanitize(item_id)
    return os.path.join(storage_root, kind, safe_id, "meta.json")


def safe_join(base: str, *parts: str) -> str:
    """安全拼接路径，防止路径穿越（确保结果在 base 之内）。"""
    base_real = os.path.realpath(base)
    target = os.path.realpath(os.path.join(base, *parts))
    if not target.startswith(base_real + os.sep) and target != base_real:
        raise ValueError(f"Path traversal detected: {parts}")
    return target


def _sanitize(name: str) -> str:
    """清理 id，只保留字母数字与连字符。"""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def _sanitize_filename(name: str) -> str:
    """清理文件名，移除路径分隔符。"""
    name = os.path.basename(name)
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


def ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def dir_size(path: str) -> int:
    """递归计算目录总字节数。"""
    total = 0
    if not os.path.isdir(path):
        return 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                continue
    return total
