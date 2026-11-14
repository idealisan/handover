"""桌面客户端：对应 HandShaker 的 macOS 端。

实现 doc/03 里的两轮握手、信任、心跳保活、请求-响应、以及
「session_id + 裸二进制」的分块传输与取消。
"""
from __future__ import annotations

import hashlib
import itertools
import os
import socket
import threading
import time
from collections import deque
from pathlib import Path

from .protocol import FrameConnection

APP_VERSION = "0.1.0"
PROTOCOL_VERSION = "1.0-demo"
MIN_CLIENT_VERSION = "0.1.0"
HOST_NAME = "Handover Demo (macOS)"
HOST_MODEL = "VirtualMac"
HEARTBEAT_INTERVAL = 3
HEARTBEAT_TIMEOUT_SECOND = 10
CHUNK = 64 * 1024


class DesktopClient:
    def __init__(self, downloads_dir: str | Path, on_event=None,
                 host_uuid: str = "SIM-MAC-0001"):
        self.downloads_dir = Path(downloads_dir).resolve()
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.on_event = on_event or (lambda *a: None)
        self.host_uuid = host_uuid

        self._seq = itertools.count(1)
        self._session_ids = itertools.count(1000)
        self._pending: dict[int, dict] = {}
        self._pending_lock = threading.Lock()
        self._lock = threading.RLock()

        self._conn: FrameConnection | None = None
        self._stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._transfers: dict[int, dict] = {}
        self._sinks: dict[int, bytearray] = {}
        self._cancelled: set[int] = set()
        self._log: deque = deque(maxlen=300)

        self._stage = "disconnected"     # disconnected/connected/need_trust/paired/rejected/locked/dead
        self._device: dict = {}
        self._device_info: dict = {}
        self._trust: str | None = None
        self._protocol_version: str = ""
        self._last_heartbeat = 0.0
        self._last_error = ""

    # ------------------------------------------------------------------ 连接
    def connect(self, host: str, port: int) -> dict:
        self.disconnect()
        sock = socket.create_connection((host, int(port)), timeout=5)
        sock.settimeout(None)
        self._stop = threading.Event()
        self._conn = FrameConnection(sock, self._on_control, self._on_data,
                                     self._on_close, label="desktop")
        self._stage = "connected"
        self._log_add("→", "CONNECT", {"host": host, "port": port})
        return self.hello()

    def hello(self) -> dict:
        """第 1 轮握手：交换 uuid / 版本 / 心跳超时（对应 SSPHandShakeRequest01）。"""
        data = self._request("HELLO", {
            "host_uuid": self.host_uuid,
            "host_name": HOST_NAME,
            "host_model": HOST_MODEL,
            "host_timestamp": int(time.time()),
            "protocol_version": PROTOCOL_VERSION,
            "app_version": APP_VERSION,
            "min_client_version": MIN_CLIENT_VERSION,
            "heartbeat_timeout_second": HEARTBEAT_TIMEOUT_SECOND,
        })
        self._device = data
        self._protocol_version = str(data.get("client_protocol_version", ""))
        if self._protocol_version and self._protocol_version != PROTOCOL_VERSION:
            self._last_error = f"协议版本不一致: {self._protocol_version}"
            self._stage = "dead"
            return self.snapshot()
        self._stage = "need_trust"
        return data

    def pair(self, trust: str) -> dict:
        """第 2 轮握手：信任确认（对应 SSPHandShakeRequest02/Response02）。"""
        data = self._request("PAIR_REQUEST", {"trust": trust})
        result = str(data.get("result", "failed"))
        self._trust = trust
        if result == "ok":
            self._stage = "paired"
            self._start_heartbeat()
            try:
                self._device_info = self._request("GET_DEVICE_INFO")
            except Exception as exc:
                self._last_error = str(exc)
        elif result == "locked":
            self._stage = "locked"
        elif result == "needauth":
            self._stage = "rejected"
        else:
            self._stage = "rejected"
        return {"result": result, "stage": self._stage}

    def disconnect(self) -> None:
        self._stop.set()
        if self._conn:
            try:
                self._conn.send_control("QUIT")
            except Exception:
                pass
            self._conn.close()
            self._conn = None
        self._stage = "disconnected"
        self._trust = None
        self._device_info = {}
        self._log_add("→", "DISCONNECT", {})

    # ------------------------------------------------------------- 请求-响应
    def _request(self, cmd: str, data: dict | None = None, *,
                 timeout: float = 10, sid: int = 0) -> dict:
        if not self._conn or self._conn.closed:
            raise RuntimeError("未连接")
        seq = next(self._seq)
        event = threading.Event()
        with self._pending_lock:
            self._pending[seq] = {"event": event, "response": None}
        self._log_add("→", cmd, data)
        self._conn.send_control(cmd, seq=seq, session_id=sid, data=data or {})
        if not event.wait(timeout):
            with self._pending_lock:
                self._pending.pop(seq, None)
            raise TimeoutError(f"{cmd} 超时")
        with self._pending_lock:
            resp = self._pending.pop(seq, {}).get("response")
        if not resp:
            raise RuntimeError(f"{cmd} 无响应")
        if not resp.get("ok", True):
            raise RuntimeError(resp.get("error") or f"{cmd} 失败")
        return resp.get("data") or {}

    # --------------------------------------------------------------- 业务 API
    def list_dir(self, path: str = "/") -> dict:
        return self._request("LIST_DIR", {"path": path})

    def mkdir(self, path: str, name: str) -> dict:
        return self._request("MKDIR", {"path": path, "name": name})

    def rename(self, path: str, new_name: str) -> dict:
        return self._request("RENAME", {"path": path, "new_name": new_name})

    def delete(self, paths: list[str]) -> dict:
        return self._request("DELETE", {"paths": paths})

    def get_clipboard(self) -> list:
        return list(self._request("GET_CLIPBOARD").get("items", []))

    def post_clipboard(self, text: str) -> dict:
        return self._request("POST_CLIPBOARD", {"text": text})

    def clear_clipboard(self) -> dict:
        return self._request("CLEAR_CLIPBOARD")

    def upload(self, remote_path: str, data: bytes) -> int:
        """上传：UPLOAD_INIT → 若干 DATA 帧 → UPLOAD_DONE（MD5 校验）。"""
        sid = next(self._session_ids)
        md5 = hashlib.md5(data).hexdigest()
        self._cancelled.discard(sid)
        tr = {"id": sid, "kind": "upload", "name": os.path.basename(remote_path),
              "path": remote_path, "size": len(data), "transferred": 0,
              "status": "running", "md5": md5, "error": ""}
        self._transfers[sid] = tr
        self._request("UPLOAD_INIT", {
            "path": remote_path, "size": len(data), "md5": md5,
            "session_id": sid,
        }, sid=sid)
        for off in range(0, len(data), CHUNK):
            if sid in self._cancelled:
                break
            chunk = data[off:off + CHUNK]
            self._conn.send_data(sid, chunk)
            tr["transferred"] += len(chunk)
        self._request("UPLOAD_DONE", {"session_id": sid}, sid=sid)
        if sid not in self._cancelled:
            tr["status"] = "done"
        return sid

    def download(self, remote_path: str) -> int:
        """下载：DOWNLOAD_INIT 后由服务端推送 DATA 帧与 DOWNLOAD_DONE。"""
        sid = next(self._session_ids)
        self._cancelled.discard(sid)
        name = os.path.basename(remote_path) or "download.bin"
        self._sinks[sid] = bytearray()
        self._transfers[sid] = {
            "id": sid, "kind": "download", "name": name,
            "path": remote_path, "size": 0, "transferred": 0,
            "status": "running", "md5": "", "error": "",
        }
        info = self._request("DOWNLOAD_INIT",
                             {"path": remote_path, "session_id": sid}, sid=sid)
        self._transfers[sid]["size"] = int(info.get("size", 0))
        self._transfers[sid]["md5"] = str(info.get("md5", ""))
        return sid

    def cancel(self, sid: int) -> None:
        self._cancelled.add(sid)
        tr = self._transfers.get(sid)
        if tr:
            tr["status"] = "cancelled"
        try:
            self._request("CANCEL", {"session_id": sid}, sid=sid, timeout=3)
        except Exception:
            pass

    # ------------------------------------------------------------ 帧回调
    def _on_control(self, msg: dict, conn: FrameConnection) -> None:
        cmd = str(msg.get("cmd", ""))
        seq = int(msg.get("seq", 0))
        data = msg.get("data") or {}
        self._log_add("←", cmd, data)
        if cmd.endswith("_ACK") and seq:
            with self._pending_lock:
                p = self._pending.get(seq)
            if p:
                p["response"] = msg
                p["event"].set()
            return
        if cmd == "DOWNLOAD_DONE":
            self._finish_download(int(msg.get("session_id", 0)), data)
        elif cmd == "DOWNLOAD_ABORT":
            sid = int(msg.get("session_id", 0))
            tr = self._transfers.get(sid)
            if tr and tr["status"] == "running":
                tr["status"] = "cancelled"
            self._sinks.pop(sid, None)
        elif cmd in ("FILE_CHANGE", "CLIPBOARD_CHANGE", "MEDIA_LIB_CHANGE"):
            self.on_event(cmd, data)

    def _on_data(self, sid: int, chunk: bytes) -> None:
        if sid in self._cancelled:
            return
        buf = self._sinks.get(sid)
        if buf is None:
            return
        buf.extend(chunk)
        tr = self._transfers.get(sid)
        if tr:
            tr["transferred"] += len(chunk)

    def _finish_download(self, sid: int, data: dict) -> None:
        tr = self._transfers.get(sid)
        buf = self._sinks.pop(sid, None)
        if tr is None or buf is None:
            return
        raw = bytes(buf)
        md5 = hashlib.md5(raw).hexdigest()
        expected = str(data.get("md5", ""))
        if expected and expected != md5:
            tr["status"] = "error"
            tr["error"] = "MD5 校验失败"
            return
        dest = self.downloads_dir / tr["name"]
        dest.write_bytes(raw)
        tr["status"] = "done"
        tr["md5"] = md5

    def _on_close(self) -> None:
        if self._stage in ("paired", "connected", "need_trust"):
            self._mark_dead("连接中断")

    # -------------------------------------------------------------- 心跳
    def _start_heartbeat(self) -> None:
        self._last_heartbeat = time.time()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="heartbeat")
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(HEARTBEAT_INTERVAL):
            try:
                self._request("HEARTBEAT", timeout=3)
                self._last_heartbeat = time.time()
            except Exception:
                self._mark_dead("心跳超时，判定设备离线")
                break

    def _mark_dead(self, reason: str) -> None:
        self._last_error = reason
        self._stage = "dead"
        self._stop.set()
        self._log_add("!", "DISCONNECTED", {"reason": reason})
        self.on_event("DISCONNECTED", {"reason": reason})

    # --------------------------------------------------------------- 状态
    def _log_add(self, direction: str, cmd: str, data: dict | None) -> None:
        brief = str(data or {})[:180]
        self._log.append({
            "ts": time.strftime("%H:%M:%S"),
            "dir": direction,
            "cmd": cmd,
            "brief": brief,
        })

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "stage": self._stage,
                "device": dict(self._device),
                "device_info": dict(self._device_info),
                "protocol_version": self._protocol_version,
                "trust": self._trust,
                "last_error": self._last_error,
                "last_heartbeat": self._last_heartbeat,
                "transfers": [dict(t) for t in self._transfers.values()],
                "log": list(self._log),
            }
