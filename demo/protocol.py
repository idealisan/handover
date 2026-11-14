"""帧协议层：SSP-like，控制面 + session_id 裸二进制数据面。

真实 HandShaker 的 SSP 用 Protobuf 作控制面、用 session_id 关联裸字节流传输大文件
（见 doc/03-SSP协议与工作原理.md §4、APK 内 SmartSyncProtocol.proto 的注释）。
本 demo 保留同样的分层与帧头设计，但把控制面换成 JSON，省去 protoc 代码生成，
便于直接阅读和改成自己的协议。

帧格式（网络字节序）::

    +--------+---------+--------+-------------+---------+---------+
    | magic  | version | flags  | session_id  | length  | payload |
    | 4 byte | 1 byte  | 1 byte | 4 byte      | 4 byte  | N byte  |
    +--------+---------+--------+-------------+---------+---------+

flags: 0x01 控制帧（payload 为 UTF-8 JSON）
       0x02 数据帧（payload 为裸文件字节）
       0x04 响应帧（与 0x01 组合）
"""
from __future__ import annotations

import json
import socket
import struct
import sys
import threading
from typing import Callable

MAGIC = b"HOVR"
VERSION = 1
HEADER = struct.Struct("!4sBBII")
FLAG_CONTROL = 0x01
FLAG_DATA = 0x02
FLAG_RESPONSE = 0x04
MAX_FRAME_SIZE = 16 * 1024 * 1024

# SmartSync Protocol 的 41 个 SSPRequestType，取自 APK 内附带的
# main/proto/SmartSyncProtocol.proto。demo 只实现带 ★ 的部分，其余留作对照与扩展。
SSP_REQUEST_TYPES = (
    "HEART_BEAT_REQUEST",              # ★ 心跳
    "GET_DEVICE_INFO_REQUEST",         # ★ 设备信息
    "GET_THUMBNAIL_REQUEST",
    "GET_PHOTO_LIB_REQUEST",
    "GET_VIDEO_LIB_REQUEST",
    "GET_AUDIO_LIB_REQUEST",
    "GET_DIR_FILES_REQUEST",           # ★ 目录浏览
    "GET_FILE_COUNT_REQUEST",
    "GET_FILE_EXIST_REQUEST",
    "GET_CREATE_FOLDER_REQUEST",       # ★ 新建目录
    "GET_RENAME_FILE_REQUEST",         # ★ 重命名
    "GET_DOWNLOAD_FILE_REQUEST",       # ★ 下载
    "GET_DOWNLOAD_FILE_RESPONSE_HEADER",
    "GET_DOWNLOAD_FILE_RESPONSE_BODY",
    "GET_UPLOAD_FILE_REQUEST_HEADER",  # ★ 上传
    "GET_UPLOAD_FILE_RESPONSE_HEADER",
    "GET_UPLOAD_FILE_REQUEST_BODY",
    "GET_UPLOAD_FILE_RESPONSE",
    "GET_DELETE_FILE_REQUEST",         # ★ 删除（含回收站）
    "PHOTO_LIB_CHANGE",
    "AUDIO_LIB_CHANGE",
    "VIDEO_LIB_CHANGE",
    "MONITOR_FOLDER_REQUEST",
    "MONITOR_FOLDER_RESPONSE_HEADER",
    "MONITOR_FOLDER_RESPONSE",
    "GET_CLIPBOARD_REQUEST",           # ★ 取剪贴板
    "POST_CLIPBOARD_REQUEST",          # ★ 发剪贴板
    "CLEAR_CLIPBOARD_REQUEST",         # ★ 清空剪贴板
    "DELETE_CLIPBOARD_REQUEST",
    "CLIPBOARD_CHANGE",                # ★ 剪贴板变更推送
    "HANDSHAKE_REQUEST_01",            # ★ 第 1 轮握手
    "HANDSHAKE_RESPONSE_01",
    "HANDSHAKE_REQUEST_02",            # ★ 第 2 轮握手（信任）
    "HANDSHAKE_RESPONSE_02",
    "QUIT_REQUEST",                    # ★ 断开
    "CANCEL_REQUEST",                  # ★ 按 session_id 取消
    "PHOTO_SYNC_REQUEST",
    "FILE_CHANGE",                     # ★ 文件变更推送
    "SYNC_MONITOR_REQUEST",
    "UPDATE_FILE_INFO",
    "UPDATE_FILE_INFO_RESPONSE",
)


def make_control(cmd: str, *, seq: int = 0, session_id: int = 0,
                 data: dict | None = None, ok: bool = True,
                 error: str | None = None) -> bytes:
    """构造控制帧的 JSON 负载。"""
    msg = {
        "cmd": cmd,
        "seq": seq,
        "session_id": session_id,
        "ok": ok,
        "data": data or {},
        "error": error,
    }
    return json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def encode_frame(payload: bytes, *, flags: int = FLAG_CONTROL,
                 session_id: int = 0) -> bytes:
    return HEADER.pack(MAGIC, VERSION, flags, session_id, len(payload)) + payload


class FrameConnection:
    """在一个 TCP socket 上收发帧；读循环在独立线程里跑。

    on_control(msg, conn) 收到控制帧（JSON dict）
    on_data(session_id, chunk) 收到裸字节数据帧
    on_close() 连接关闭
    """

    def __init__(self, sock: socket.socket,
                 on_control: Callable[[dict, "FrameConnection"], None],
                 on_data: Callable[[int, bytes], None],
                 on_close: Callable[[], None],
                 label: str = "conn"):
        self.sock = sock
        self.label = label
        self.on_control = on_control
        self.on_data = on_data
        self.on_close = on_close
        self._send_lock = threading.Lock()
        self._closed = threading.Event()
        self._buf = bytearray()
        self._reader = threading.Thread(target=self._read_loop, daemon=True,
                                        name=f"{label}-reader")
        self._reader.start()

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def send_control(self, cmd: str, *, seq: int = 0, session_id: int = 0,
                     data: dict | None = None, ok: bool = True,
                     error: str | None = None, response: bool = False) -> None:
        payload = make_control(cmd, seq=seq, session_id=session_id,
                               data=data, ok=ok, error=error)
        flags = FLAG_CONTROL | (FLAG_RESPONSE if response else 0)
        self._send(encode_frame(payload, flags=flags, session_id=session_id))

    def send_data(self, session_id: int, chunk: bytes) -> None:
        self._send(encode_frame(chunk, flags=FLAG_DATA, session_id=session_id))

    def _send(self, frame: bytes) -> None:
        with self._send_lock:
            try:
                self.sock.sendall(frame)
            except OSError:
                self.close()

    def _read_loop(self) -> None:
        try:
            while not self._closed.is_set():
                chunk = self.sock.recv(65536)
                if not chunk:
                    break
                self._buf.extend(chunk)
                self._drain()
        except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            pass
        finally:
            self.close()
            try:
                self.on_close()
            except Exception:
                pass

    def _drain(self) -> None:
        while len(self._buf) >= HEADER.size:
            magic, ver, flags, sid, length = HEADER.unpack_from(self._buf, 0)
            if magic != MAGIC:
                raise ValueError("bad magic")
            if ver != VERSION:
                raise ValueError("bad version")
            if length > MAX_FRAME_SIZE:
                raise ValueError("frame too large")
            total = HEADER.size + length
            if len(self._buf) < total:
                return
            payload = bytes(self._buf[HEADER.size:total])
            del self._buf[:total]
            if flags & FLAG_DATA:
                self._safe_call(lambda: self.on_data(sid, payload))
            else:
                msg = json.loads(payload.decode("utf-8"))
                self._safe_call(lambda: self.on_control(msg, self))

    def _safe_call(self, fn) -> None:
        try:
            fn()
        except Exception as exc:  # 单个回调出错不应打断整条连接
            print(f"[{self.label}] handler error: {exc}", file=sys.stderr)

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
