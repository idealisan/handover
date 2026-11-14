"""模拟安卓端：虚拟文件系统 + 一个真正监听 TCP 的 SSP-like 服务端。

桌面客户端不是直接读内存状态，而是通过 socket 与这个「手机」收发帧，
因此握手、分帧、session_id、流式传输、取消等代码路径都会被真实走到。
后续接真实手机时，只需把连接目标换成安卓端监听的 IP:port，并把控制面
JSON 换成 Protobuf（见 doc/06 待验证项）。
"""
from __future__ import annotations

import hashlib
import os
import socket
import threading
import time
from pathlib import Path

from .protocol import FrameConnection

PROTOCOL_VERSION = "1.0-demo"
CLIENT_VERSION = "0.1.0"
MIN_HOST_VERSION = "0.1.0"
CHUNK = 64 * 1024
THROTTLE_MS = 6  # 每块之间稍作停顿，便于演示进度条与取消
DEVICE_UUID = "SIM-PHONE-0001"
DEVICE_NAME = "模拟手机 (Smartisan OS)"


class VirtualPhone:
    """落在 tmp/ 下的虚拟手机存储，带回收站。"""

    SEED_DIRS = ("DCIM/Camera", "Pictures/Screenshots", "Music",
                 "Download", "Documents")
    SEED_FILES = {
        "Documents/欢迎.txt": "Handover Demo 虚拟手机存储\n对应 doc/03 中的 SSPGetDirFilesRequest\n",
        "Documents/协议说明.txt": "控制面 JSON；数据面按 session_id 走裸字节流\n",
        "DCIM/Camera/photo_001.txt": "（示例图片占位文件）\n",
        "DCIM/Camera/photo_002.txt": "（示例图片占位文件）\n",
        "Music/track_001.txt": "（示例音频占位文件）\n",
        "Download/readme.txt": "从电脑拖进来的文件会出现在这里\n",
    }

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.trash = self.root / ".Trash"
        self.trash.mkdir(exist_ok=True)
        self.locked = False
        self.clipboard: list[dict] = [
            {"text": "欢迎使用 Handover Demo", "ts": int(time.time() * 1000)},
        ]
        self._seed()

    def _seed(self) -> None:
        for d in self.SEED_DIRS:
            (self.root / d).mkdir(parents=True, exist_ok=True)
        for rel, text in self.SEED_FILES.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.exists():
                p.write_text(text, encoding="utf-8")

    # ---- 路径安全：拒绝越出虚拟根目录 ----
    def _resolve(self, rel: str) -> Path:
        rel = (rel or "/").replace("\\", "/").strip()
        if not rel.startswith("/"):
            rel = "/" + rel
        p = (self.root / rel.lstrip("/")).resolve()
        if p != self.root and self.root not in p.parents:
            raise ValueError("路径越界")
        return p

    @staticmethod
    def _norm(rel: str) -> str:
        rel = (rel or "/").replace("\\", "/").strip().strip("/")
        return "/" + rel if rel else "/"

    def list_dir(self, rel: str) -> dict:
        p = self._resolve(rel)
        if not p.is_dir():
            raise ValueError("不是目录")
        entries = []
        for c in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
            if c.name == ".Trash":
                continue
            st = c.stat()
            entries.append({
                "name": c.name,
                "path": "/" + str(c.relative_to(self.root)).replace(os.sep, "/"),
                "size": 0 if c.is_dir() else st.st_size,
                "is_dir": c.is_dir(),
                "mtime": int(st.st_mtime),
            })
        return {"path": self._norm(rel), "entries": entries}

    def mkdir(self, parent: str, name: str) -> dict:
        name = os.path.basename(name)
        if not name:
            raise ValueError("目录名为空")
        p = self._resolve(parent) / name
        if p.exists():
            raise ValueError("同名文件已存在")
        p.mkdir()
        return {"path": "/" + str(p.relative_to(self.root)).replace(os.sep, "/")}

    def rename(self, rel: str, new_name: str) -> dict:
        new_name = os.path.basename(new_name)
        if not new_name:
            raise ValueError("名称为空")
        src = self._resolve(rel)
        if not src.exists():
            raise ValueError("源文件不存在")
        dst = src.parent / new_name
        if dst.exists():
            raise ValueError("目标已存在")
        src.rename(dst)
        return {"path": "/" + str(dst.relative_to(self.root)).replace(os.sep, "/")}

    def delete(self, paths: list[str]) -> dict:
        moved = []
        for rel in paths:
            src = self._resolve(rel)
            if not src.exists():
                continue
            dst = self.trash / f"{int(time.time() * 1000)}_{src.name}"
            src.rename(dst)
            moved.append(rel)
        return {"moved": moved, "trash": True}

    def read_bytes(self, rel: str) -> bytes:
        p = self._resolve(rel)
        if not p.is_file():
            raise ValueError("文件不存在或不是普通文件")
        return p.read_bytes()

    def write_bytes(self, rel: str, data: bytes) -> dict:
        p = self._resolve(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return {"path": self._norm(rel), "size": len(data)}

    def usage(self) -> tuple[int, int]:
        used = 0
        for p in self.root.rglob("*"):
            if p.is_file():
                try:
                    used += p.stat().st_size
                except OSError:
                    pass
        return used, 64 * 1024 * 1024 * 1024  # 假装 64 GB

    def device_info(self) -> dict:
        used, total = self.usage()
        return {
            "device_uuid": DEVICE_UUID,
            "device_name": DEVICE_NAME,
            "phone_model": "Smartisan OS Simulator",
            "phone_name": DEVICE_NAME,
            "product_brand": "Smartisan",
            "smartisan_version": "6.0-demo",
            "battery_percentage": 78,
            "battery_capacity": 4000,
            "phone_locked": self.locked,
            "disk_size": total,
            "used_disk_size": used,
            "root_path": "/",
            "apk_version": CLIENT_VERSION,
            "client_protocol_version": PROTOCOL_VERSION,
            "client_min_host_version": MIN_HOST_VERSION,
            "external_storage_permission": "ALLOW_READ_WRITE",
            "debug_build_time": "demo",
        }


class PhoneServer:
    """在回环地址上监听，模拟手机端的 SSP 服务。"""

    def __init__(self, phone: VirtualPhone, host: str = "127.0.0.1", port: int = 0):
        self.phone = phone
        self.host = host
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._conns: list[FrameConnection] = []
        self._uploads: dict[int, dict] = {}
        self._cancelled: set[int] = set()
        self._trust: str | None = None

    def start(self) -> None:
        self._running.set()
        self._thread = threading.Thread(target=self._accept_loop, daemon=True,
                                        name="phone-server")
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        try:
            self._sock.close()
        except OSError:
            pass
        with self._lock:
            conns = list(self._conns)
        for fc in conns:
            fc.close()

    def set_locked(self, locked: bool) -> None:
        self.phone.locked = bool(locked)

    def _accept_loop(self) -> None:
        while self._running.is_set():
            try:
                raw, addr = self._sock.accept()
            except OSError:
                break
            box: list[FrameConnection] = []
            fc = FrameConnection(
                raw,
                self._on_control,
                self._on_data,
                lambda: self._drop(box[0]) if box else None,
                label=f"phone-{addr[1]}",
            )
            box.append(fc)
            with self._lock:
                self._conns.append(fc)

    def _drop(self, fc: FrameConnection) -> None:
        with self._lock:
            if fc in self._conns:
                self._conns.remove(fc)

    def _push(self, cmd: str, data: dict | None = None) -> None:
        with self._lock:
            conns = [c for c in self._conns if not c.closed]
        for fc in conns:
            fc.send_control(cmd, data=data or {})

    @staticmethod
    def _ack(fc: FrameConnection, cmd: str, seq: int, sid: int = 0,
             data: dict | None = None, ok: bool = True,
             error: str | None = None) -> None:
        fc.send_control(cmd + "_ACK", seq=seq, session_id=sid,
                        data=data, ok=ok, error=error, response=True)

    def _on_control(self, msg: dict, fc: FrameConnection) -> None:
        cmd = msg.get("cmd", "")
        seq = int(msg.get("seq", 0))
        sid = int(msg.get("session_id", 0))
        d = msg.get("data") or {}
        try:
            if cmd == "HELLO":
                self._hello(fc, seq, d)
            elif cmd == "PAIR_REQUEST":
                self._pair(fc, seq, d)
            elif cmd == "HEARTBEAT":
                self._ack(fc, cmd, seq, data={"client_timestamp": int(time.time())})
            elif cmd == "GET_DEVICE_INFO":
                self._ack(fc, cmd, seq, data=self.phone.device_info())
            elif cmd == "LIST_DIR":
                self._ack(fc, cmd, seq, data=self.phone.list_dir(d.get("path", "/")))
            elif cmd == "MKDIR":
                self.phone.mkdir(d.get("path", "/"), d.get("name", ""))
                self._ack(fc, cmd, seq, data={"path": d.get("path")})
                self._push("FILE_CHANGE", {"path": d.get("path")})
            elif cmd == "RENAME":
                res = self.phone.rename(d.get("path", ""), d.get("new_name", ""))
                self._ack(fc, cmd, seq, data=res)
                self._push("FILE_CHANGE", res)
            elif cmd == "DELETE":
                res = self.phone.delete(d.get("paths", []))
                self._ack(fc, cmd, seq, data=res)
                self._push("FILE_CHANGE", res)
            elif cmd == "GET_CLIPBOARD":
                self._ack(fc, cmd, seq, data={"items": self.phone.clipboard})
            elif cmd == "POST_CLIPBOARD":
                text = str(d.get("text", ""))
                item = {"text": text, "ts": int(time.time() * 1000)}
                self.phone.clipboard.insert(0, item)
                self._ack(fc, cmd, seq, data={"succeed": True})
                self._push("CLIPBOARD_CHANGE", {"items": self.phone.clipboard})
            elif cmd == "CLEAR_CLIPBOARD":
                self.phone.clipboard.clear()
                self._ack(fc, cmd, seq, data={"succeed": True})
                self._push("CLIPBOARD_CHANGE", {"items": []})
            elif cmd == "UPLOAD_INIT":
                self._upload_init(fc, seq, sid, d)
            elif cmd == "UPLOAD_DONE":
                self._upload_done(fc, seq, sid)
            elif cmd == "DOWNLOAD_INIT":
                self._download_init(fc, seq, sid, d)
            elif cmd == "CANCEL":
                self._cancelled.add(sid)
                self._ack(fc, cmd, seq, sid, data={"session_id": sid})
            elif cmd == "QUIT":
                fc.close()
            else:
                self._ack(fc, cmd, seq, ok=False, error=f"未知命令: {cmd}")
        except Exception as exc:
            self._ack(fc, cmd, seq, sid, ok=False, error=str(exc))

    def _hello(self, fc: FrameConnection, seq: int, d: dict) -> None:
        min_client = str(d.get("min_client_version", "0"))
        if CLIENT_VERSION < min_client:
            self._ack(fc, "HELLO", seq, ok=False,
                      error="手机端版本低于电脑端要求的最小版本")
            return
        self._ack(fc, "HELLO", seq, data={
            "device_uuid": DEVICE_UUID,
            "device_name": DEVICE_NAME,
            "apk_version": CLIENT_VERSION,
            "client_protocol_version": PROTOCOL_VERSION,
            "client_min_host_version": MIN_HOST_VERSION,
            "is_smartisan_device": True,
            "usb_serial": "SIM0001",
        })

    def _pair(self, fc: FrameConnection, seq: int, d: dict) -> None:
        trust = str(d.get("trust", "NO"))
        if self.phone.locked:
            result = "locked"
        elif trust in ("ONCE", "ALWAYS"):
            result = "ok"
            self._trust = trust
        else:
            result = "failed"
        self._ack(fc, "PAIR_REQUEST", seq, data={
            "trust": trust,
            "result": result,
            "device_uuid": DEVICE_UUID,
            "derived_key": "demo-derived-key",
        })

    def _upload_init(self, fc: FrameConnection, seq: int, sid: int, d: dict) -> None:
        self._cancelled.discard(sid)
        self._uploads[sid] = {
            "path": str(d.get("path", "")),
            "md5": d.get("md5"),
            "buf": bytearray(),
        }
        self._ack(fc, "UPLOAD_INIT", seq, sid, data={"ready": True})

    def _on_data(self, sid: int, chunk: bytes) -> None:
        u = self._uploads.get(sid)
        if u is None or sid in self._cancelled:
            return
        u["buf"].extend(chunk)

    def _upload_done(self, fc: FrameConnection, seq: int, sid: int) -> None:
        u = self._uploads.pop(sid, None)
        if u is None:
            self._ack(fc, "UPLOAD_DONE", seq, sid, ok=False, error="上传会话不存在")
            return
        data = bytes(u["buf"])
        if u["md5"] and hashlib.md5(data).hexdigest() != u["md5"]:
            self._ack(fc, "UPLOAD_DONE", seq, sid, ok=False, error="MD5 校验失败")
            return
        res = self.phone.write_bytes(u["path"], data)
        res["md5"] = hashlib.md5(data).hexdigest()
        self._ack(fc, "UPLOAD_DONE", seq, sid, data=res)
        self._push("FILE_CHANGE", res)

    def _download_init(self, fc: FrameConnection, seq: int, sid: int, d: dict) -> None:
        raw = self.phone.read_bytes(str(d.get("path", "")))
        md5 = hashlib.md5(raw).hexdigest()
        self._cancelled.discard(sid)
        self._ack(fc, "DOWNLOAD_INIT", seq, sid,
                  data={"size": len(raw), "md5": md5})
        t = threading.Thread(target=self._stream, args=(fc, sid, raw, md5),
                             daemon=True, name=f"download-{sid}")
        t.start()

    def _stream(self, fc: FrameConnection, sid: int, raw: bytes, md5: str) -> None:
        for off in range(0, len(raw), CHUNK):
            if sid in self._cancelled or fc.closed:
                fc.send_control("DOWNLOAD_ABORT", session_id=sid,
                                data={"session_id": sid})
                return
            fc.send_data(sid, raw[off:off + CHUNK])
            time.sleep(THROTTLE_MS / 1000.0)
        fc.send_control("DOWNLOAD_DONE", session_id=sid,
                        data={"session_id": sid, "md5": md5, "size": len(raw)})
