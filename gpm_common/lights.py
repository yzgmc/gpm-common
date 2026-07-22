"""状态指示灯系统：用绿/黄/红灯表示各端健康度。

灯色含义：
- GREEN  健康：一切正常
- YELLOW 降级：出现需关注的情况（磁盘占用高、近期有错误等），但仍可服务
- RED    异常：不可正常服务（磁盘将满、存储目录不可访问、错误率过高等）
- OFF    未知：未上报灯色（如客户端未实现灯系统，或刚启动尚无数据）

服务端通过 compute_server_light() 根据磁盘占用与错误计数计算自身灯色，
随 Heartbeat 上报给 web-admin；后台据此渲染彩色指示灯并聚合"总体系统灯"。
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class LightLevel:
    """灯色常量。使用字符串便于 JSON 序列化与前端匹配。"""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    OFF = "off"

    ALL = (GREEN, YELLOW, RED, OFF)

    @classmethod
    def priority(cls, level: str) -> int:
        """灯色严重度排序，数值越大越严重。用于聚合总体灯。"""
        order = {cls.GREEN: 0, cls.OFF: 1, cls.YELLOW: 2, cls.RED: 3}
        return order.get(level, 1)


class Light(BaseModel):
    """单次灯状态：灯色 + 原因 + 检查时间。"""

    level: str = Field(..., description="green / yellow / red / off")
    reason: str = Field(default="", description="当前灯色的人类可读原因")
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# 默认阈值（磁盘占用百分比）。可通过环境变量覆盖。
_DEFAULT_DISK_YELLOW = 85.0
_DEFAULT_DISK_RED = 95.0
_DEFAULT_ERROR_RED = 10  # 累计错误数达到该值即红灯


def compute_server_light(
    data_dir: str,
    error_count: int = 0,
    disk_yellow_pct: Optional[float] = None,
    disk_red_pct: Optional[float] = None,
    error_red: Optional[int] = None,
) -> Light:
    """根据服务端运行指标计算灯色。

    判定规则（按严重度从高到低，命中即返回）：
    1. 存储目录不可访问                  -> RED
    2. 磁盘占用 >= disk_red_pct          -> RED
    3. 累计错误数 >= error_red           -> RED
    4. 磁盘占用 >= disk_yellow_pct       -> YELLOW
    5. 其余                              -> GREEN
    """
    yellow = disk_yellow_pct if disk_yellow_pct is not None else float(
        os.getenv("GPM_LIGHT_DISK_YELLOW", _DEFAULT_DISK_YELLOW)
    )
    red = disk_red_pct if disk_red_pct is not None else float(
        os.getenv("GPM_LIGHT_DISK_RED", _DEFAULT_DISK_RED)
    )
    err_red = error_red if error_red is not None else int(
        os.getenv("GPM_LIGHT_ERROR_RED", _DEFAULT_ERROR_RED)
    )

    # 1. 存储目录检查
    if not os.path.isdir(data_dir):
        return Light(level=LightLevel.RED, reason=f"存储目录不可访问: {data_dir}")

    try:
        usage = shutil.disk_usage(data_dir)
    except OSError as exc:
        return Light(level=LightLevel.RED, reason=f"无法读取磁盘占用: {exc}")

    pct = (usage.used / usage.total * 100.0) if usage.total else 0.0
    free_gb = (usage.total - usage.used) / (1024 ** 3)

    # 2. 磁盘红色
    if pct >= red:
        return Light(
            level=LightLevel.RED,
            reason=f"磁盘占用 {pct:.1f}% >= {red:.0f}%（剩余 {free_gb:.1f} GB）",
        )
    # 3. 错误红色
    if error_count >= err_red:
        return Light(
            level=LightLevel.RED,
            reason=f"累计错误 {error_count} >= {err_red}",
        )
    # 4. 磁盘黄色
    if pct >= yellow:
        return Light(
            level=LightLevel.YELLOW,
            reason=f"磁盘占用 {pct:.1f}% >= {yellow:.0f}%（剩余 {free_gb:.1f} GB）",
        )
    # 5. 绿色
    return Light(
        level=LightLevel.GREEN,
        reason=f"运行正常，磁盘占用 {pct:.1f}%（剩余 {free_gb:.1f} GB）",
    )


def aggregate_light(levels: list[str]) -> str:
    """聚合多个灯色为总体系统灯：取最严重者。空列表返回 OFF。"""
    if not levels:
        return LightLevel.OFF
    return max(levels, key=LightLevel.priority)
