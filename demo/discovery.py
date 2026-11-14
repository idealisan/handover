"""mDNS / Bonjour 设备发现（只浏览真实设备）。

真实 HandShaker 用 `_handshaker_ssp._tcp` 注册与浏览服务（doc/03 §2.3）。
安卓端 APK 会自行注册该服务；这里用 zeroconf 浏览局域网内的真实设备。

zeroconf 不可用或网络受限时自动降级：界面仍可用手动 IP:port 连接
（例如 adb forward 后的 127.0.0.1:10086）。
"""
from __future__ import annotations

import threading

SERVICE_TYPE = "_handshaker_ssp._tcp.local."


class Discovery:
    """zeroconf ServiceBrowser 的监听器，用于发现局域网内真实安卓端。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._services: dict[str, dict] = {}
        self._zc = None
        self._browser = None
        self.available = False
        self.error = ""

    def start(self) -> None:
        try:
            from zeroconf import ServiceBrowser, Zeroconf
            self._zc = Zeroconf()
            self._browser = ServiceBrowser(self._zc, SERVICE_TYPE, self)
            self.available = True
        except Exception as exc:  # 网络受限/权限不足时降级
            self.available = False
            self.error = str(exc)

    # ---- zeroconf ServiceBrowser listener 接口 ----
    def add_service(self, zc, type_, name):
        self._resolve(zc, type_, name)

    def update_service(self, zc, type_, name):
        self._resolve(zc, type_, name)

    def remove_service(self, zc, type_, name):
        with self._lock:
            self._services.pop(name, None)

    def _resolve(self, zc, type_, name):
        try:
            info = zc.get_service_info(type_, name, timeout=2000)
            if not info:
                return
            addrs = info.parsed_addresses()
            host = addrs[0] if addrs else "127.0.0.1"
            with self._lock:
                self._services[name] = {
                    "name": name.split(".")[0],
                    "host": host,
                    "port": info.port,
                    "source": "mdns",
                }
        except Exception:
            pass

    def services(self) -> list[dict]:
        with self._lock:
            return [dict(s) for s in self._services.values()]

    def stop(self) -> None:
        try:
            if self._zc is not None:
                self._zc.close()
        except Exception:
            pass
