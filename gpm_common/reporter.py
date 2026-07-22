"""Reporter：后台线程，定期向 web-admin 上报 Heartbeat。

所有端（windows-server / web-server / client）启动时创建一个 Reporter 实例并 start()，
关闭时 stop()。Reporter 通过传入的 `build_payload` 回调获取当前心跳数据，
POST 到 web-admin 的 /api/v1/report 接口。

上报失败不影响主业务，仅打印警告日志。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

import httpx

from gpm_common.heartbeat import Heartbeat


logger = logging.getLogger("gpm.reporter")


PayloadBuilder = Callable[[], Heartbeat]


class Reporter:
    """周期性上报心跳到 web-admin。"""

    def __init__(
        self,
        admin_url: str,
        build_payload: PayloadBuilder,
        interval: float = 10.0,
        timeout: float = 5.0,
    ) -> None:
        self.admin_url = admin_url.rstrip("/")
        self._build = build_payload
        self._interval = max(1.0, interval)
        self._timeout = timeout
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    @property
    def endpoint(self) -> str:
        return f"{self.admin_url}/api/v1/report"

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="gpm-reporter"
            )
            self._thread.start()
            logger.info("Reporter started -> %s every %.1fs", self.endpoint, self._interval)

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=2.0)
        self._thread = None

    def report_once(self) -> bool:
        """立刻上报一次。返回是否成功。"""
        try:
            payload = self._build()
        except Exception as exc:  # noqa: BLE001
            logger.warning("build heartbeat payload failed: %s", exc)
            return False
        try:
            with httpx.Client(timeout=self._timeout) as client:
                # model_dump(mode="json") 让 Pydantic 把 datetime 等转为可 JSON 序列化的字符串
                resp = client.post(self.endpoint, json=payload.model_dump(mode="json"))
                resp.raise_for_status()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("report to %s failed: %s", self.endpoint, exc)
            return False

    def _loop(self) -> None:
        # 启动时立即上报一次，便于 web-admin 快速发现
        self.report_once()
        while not self._stop.is_set():
            if self._stop.wait(self._interval):
                break
            self.report_once()
