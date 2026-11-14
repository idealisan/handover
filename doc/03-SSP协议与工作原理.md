# 03 SSP 协议与工作原理

> 这是本系列的核心报告。最权威的一手证据是 APK 内附带的
> `main/proto/SmartSyncProtocol.proto`（741 行，proto2，`package smartsync`），
> 它开宗明义写着：「这个文件定义了 Smartisan HandShaker 手机端和电脑端直接的交互协议」。
> Mac 端 `SmartFinderCore.framework` 中的 `SSP*` 类与该定义逐条对应，构成双向印证。

## 1. 总体架构：三层解耦

```
┌─────────────────────────────────────────────────────────────┐
│ 业务层   文件/目录 · 媒体库/缩略图 · 剪贴板 · 目录监控 · 照片同步 │
│          ← 由 41 个 SSPRequestType 命令驱动                    │
├─────────────────────────────────────────────────────────────┤
│ 协议层   SmartSync Protocol (SSP)                             │
│          Protobuf 消息 + 帧头 + session_id + 心跳 + 两轮握手信任 │
├─────────────────────────────────────────────────────────────┤
│ 传输层   ① USB-AOA(libusb bulk)  ② USB-ADB(adb forward +       │
│          localhost TCP)  ③ Wi-Fi 局域网(mDNS/NSD + TCP/TLS)   │
└─────────────────────────────────────────────────────────────┘
```

**核心策略**：无论物理链路是 USB 还是 Wi-Fi，上层跑的都是同一套 SSP。
电脑端不直接读手机文件系统，而是把手机端当成一个「远程文件/媒体服务」，
通过请求-响应来浏览、上传、下载、订阅变更。这正是新项目最值得照搬的地方。

## 2. 三条传输通道

### 2.1 USB-AOA（Android Open Accessory）——优先链路

**证据【事实】**（Mac 端字符串）：

- `matchingdevices.plist` 提供 `IOProviderClass=IOUSBDevice` + `idVendor` 的匹配字典；
  `start watching for SF USB devices`、`USB device arrived`、`A device was opened already`。
- `libusb_control_transfer get aoa verion failed`、`got aoa verion: %d`、
  `device supports protocol 1 or higher`、`isSupportAOAv2`。
- `send_control_string ok` / `send_start_accessory_control ok` / `ACCESSORY_START control sent`、
  `Attempted to put device into accessory mode` / `now in accessories mode`、
  `Accessory Identification sent.`；发送的三个标识串是 `Smartisan`、`HandShaker`、
  版本号 `1.0`（另有 `hostuuid`）。
- `bulk_in_endpoint = %x` / `bulk_out_endpoint = %x`、`bad bulk ep in!!!`、
  `libusb_bulk_transfer send data failed`、`message reading thread canceled`、
  `com.smatisan.smartfinder.usb_write_queue`。
- `SFUSBDevice sendHandShakeRequestWithMSTimeout:`、`err: handshake timeout`、
  `err: handshake sessionid does not match!`、`err: handshake data error! > 500 bytes`。

**证据【事实】**（APK 端）：

- `res/xml/accessory_filter.xml` 内容为
  `manufacturer="Smartisan" model="HandShaker" version="1.0"`。
- AndroidManifest 声明 `android.hardware.usb.action.USB_ACCESSORY_ATTACHED`，
  并有 `USB_ACCESSORY_DETACHED`；类名 `UsbAccessory`、`AccessoryManager.java`、
  `openAccessory succeeded`、`onStartCommand, accessory =`。
- 服务 `ConnectionManagerService`、`MediaScannerService`、`UiDialogService`。

**时序【强推断】**：

1. 插线，Mac 通过 IOKit/libusb 热插拔按 `idVendor` 匹配到安卓设备。
2. 读取 AOA 协议版本，向设备发送厂商/型号/版本等控制字符串，再发 `ACCESSORY_START`。
3. 手机重新以配件模式枚举，身份为 `Smartisan / HandShaker / 1.0`；系统按
   `accessory_filter.xml` 匹配到手机端应用并自动拉起 `ConnectionManagerService`。
4. 双方用 bulk in/out 端点收发 SSP 帧，直接进入两轮握手。

**为什么这是「好用」的关键**：AOA 是 Android 系统级配件机制，理论上**不需要打开
USB 调试、不需要 root、也不需要安装驱动**。UI 文案把「AOA 失败」与「未打开 USB 调试」
分成两条不同的提示，佐证二者是不同链路。此项为【推断】，需实机验证。

### 2.2 USB-ADB 转发——兼容/回退链路

**证据【事实】**：

- Mac 应用自带 `adb` 可执行文件；`SmartFolder.apk`、`install`、
  `[INSTALL_FAILED_UNKNOWN_SOURCES`、`[INSTALL_FAILED_VERSION_DOWNGRADE`、
  `[INSTALL_PARSE_FAILED_INCONSISTENT_CERTIFICATES`；
  `http://sf.smartisan.com/sf/release/apk`。
- `am force-stop com.smartisanos.smartfolder`、
  `startservice --user 0 com.smartisanos.smartfolder/.AdbForwardService`、
  `dumpsys activity services com.smartisanos.smartfolder`。
- `adb forward --list`、`%@ tcp:(\d+) tcp:10086`、`tcp:%@` / `tcp:%lu` /
  `tcp:10086`，以及音频通道 `%@ tcp:(\d+) tcp:19999` / `tcp:19999`。
- `http://127.0.0.1:%d/`、`http://127.0.0.1:%lu/?test=123`、
  `http://127.0.0.1:%lu/?file_path=%@`；`startADBForwardAtPort:`、`socketPort`、
  `audioHttpServerSocketPort`、`adbforward start connectToHost`。
- `SFADBForwardKeepAliveOperation`、`keepAliveOperationQueue`、
  `start heart beat thread`、`HeartBeat timeout, client dead %f`。
- `adb shell` 命令串：`getprop ro.build.version.sdk`、`dumpsys battery`、
  `screencap -p /sdcard/sfscreenshot.png`、`ls -al "%@"`、`mkdir -p "%@"`、
  `rm -rf`、`find %@ -maxdepth 5 ... | wc -l`、
  `am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE`。
- UI 文案：「使用 HandShaker 需要在手机中安装数据传输服务应用，请在系统设置中打开
  允许从『未知来源』安装应用」「无法安装应用『传输服务』」「传输服务签名不一致」
  「请在手机弹出的『允许 USB 调试』对话框点击『确定』按钮」。

**时序【强推断】**：

1. 检测到 USB 调试已授权 → 用内置 adb 安装/升级手机端「传输服务」APK
   （`com.smartisanos.smartfolder`），需要用户允许未知来源安装。
2. `am startservice` 拉起 `.AdbForwardService`；`adb forward tcp:<本机端口> tcp:10086`
   把电脑端本地端口转发到手机端 SSP 服务，音频 HTTP 服务另用 `tcp:19999`。
3. 电脑端用 `GCDAsyncSocket` 连 `localhost:<本机端口>` 跑 SSP。
4. 大文件/缩略图另走 `http://127.0.0.1:<port>/?file_path=...` 形式的本地 HTTP 通道，
   与 APK 侧的 `sessionId=` / `&clientSessionId=` 查询参数呼应。
5. `adb forward --list` 的正则解析说明本机端口是动态分配、可复用的。

**局限**：`10086` 为手机端 SSP 监听端口属于【强推断】（APK 有 `Start Wi-Fi ServerSocket...`
与 `mServerSocket`，Mac 有 `connectToHost:onPort:`）；端口选择策略、HTTP 通道与 SSP
裸二进制流之间的分工需抓包确认。

### 2.3 Wi-Fi 局域网

**证据【事实】**（Mac 端）：

- Bonjour 服务类型 **`_handshaker_ssp._tcp`**；`NSNetService`、`NSNetServiceBrowser`
  及全部 delegate 方法、`searchForServicesOfType:inDomain:`、`publish` / `unpublish`、
  `netServiceBrowser:didFindService:moreComing:`、`netService didNotResolve`。
- `start watching for SF Wifi devices`、`SFWifiDeviceManager startScan beg`、
  `Unable to connect to the address(%@) error`、`try again in 1 second.`、
  `Unable to connect to any resolved address. Apk might close already.`。
- `GCDAsyncSocket` / `GCDAsyncUdpSocket` / `joinMulticastGroup`；
  `socket:didAcceptNewSocket:`、`newSocketQueueForConnectionFromAddress:onSocket:`
  （说明电脑端**也会监听**接受入站连接）。
- `SFWifiAsyncSocket, Error in socket() function`、`SFWifiSocket,Error in connect() function`。
- 二维码相关：`IPPortQRCode`、`APKQRCode`、`refreshQRCode`、`invalidQRCode`、
  `refresh qrcode then relisten ip port %@`、`didScanQRCode IP : %@`、
  `QRCcode begin connect`、`QRCode send handshake request 1/2`、
  `Connect by qrcode success`、`SFWifiScanQRCode`。
- UI 文案：「Connect via USB」「请先连接到无线网络」「请打开 HandShaker 手机客户端，
  扫描上方二维码连接」「看不到要连接的手机？请扫码连接」「二维码已过期，请点击刷新」。

**证据【事实】**（APK 端）：`NsdManager`、`NsdServiceInfo`、`registerService` /
`unregisterService`、`cdoStartNsdBroadcast`、`_handshaker_ssp._tcp.`、
`Start Wi-Fi ServerSocket...`、`ServerSocket is already running`、
`RunServerSocket... mSocket.accept`、`java.net.ServerSocket`、`WifiManager`；
`network_security_config.xml` 设 `cleartextTrafficPermitted="true"`。

**时序【强推断】**：

1. 手机端启动 `ServerSocket`，用 NSD 注册 `_handshaker_ssp._tcp` 服务（携带端口）。
2. 电脑端 `NSNetServiceBrowser` 浏览并 resolve 到 IP:port，`GCDAsyncSocket` 主动连上，
   在该 TCP 连接上跑 SSP。
3. 发现失败（跨网段、mDNS 被阻断）时，电脑端展示含自身 IP:port 的二维码
   （`IPPortQRCode`），手机端扫码后**反向连到电脑端监听端口**，触发
   `socket:didAcceptNewSocket:`。
4. `APKQRCode` 是下载手机端应用的二维码（关联 `http://t.tt/apps/handshaker?qr=1`），
   与连接无关。

**局限**：两端都同时具备 publish/监听与 browse/连接能力，因此不是严格的固定 C/S，
不同通道下角色可能互换；TLS 是否默认启用未定（有 `GCDAsyncSocketManuallyEvaluateTrust`、
`kCFStreamErrorDomainSSL`、自签证书 pinning 相关字符串，但 Mac 的
`NSAllowsArbitraryLoads=true` 与 APK 的 `cleartextTrafficPermitted=true` 说明明文同样被允许）。

## 3. 两轮握手与信任模型

来自 proto 定义（`SSPHandShakeRequest01/Response01/Request02/Response02`）。

**第 1 轮：交换身份与能力**

电脑 → 手机 `SSPHandShakeRequest01`：

| 字段 | 含义 |
| --- | --- |
| `host_uuid` | 电脑唯一标识（注释举例：MAC 地址） |
| `host_name` / `host_model` | 电脑名、机型 |
| `host_timestamp` | 主机时间戳 |
| `host_smart_sync_protocol_version` | 主机 SSP 协议版本 |
| `host_app_version` / `host_min_client_version` | 主机版本、要求的最小 APK 版本 |
| `md5` | **ENCKEY 的 MD5** |
| `enckey` | **ENCKEY**（密钥交换材料） |
| `heartbeat_timeout_second` | 心跳超时上限（如 10 秒） |

手机 → 电脑 `SSPHandShakeResponse01`（只返回一次）：`apk_version`、`apk_version_name`、
`client_timestamp`、`client_smart_sync_protocol_version`、`client_min_host_version`、
`device_uuid`、`device_name`、`usb_serial`（`getprop ro.serialno`）、`is_smartisan_device`、
`client_min_host_version_code`。

**第 2 轮：校验 derived_key 或移除信任**

电脑若发现 `device_uuid` 不在信任列表（新手机），发 `SSPHandShakeRequest02`：
`host_uuid`、`derived_key`、`trust_type`。手机回 `SSPHandShakeResponse02`（**可能返回多次**，
最后一次必须带 `result`）：`trust_type`、`device_uuid`、`device_name`、`derived_key`、`result`。

`result` 的四种取值（proto 注释原文）：

- `'failed'`：握手失败
- `'locked'`：手机处于锁屏
- `'needauth'`：手机处于授权窗口
- `base64(RSA_encrypt('ok'))`：握手成功 —— 电脑端用 RSA 解密出 `ok` 才判定成功

信任类型 `SSPHandShakeTrustType`：
`TRUST_WAITING`(1) / `TRUST_UNKNOW`(2) / `TRUST_NO`(3) / `TRUST_ONCE`(4) /
`TRUST_ALWAYS`(5) / `TRUST_REMOVE`(6)。

**密码学证据【事实】**：Mac 端 `Failed to create key BIO`、`Failed to create RSA`、
`RSA_sign failed!`、`keySize==128`、`data signing failed!`、`check result packge size wrong`、
`check result key size wrong`、`enckey`、`derived_key`、`trust_type`；静态链接 OpenSSL 1.0.2d。
APK 端 `RSA/ECB/PKCS1Padding`、`SHA256withRSA`、`RSAPublicKeySpec`、`rsa verify failed`、
`writeKeyExchangeInfo====rsaResultStr===`、`derivedKey`。

UI 佐证：「手机『%@』拒绝信任这台电脑」「通过无线网络连接过的设备将出现在这里。
你可以在与手机建立连接时选择『信任』」「访问受限 / 请先解锁手机」「请授权这台 Mac」。

**局限**：ENCKEY 与 derived_key 的确切生成/派生算法、密钥长度、是否用于逐帧加密，
静态分析无法确定；见 `06-待验证问题与后续分析计划.md`。

## 4. 报文分帧与会话（session_id）

**证据【事实】**：

- Mac `SSPRequestOperation` 的属性：`sessionId`、`dataLength`、`lenData`(NSMutableData)、
  `dataLock`、`request`(`GPBMessage`)、`didSent` / `didFinish` / `didCancel`、
  `sentTime`、`timeout`；底层用 `readDataToLength:withTimeout:tag:` 与
  `writeData:withTimeout:tag:`。
- Mac `SFADBForwardOperation` 有 `hasHeader`、`totalBodyLength`、`rawData`，
  说明是「头部 + 定长 body」的读法。
- 日志串：`[%@]=========sessionId:%d=========`、`send data request timeout sessionId=%u`、
  `send data request failed:%s sessionId=%u`、`send cancel request sessionId=%ld failed`。
- APK：`SspPacket.java`、`SspReader`、`SspExecutorManager`、`SspFileTransferTask`、
  `sessionId` / `session_id` / `clientSessionId`、`getSessionId` / `setSessionId`、
  `Reader cannot read packet anymore, disconnecting...`。
- proto 注释明确写了两次：
  「`SSPDownloadFileResponseBody` 不适合大文件传输，所以文件传输主要数据通过
  **session_id + binary** 方式传输」、
  「`SSPUploadFileRequestBody` 不适合大文件传输，所以文件传输主要数据通过
  session_id + binary 方式传输」。

**模型【强推断】**：每个逻辑请求分配一个 `session_id`；一帧 = 头部（长度、类型、
session_id 等）+ Protobuf 消息体；`GPBMessage` 负责控制面，大文件字节流不塞进
`bytes` 字段，而是由同一 `session_id` 关联的裸二进制流（或独立 HTTP 通道）传输。
`CANCEL_REQUEST` 同样携带 `session_id`，用于取消某一个具体传输任务。
这样做既保留了 Protobuf 的可扩展性，又避免大文件序列化带来的内存与拷贝开销。

## 5. 命令集：41 个 SSPRequestType

| 分组 | 命令（编号） |
| --- | --- |
| 会话控制 | `HANDSHAKE_REQUEST_01`(31) / `RESPONSE_01`(32) / `REQUEST_02`(33) / `RESPONSE_02`(34)、`QUIT_REQUEST`(35)、`CANCEL_REQUEST`(36) |
| 心跳与设备 | `HEART_BEAT_REQUEST`(1)、`GET_DEVICE_INFO_REQUEST`(2) |
| 目录与文件 | `GET_DIR_FILES_REQUEST`(7)、`GET_FILE_COUNT_REQUEST`(8)、`GET_FILE_EXIST_REQUEST`(9)、`GET_CREATE_FOLDER_REQUEST`(10)、`GET_RENAME_FILE_REQUEST`(11)、`GET_DELETE_FILE_REQUEST`(19)、`FILE_CHANGE`(38) |
| 上传下载 | `GET_DOWNLOAD_FILE_REQUEST`(12) / `RESPONSE_HEADER`(13) / `RESPONSE_BODY`(14)、`GET_UPLOAD_FILE_REQUEST_HEADER`(15) / `RESPONSE_HEADER`(16) / `REQUEST_BODY`(17) / `RESPONSE`(18) |
| 媒体库与缩略图 | `GET_THUMBNAIL_REQUEST`(3)、`GET_PHOTO_LIB_REQUEST`(4)、`GET_VIDEO_LIB_REQUEST`(5)、`GET_AUDIO_LIB_REQUEST`(6)、`PHOTO_LIB_CHANGE`(20)、`AUDIO_LIB_CHANGE`(21)、`VIDEO_LIB_CHANGE`(22) |
| 监控与同步 | `MONITOR_FOLDER_REQUEST`(23) / `RESPONSE_HEADER`(24) / `RESPONSE`(25)、`PHOTO_SYNC_REQUEST`(37)、`SYNC_MONITOR_REQUEST`(39)、`UPDATE_FILE_INFO`(40) / `RESPONSE`(41) |
| 剪贴板 | `GET_CLIPBOARD_REQUEST`(26)、`POST_CLIPBOARD_REQUEST`(27)、`CLEAR_CLIPBOARD_REQUEST`(28)、`DELETE_CLIPBOARD_REQUEST`(29)、`CLIPBOARD_CHANGE`(30) |

配套枚举：`SSPFileEventType`（8 种，对应 Android `FileObserver`）、
`SSPFileIOError`（12 种）、`SSPFileIOPermission`、`SSPHandShakeTrustType`、
`SSPCancelErrorCode`、`SSPFileType`、`SSPFileChangeStatus`（5 种）。

## 6. 关键业务机制

- **文件传输**：`SSPDataRange{offset,length}` 支持断点/分块；`gzip` 标志对值得压缩的
  类型启用压缩；`need_md5` / `data_md5` 做整段校验；上传为覆盖语义（已存在则删旧文件）；
  `is_sync` 维护同步状态；`is_trash` 支持移入回收站；`SSPFileIOError` 覆盖磁盘不足、
  MD5 失败、SD 卡权限、路径/文件名过长（文件名 255、路径 4096）、系统文件等。
- **媒体库**：手机读 MediaStore，返回 `SSPImageFile`（含宽高、Exif orientation、
  thumbnail bytes、经纬度、mini_thumb_magic）、`SSPVideoFile`、`SSPAudioFile`（ID3 标签、
  时长、比特率、采样率、start_offset 用于 APE 音轨）、以及各自 Album；
  电脑端按需用 `GET_THUMBNAIL_REQUEST` 按 media id 或 path 拉缩略图。
- **剪贴板**：`SSPClipboard{ content(gzip 压缩), mstimestamp }`；支持取、发、清空、
  删除、以及 `CLIPBOARD_CHANGE` 变更回调，构成双端剪贴板同步。
- **变更订阅**：`MONITOR_FOLDER_REQUEST` 注册/注销目录监控（基于 `FileObserver`），
  手机端主动推 `MONITOR_FOLDER_RESPONSE` 的 `SSPFileEvent` 列表；媒体库变更、
  `SSPFileChange` 也由手机端推送。
- **照片自动同步**：`SSPPhotoSyncRequest{ pc_id, files(上次快照) }`，手机返回当前快照
  与 `is_first`；电脑端用 FMDB 存同步状态，断线后下次连接继续（UI 有「上次自动完全
  同步时间」「因为连接中断，照片同步已停止…下次连接时，会继续同步」）。
- **保活**：`SSPHeartBeatRequest/Response` 互报时间戳，主机在握手时下发
  `heartbeat_timeout_second`；超时即判定 `client dead`，发 `SFDeviceWillLeftNotification`。
  ADB 链路另有 `SFADBForwardKeepAliveOperation` 维持 forward 不被回收。
- **设备信息**：`SSPGetDeviceInfoResponse` 有 36 个字段，含型号、颜色、磁盘/内存、
  电量、根路径、品牌、Smartisan OS 版本、是否锁屏、外置 SD 卡权限、各类空间占用。
- **冲突规避**：与 Android File Transfer（MTP）互斥，UI 主动询问是否关闭它。

## 7. 连接状态机

```
[插线 / 开机 / 打开应用]
  ├─ USB-AOA 匹配成功 ──► 切配件模式 ─────────────┐
  ├─ USB 调试已授权 ──► 安装/启动传输服务 ────────┤
  └─ 同一局域网 ──► NSD/Bonjour 或扫码 ──────────┤
                                                 ▼
                              建立 SSP 通道 (TCP / bulk / ADB forward)
                                                 ▼
                   HandShake 01：交换 uuid、版本、enckey、心跳超时
                                                 ▼
                   HandShake 02：信任判定 + derived_key
        ┌── TRUST_NO / locked / needauth ──► 拒绝 / 等待用户操作
        └── TRUST_ONCE / TRUST_ALWAYS ────► result = base64(RSA('ok'))
                                                 ▼
              GET_DEVICE_INFO + 启动心跳 + 注册目录/媒体/剪贴板回调
                                                 ▼
                  文件、媒体库、缩略图、剪贴板、同步 请求-响应
                                                 ▼
                      QUIT_REQUEST / 心跳超时 / 拔线 / 取消
```

## 8. 外围服务（可剔除）

Sparkle 自动更新（`SUFeedURL`）、云端账户与统计（`api*.smartisan.com`、
`FRApptrackerURL`）、阿里云 OSS 反馈附件、闪念胶囊 `IdeaPills` 插件与讯飞语音。
这些与局域网互传主流程无关，新项目不必复刻。

## 9. 本报告的局限

- 全程静态分析，未抓包、未运行程序。
- 帧头字节布局、TLS 默认开关、ENCKEY/derived_key 算法、二维码载荷的具体编码格式、
  AOA 与 ADB 链路的优先级策略，均为推断。
- 安卓样本是第三方兼容实现，与官方原版手机端可能存在差异。
- 详见 `06-待验证问题与后续分析计划.md`。
