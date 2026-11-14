"""Handover Demo：桌面端连接真实安卓设备（不含模拟手机）。

分层对照 doc/03-SSP协议与工作原理.md：
    protocol.py   帧协议（控制面 JSON + session_id 裸流数据面）
    client.py     桌面客户端（握手、心跳、请求-响应、传输）
    discovery.py  mDNS 设备发现（仅浏览真实设备）
    engine.py     状态机与动作分发
    webui.py      本地 Web GUI

桌面端只连接真实安卓端 APK（android/），数据在设备公共存储 /sdcard 上。
"""
