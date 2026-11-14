"""Handover Demo：模拟 HandShaker macOS 客户端的 Python 演示工程。

分层对照 doc/03-SSP协议与工作原理.md：
    protocol.py   帧协议（控制面 JSON + session_id 裸流数据面）
    mock_phone.py 模拟手机端（虚拟文件系统 + TCP 服务端）
    client.py     桌面客户端（握手、心跳、请求-响应、传输）
    discovery.py  mDNS 设备发现
    engine.py     状态机与动作分发
    webui.py      本地 Web GUI
"""
