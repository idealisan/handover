# 08 Python GUI Demo 说明

> 本文件说明仓库内的 Python 演示工程：用浏览器 GUI 复刻 HandShaker 的 macOS 客户端，
> 通过自定义的 SSP-like 协议连接**真实安卓设备**。本工程**不含任何模拟手机/假数据**，
> 界面里看到的目录与文件全部来自设备公共存储 `/sdcard`。

## 1. 目标与边界

- 复刻的是**策略与架构**：传输层/协议层解耦、两轮握手与信任、心跳、session_id 关联的
  控制面 + 裸流数据面、目录/剪贴板/文件事件。
- **不追求与官方 SSP 二进制兼容**：控制面用 JSON 替代 Protobuf，帧头为自定义格式。
  官方帧头字节布局与密钥交换尚未确认（见 doc/06），因此本 demo 不能直接连官方安卓端。
- 连接的是本项目自建的安卓端（见 doc/09），二者使用完全相同的 HOVR/JSON 协议；
  安卓端已申请文件/相册权限，读取的是真实系统目录。
- 早期版本曾内置内存模拟手机，现已按需求**彻底移除**（见 doc/10）。

## 2. 运行方式

首次准备：

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

准备真实安卓端（二选一）：

```
# 方式 A：adb forward（本机连虚拟机/手机）
adb forward tcp:10086 tcp:10086
# 方式 B：同一局域网，安卓端会自行注册 _handshaker_ssp._tcp，被 mDNS 自动发现
```

启动 GUI（会自动打开浏览器，并默认连接 `127.0.0.1:10086`）：

```
.venv/bin/python run_demo.py
```

其他入口：

```
.venv/bin/python run_demo.py --no-browser --port 8765   # 只起服务、不弹浏览器
.venv/bin/python run_demo.py --no-autoconnect            # 启动时不自动连，由界面手动连接
.venv/bin/python run_demo.py --probe 127.0.0.1:10086    # 对真实设备做端到端协议自检
```

依赖只有 **zeroconf**（mDNS/Bonjour 发现，缺失时自动降级为手动输入）。
GUI 使用标准库 **http.server** + 浏览器，因为本机 Python 缺少 `_tkinter`，无法使用
tkinter；若后续想要原生窗口，只需替换 `demo/webui.py`，引擎与协议层不用动。

> 注意：本机存在全局 `http_proxy` 时，脚本已设置 `no_proxy=127.0.0.1,localhost`，
> 浏览器访问 `http://127.0.0.1:8765/` 会直连，不会被代理拦截。

## 3. 文件结构

| 文件 | 职责 |
| --- | --- |
| `run_demo.py` | 入口：GUI / 探测 / 启动即连真机 |
| `demo/protocol.py` | HOVR 帧编解码、控制消息、41 个 SSP 命令名参考 |
| `demo/client.py` | 桌面客户端：两轮握手、心跳、请求-响应、上传下载与取消 |
| `demo/discovery.py` | 仅浏览 mDNS 真实设备，zeroconf 缺失时降级 |
| `demo/engine.py` | 状态机与动作分发，供 GUI 调用 |
| `demo/webui.py` | 本地 Web GUI（单页 HTML/CSS/JS + JSON API） |
| `demo/mock_phone.py` | **已清空**：原模拟手机实现已删除，仅保留占位说明 |
| `requirements.txt` | 依赖清单 |
| `.gitignore` | 排除 .venv、缓存、tmp 与本机产物 |

## 4. 协议设计

帧格式（网络字节序，与安卓端完全一致）：

```
+--------+---------+--------+-------------+---------+---------+
| magic  | version | flags  | session_id  | length  | payload |
| 4 byte | 1 byte  | 1 byte | 4 byte      | 4 byte  | N byte  |
+--------+---------+--------+-------------+---------+---------+
```

- `magic` = HOVR，`version` = 1。
- `flags`：0x01 控制帧（JSON）、0x02 数据帧（裸字节）、0x04 响应帧。
- 控制帧 JSON：`cmd`、`seq`、`session_id`、`ok`、`data`、`error`。
- 响应命名：请求 `X` 的响应为 `X_ACK`；服务端主动推送使用独立命令名（`FILE_CHANGE` 等）。
- 大文件不放进 JSON：先 `UPLOAD_INIT` / `DOWNLOAD_INIT` 协商，再用同一 `session_id`
  连续发送数据帧，最后以 `UPLOAD_DONE` / `DOWNLOAD_DONE` 收尾并校验 MD5。
- `CANCEL` 按 `session_id` 取消某个传输。

已实现命令：HELLO、PAIR_REQUEST、HEARTBEAT、GET_DEVICE_INFO、LIST_DIR、MKDIR、RENAME、
DELETE、GET_CLIPBOARD、POST_CLIPBOARD、CLEAR_CLIPBOARD、UPLOAD_INIT、UPLOAD_DONE、
DOWNLOAD_INIT、CANCEL、QUIT，以及 FILE_CHANGE / CLIPBOARD_CHANGE / DOWNLOAD_DONE /
DOWNLOAD_ABORT 推送。`demo/protocol.py` 里保留了官方 41 个命令名的完整清单，便于对照。

## 5. 界面功能

- **设备**：仅显示 mDNS 发现的真实设备；也可手动填写 IP:端口（默认预填 127.0.0.1:10086）。
- **握手**：连接后进入「等待手机授权」，弹窗选择「仅此一次 / 始终信任 / 拒绝」，
  对应 `result` 的 ok / failed。
- **状态栏**：连接状态、协议版本、最近心跳时间。
- **文件**：目录浏览（真实 `/sdcard`）、上级、新建文件夹、重命名、删除（回收站）、
  上传、下载、进度与取消。
- **剪贴板**：读取手机剪贴板、发送文字、清空，变更时自动刷新。
- **传输**：上传/下载任务列表、进度条、状态、取消、下载完成后可保存到电脑。
- **协议日志**：按时间显示收发的命令与摘要，便于观察握手与传输过程。

## 6. 端到端自检结果

`.venv/bin/python run_demo.py --probe 127.0.0.1:10086` 对真实安卓端，6/6 通过：

```
PASS  连接 + HELLO  need_trust
PASS  信任握手  ok
PASS  设备信息  SM-A536B
PASS  目录浏览  13 项          # /sdcard 真实根目录
PASS  上传下载往返  done
PASS  剪贴板  1
```

另做过跨边界双向验证（见 doc/10）：设备侧新建的文件 UI 能列出，UI 上传的文件
设备侧 `cat` 字节与 MD5 一致；真实截图
`Screenshot_20261114-042107_Handover Demo.png`（84925 字节）可下载且与原图一致。

## 7. 安全与隐私

- Web GUI 只监听 **127.0.0.1**，不暴露到局域网。
- 桌面端对文件名统一取 basename；安卓端对路径做 canonical 校验，拒绝 `..` 越界。
- 上传限制 8 MB（演示用），base64 严格解码。
- 前端对所有动态文本做 HTML 转义，文件链接改用 data 属性 + 事件委托，避免文件名注入。
- 明文 TCP、无 TLS/加密，仅用于本机/可信局域网演示。
- 不上传云端、无遥测；运行产物全部在 `tmp/`，已被 `.gitignore` 排除。

## 8. 接入官方设备的替换点

1. 控制面：把 JSON 换成官方 `SmartSyncProtocol.proto` 生成的 Protobuf 代码。
2. 帧头：按抓包结果替换 magic/长度/字段顺序（见 doc/06 第 1 项）。
3. 握手：接入 ENCKEY / derived_key / RSA 校验（见 doc/06 第 2、3 项）。
4. 传输安全：在 TCP 上加 TLS 1.3 或自签证书 + pinning。
5. 发现：继续使用 `_handshaker_ssp._tcp`，或改成自己的服务类型。
