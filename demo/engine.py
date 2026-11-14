"""演示引擎：把模拟手机、桌面客户端、发现层与 UI 状态串起来。

Web UI 只通过 snapshot() 读状态、通过 action() 下发动作，
不直接碰 socket，方便以后把 GUI 换成真正的原生窗口。
"""
from __future__ import annotations

import base64
import binascii
import os
import posixpath
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from .client import DesktopClient
from .discovery import Discovery, lan_ip
from .mock_phone import PhoneServer, VirtualPhone
from .protocol import SSP_REQUEST_TYPES

MAX_UPLOAD = 8 * 1024 * 1024


class Engine:
    def __init__(self, workdir: str | Path = "tmp/demo"):
        self.workdir = Path(workdir).resolve()
        self.downloads = self.workdir / "downloads"
        self.downloads.mkdir(parents=True, exist_ok=True)

        self.phone = VirtualPhone(self.workdir / "phone")
        self.server = PhoneServer(self.phone)
        self.client = DesktopClient(self.downloads, on_event=self._on_client_event)
        self.discovery = Discovery()

        self._current_path = "/"
        self._listing: dict = {"path": "/", "entries": []}
        self._clipboard: list = []
        self._events: deque = deque(maxlen=60)
        self._token = uuid.uuid4().hex[:8]
        self._lan_ip = lan_ip()
        self._qr: dict = {}
        self._started = False

    # ------------------------------------------------------------ 生命周期
    def start(self) -> None:
        self.server.start()
        self.discovery.start()
        self.discovery.register("Handover 模拟手机", self.server.port)
        self._qr = self._make_qr()
        self._started = True

    def stop(self) -> None:
        try:
            self.client.disconnect()
        except Exception:
            pass
        self.discovery.stop()
        self.server.stop()

    def _make_qr(self) -> dict:
        payload = (f"handover://{self._lan_ip}:{self.server.port}"
                   f"?p=1.0-demo&t={self._token}")
        try:
            import qrcode
            q = qrcode.QRCode(border=2)
            q.add_data(payload)
            q.make(fit=True)
            matrix = [[1 if v else 0 for v in row] for row in q.get_matrix()]
            return {"available": True, "payload": payload, "matrix": matrix}
        except Exception as exc:
            return {"available": False, "payload": payload, "matrix": [],
                    "error": str(exc)}

    # --------------------------------------------------------------- 事件
    def _on_client_event(self, cmd: str, data: dict) -> None:
        self._events.appendleft({
            "ts": time.strftime("%H:%M:%S"),
            "cmd": cmd,
            "brief": str(data or {})[:160],
        })
        # 注意：这里在客户端读线程里，绝不能发起新的 _request，否则会自锁。
        # 界面层在做完写操作后会显式调用 list_dir 刷新。

    # --------------------------------------------------------------- 设备
    def devices(self) -> list[dict]:
        out = [{
            "id": "builtin",
            "name": "内置模拟手机",
            "host": "127.0.0.1",
            "port": self.server.port,
            "source": "builtin",
        }]
        for i, s in enumerate(self.discovery.services()):
            out.append({
                "id": f"mdns-{i}",
                "name": s["name"],
                "host": s["host"],
                "port": s["port"],
                "source": "mdns",
            })
        return out

    # --------------------------------------------------------------- 动作
    def action(self, cmd: str, args: dict | None = None) -> dict:
        args = args or {}
        handler = getattr(self, "_act_" + cmd, None)
        if handler is None:
            raise ValueError(f"未知动作: {cmd}")
        return handler(args)

    def _act_connect(self, a: dict) -> dict:
        host = str(a.get("host", "127.0.0.1"))
        port = int(a.get("port", self.server.port))
        hello = self.client.connect(host, port)
        return {"hello": hello, "stage": self.client.snapshot()["stage"]}

    def _act_pair(self, a: dict) -> dict:
        trust = str(a.get("trust", "ONCE"))
        if trust not in ("ONCE", "ALWAYS", "NO"):
            trust = "NO"
        res = self.client.pair(trust)
        if res.get("stage") == "paired":
            self._refresh()
        return res

    def _act_disconnect(self, a: dict) -> dict:
        self.client.disconnect()
        self._listing = {"path": "/", "entries": []}
        self._clipboard = []
        return {"ok": True}

    def _act_list_dir(self, a: dict) -> dict:
        path = str(a.get("path", "/"))
        self._current_path = path
        if self.client.snapshot()["stage"] == "paired":
            self._listing = self.client.list_dir(path)
        return {"listing": self._listing}

    def _refresh(self) -> None:
        if self.client.snapshot()["stage"] != "paired":
            return
        self._listing = self.client.list_dir(self._current_path)
        self._clipboard = self.client.get_clipboard()

    def _act_mkdir(self, a: dict) -> dict:
        name = os.path.basename(str(a.get("name", "")))
        self.client.mkdir(self._current_path, name)
        self._refresh()
        return {"ok": True}

    def _act_rename(self, a: dict) -> dict:
        new_name = os.path.basename(str(a.get("new_name", "")))
        self.client.rename(str(a.get("path", "")), new_name)
        self._refresh()
        return {"ok": True}

    def _act_delete(self, a: dict) -> dict:
        paths = [str(p) for p in a.get("paths", [])]
        if paths:
            self.client.delete(paths)
            self._refresh()
        return {"ok": True}

    def _act_upload(self, a: dict) -> dict:
        name = os.path.basename(str(a.get("name", "")))
        if not name or name in (".", ".."):
            raise ValueError("文件名不合法")
        raw = str(a.get("content_b64", ""))
        try:
            data = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"文件内容解码失败: {exc}")
        if len(data) > MAX_UPLOAD:
            raise ValueError("演示限制：单文件不超过 8 MB")
        remote = posixpath.join(self._current_path, name)
        sid = self.client.upload(remote, data)
        self._refresh()
        return {"session_id": sid, "path": remote, "size": len(data)}

    def _act_download(self, a: dict) -> dict:
        sid = self.client.download(str(a.get("path", "")))
        return {"session_id": sid}

    def _act_cancel(self, a: dict) -> dict:
        self.client.cancel(int(a.get("session_id", 0)))
        return {"ok": True}

    def _act_clipboard_post(self, a: dict) -> dict:
        self.client.post_clipboard(str(a.get("text", "")))
        self._clipboard = self.client.get_clipboard()
        return {"ok": True}

    def _act_clipboard_clear(self, a: dict) -> dict:
        self.client.clear_clipboard()
        self._clipboard = self.client.get_clipboard()
        return {"ok": True}

    def _act_set_locked(self, a: dict) -> dict:
        self.server.set_locked(bool(a.get("locked", False)))
        return {"ok": True}

    def _act_reseed(self, a: dict) -> dict:
        """补回示例文件（不删除任何已有文件）。"""
        self.phone._seed()  # noqa: SLF001 - demo 内部播种
        return {"ok": True}

    # ------------------------------------------------------------- 快照
    def snapshot(self) -> dict:
        cs = self.client.snapshot()
        return {
            "connection": {
                "stage": cs["stage"],
                "device": cs["device"],
                "device_info": cs["device_info"],
                "protocol_version": cs["protocol_version"],
                "trust": cs["trust"],
                "last_error": cs["last_error"],
                "last_heartbeat": cs["last_heartbeat"],
            },
            "devices": self.devices(),
            "listing": self._listing,
            "current_path": self._current_path,
            "clipboard": self._clipboard,
            "transfers": cs["transfers"],
            "log": cs["log"],
            "events": list(self._events),
            "qr": self._qr,
            "phone": {"locked": self.phone.locked, "port": self.server.port},
            "capabilities": {
                "zeroconf": self.discovery.available,
                "zeroconf_error": self.discovery.error,
                "qrcode": bool(self._qr.get("available")),
            },
            "versions": {
                "app": "0.1.0",
                "protocol": "1.0-demo",
                "min_client": "0.1.0",
            },
            "ssp_request_types": list(SSP_REQUEST_TYPES),
        }
