#!/usr/bin/env python3
"""Handover Demo 入口（只连接真实安卓设备，不含任何模拟手机）。

    .venv/bin/python run_demo.py                    # 启动 Web GUI 并打开浏览器
    .venv/bin/python run_demo.py --no-browser       # 只起服务
    .venv/bin/python run_demo.py --probe HOST:PORT  # 对真实设备做一次协议自检
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import sys
import time
import webbrowser

from demo.client import DesktopClient
from demo.engine import DEFAULT_HOST, DEFAULT_PORT, Engine
from demo.webui import serve

# 本机可能有全局 HTTP 代理；本地回环必须直连。
os.environ.setdefault("no_proxy", "127.0.0.1,localhost,::1")
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost,::1")


def wait_transfer(client: DesktopClient, sid: int, timeout: float = 8.0):
    end = time.time() + timeout
    while time.time() < end:
        for t in client.snapshot()["transfers"]:
            if t["id"] == sid and t["status"] in ("done", "error", "cancelled"):
                return t
        time.sleep(0.05)
    return None


def run_probe(target: str) -> int:
    """对真实安卓端做一次端到端协议自检。"""
    host, _, port_s = target.partition(":")
    if not host or not port_s.isdigit():
        print("用法：--probe 127.0.0.1:10086")
        return 2
    client = DesktopClient("tmp/demo/probe_downloads")
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok)))
        print(("PASS  " if ok else "FAIL  ") + name + (("  " + detail) if detail else ""))

    try:
        client.connect(host, int(port_s))
        stage = client.snapshot()["stage"]
        check("连接 + HELLO", stage in ("need_trust", "paired"), stage)
        res = client.pair("ALWAYS")
        check("信任握手", res.get("result") == "ok", str(res.get("result")))
        info = client.snapshot()["device_info"]
        check("设备信息", bool(info), str(info.get("phone_model", "")))
        listing = client.list_dir("/")
        check("目录浏览", "entries" in listing, f"{len(listing.get('entries', []))} 项")

        payload = b"probe from desktop\n" * 50
        client.upload("/probe.txt", payload)
        sid = client.download("/probe.txt")
        tr = wait_transfer(client, sid)
        dest = client.downloads_dir / "probe.txt"
        check("上传下载往返", bool(tr) and tr["status"] == "done" and dest.is_file()
              and dest.read_bytes() == payload, tr["status"] if tr else "timeout")
        client.post_clipboard("probe clipboard")
        items = client.get_clipboard()
        check("剪贴板", any(i.get("text") == "probe clipboard" for i in items), str(len(items)))
        client.disconnect()
    except Exception as exc:
        print(f"探测异常：{exc}")
        results.append(("探测", False))
    failed = [n for n, ok in results if not ok]
    print()
    print(f"探测结果：{len(results) - len(failed)}/{len(results)} 通过")
    return 0 if not failed else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Handover Demo")
    ap.add_argument("--probe", metavar="HOST:PORT", help="对真实设备做协议自检")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--port", type=int, default=0, help="Web GUI 端口，0 为随机")
    ap.add_argument("--workdir", default="tmp/demo", help="运行时下载目录")
    ap.add_argument("--no-autoconnect", action="store_true",
                    help="启动时不自动连接默认安卓端地址")
    args = ap.parse_args()

    if args.probe:
        return run_probe(args.probe)

    engine = Engine(args.workdir)
    engine.start()

    # 启动即尝试连真机；失败则留在「未连接」状态，由界面手动连接。
    if not args.no_autoconnect:
        try:
            engine.action("connect", {"host": DEFAULT_HOST, "port": DEFAULT_PORT})
        except Exception as exc:
            print(f"  自动连接真机失败（可在界面手动连接）：{exc}")

    try:
        server, url = serve(engine, port=args.port)
        print("Handover Demo 已启动（仅连接真实安卓设备）")
        print(f"  Web GUI : {url}")
        print(f"  真机地址: {DEFAULT_HOST}:{DEFAULT_PORT}  (adb forward tcp:10086 tcp:10086)")
        print("  安卓端数据源：设备公共存储 /sdcard（已申请文件/相册权限）")
        if not args.no_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n正在退出…")
        finally:
            server.shutdown()
        return 0
    finally:
        engine.stop()


if __name__ == "__main__":
    sys.exit(main())
