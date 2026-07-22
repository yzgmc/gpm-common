"""文件哈希工具。统一使用 sha256。"""

from __future__ import annotations

import hashlib
from pathlib import Path


def compute_sha256(file_path: str, chunk_size: int = 1 << 20) -> str:
    """计算文件 sha256，按 1MB 块读取以支持大文件。"""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_bytes_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_file(file_path: str, expected_hash: str) -> bool:
    """校验文件 sha256 是否匹配。"""
    if not Path(file_path).exists():
        return False
    return compute_sha256(file_path) == expected_hash.lower()
