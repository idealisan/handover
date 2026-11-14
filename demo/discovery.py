"""mDNS / Bonjour 设备发现。

真实 HandShaker 用 `_handshaker_ssp._tcp` 注册与浏览服务（doc/03 §2.3）。
这里用 zeroconf 复现同样的机制：demo 会把内置模拟手机注册成一个服务，
同时浏览局域网内其它同类服务（将来真实安卓端上线时会自动出现在列表里）。

zeroconf 不可用或网络受限时自动降级：界面仍可用「内置模拟设备」和手动 IP:port。
"""
from __future__ import annotations

import socket
import threading

SERVICE_TYPE = "_handshaker_ssp._tcp.local."


def lan_ip() -> str:
    """取本机局域网 IPv4，仅用于展示二维码内容；失败则回落到回环地址。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"


class Discovery:
    """zeroconf ServiceBrowser 的监听器，同时负责注册内置模拟设备。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._services: dict[str, dict] = {}
        self._zc = None
        self._browser = None
        self._registered = None
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

    def register(self, name: str, port: int, host: str = "127.0.0.1") -> None:
        if self._zc is None:
            return
        try:
            from zeroconf import ServiceInfo
            info = ServiceInfo(
                SERVICE_TYPE,
                f"{name}.{SERVICE_TYPE}",
                addresses=[socket.inet_aton(host)],
                port=int(port),
                properties={"p": "1.0-demo", "demo": "1"},
            )
            self._zc.register_service(info)
            self._registered = info
        except Exception as exc:
            self.error = f"注册失败: {exc}"

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
            if self._registered is not None and self._zc is not None:
                self._zc.unregister_service(self._registered)
            if self._zc is not None:
                self._zc.close()
        except Exception:
            pass
