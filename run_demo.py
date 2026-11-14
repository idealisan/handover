#!/usr/bin/env python3
"""Handover Demo 入口。

    .venv/bin/python run_demo.py                    # 启动 Web GUI
    .venv/bin/python run_demo.py --no-browser       # 只起服务
    .venv/bin/python run_demo.py --self-test        # 无头自测（内置模拟手机）
    .venv/bin/python run_demo.py --probe HOST:PORT  # 探测任意 SSP-like 服务端
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import sys
import time
import uuid
import webbrowser

from demo.client import DesktopClient
from demo.engine import Engine
from demo.webui import serve


def wait_transfer(client: DesktopClient, sid: int, timeout: float = 8.0):
    end = time.time() + timeout
    while time.time() < end:
        for t in client.snapshot()["transfers"]:
            if t["id"] == sid and t["status"] in ("done", "error", "cancelled"):
                return t
        time.sleep(0.05)
    return None


def run_self_test(engine: Engine) -> int:
    results = []
    suffix = uuid.uuid4().hex[:6]

    def check(name, ok, detail=""):
        results.append((name, bool(ok)))
        print(("PASS  " if ok else "FAIL  ") + name + (("  " + detail) if detail else ""))

    dev = engine.devices()[0]
    engine.action("connect", {"host": dev["host"], "port": dev["port"]})
    snap = engine.snapshot()["connection"]
    check("握手 01 / HELLO", snap["stage"] == "need_trust", snap["stage"])
    check("协议版本协商", snap["protocol_version"] == "1.0-demo", snap["protocol_version"])

    res = engine.action("pair", {"trust": "ALWAYS"})
    snap = engine.snapshot()["connection"]
    check("握手 02 / 信任", res.get("result") == "ok" and snap["stage"] == "paired", snap["stage"])
    check("设备信息", bool(snap["device_info"].get("phone_model")), str(snap["device_info"].get("phone_model")))

    engine.action("list_dir", {"path": "/"})
    check("目录浏览", len(engine.snapshot()["listing"]["entries"]) >= 4)

    folder = f"自测目录-{suffix}"
    engine.action("mkdir", {"name": folder})
    engine.action("list_dir", {"path": "/"})
    names = [e["name"] for e in engine.snapshot()["listing"]["entries"]]
    check("新建文件夹", folder in names)

    upload_name = f"selftest-{suffix}.txt"
    payload = b"handover demo self test\n" * 200
    up = engine.action("upload", {
        "name": upload_name,
        "content_b64": base64.b64encode(payload).decode(),
    })
    check("上传 + MD5", up.get("size") == len(payload), f"{up.get('size')} bytes")

    down = engine.action("download", {"path": "/" + upload_name})
    tr = wait_transfer(engine.client, down["session_id"])
    dest = engine.downloads / upload_name
    check("下载完成", bool(tr) and tr["status"] == "done", tr["status"] if tr else "timeout")
    ok_bytes = dest.is_file() and dest.read_bytes() == payload
    check("下载内容一致", ok_bytes, hashlib.md5(dest.read_bytes()).hexdigest()[:12] if dest.is_file() else "n/a")

    engine.action("clipboard_post", {"text": "hello from mac"})
    check("剪贴板发送", any(i.get("text") == "hello from mac" for i in engine.snapshot()["clipboard"]))
    engine.action("clipboard_clear")
    check("剪贴板清空", len(engine.snapshot()["clipboard"]) == 0)

    renamed = f"renamed-{suffix}.txt"
    engine.action("rename", {"path": "/" + upload_name, "new_name": renamed})
    engine.action("list_dir", {"path": "/"})
    names = [e["name"] for e in engine.snapshot()["listing"]["entries"]]
    check("重命名", renamed in names and upload_name not in names)

    engine.action("delete", {"paths": ["/" + renamed]})
    engine.action("list_dir", {"path": "/"})
    names = [e["name"] for e in engine.snapshot()["listing"]["entries"]]
    check("删除进回收站", renamed not in names)

    big = engine.phone.root / "big.bin"
    if not big.exists():
        big.write_bytes(os.urandom(2 * 1024 * 1024))
    down = engine.action("download", {"path": "/big.bin"})
    engine.action("cancel", {"session_id": down["session_id"]})
    tr = wait_transfer(engine.client, down["session_id"], timeout=3)
    check("取消传输", bool(tr) and tr["status"] == "cancelled", tr["status"] if tr else "timeout")

    engine.action("set_locked", {"locked": True})
    engine.action("disconnect")
    engine.action("connect", {"host": dev["host"], "port": dev["port"]})
    res = engine.action("pair", {"trust": "ALWAYS"})
    check("锁屏返回 locked", res.get("result") == "locked", str(res.get("result")))
    engine.action("set_locked", {"locked": False})

    engine.action("disconnect")
    check("断开连接", engine.snapshot()["connection"]["stage"] == "disconnected")

    failed = [n for n, ok in results if not ok]
    print()
    print(f"自测结果：{len(results) - len(failed)}/{len(results)} 通过")
    if failed:
        print("失败项：" + "；".join(failed))
        return 1
    print("SELF-TEST PASS")
    return 0


def run_probe(target: str) -> int:
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
    ap.add_argument("--self-test", action="store_true", help="无头自测（内置模拟手机）")
    ap.add_argument("--probe", metavar="HOST:PORT", help="探测任意 SSP-like 服务端")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--port", type=int, default=0, help="Web GUI 端口，0 为随机")
    ap.add_argument("--workdir", default="tmp/demo", help="运行时沙箱目录")
    args = ap.parse_args()

    if args.probe:
        return run_probe(args.probe)

    engine = Engine(args.workdir)
    engine.start()
    try:
        if args.self_test:
            return run_self_test(engine)

        server, url = serve(engine, port=args.port)
        print("Handover Demo 已启动")
        print(f"  Web GUI : {url}")
        print(f"  模拟手机 : 127.0.0.1:{engine.server.port}")
        print("  提示：也可在界面里手动填写安卓端 IP:10086（先用 adb forward 映射端口）")
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
