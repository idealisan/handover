# 04 Android 端 APK 对照分析

> 安卓样本位于 `tmp/` 目录（包名 `com.smartutils.smartfolder.airshare`，版本 2.5.5，
> `assets/version.properties` 中 `VERSION_CODE=401`，构建时间 2020-10-08）。
> 内部代码包名仍为 `com.smartisanos.smartfolder`。
>
> 修订：后续取得的官方 APK 分析见 `07-官方HandShaker-APK对照分析.md`。该报告确认
> 官方客户端同样带有本文 §6 所述的 native 混淆，并把本文 §8 中此项由「未验证」升级为事实。

## 1. 样本性质与可信度边界

**重要【事实】**：这不是锤子官方原版手机端应用，而是一个**与 SSP 协议兼容的
第三方/重打包实现**，依据如下：

- 包名是 `com.smartutils.smartfolder.airshare`，文件名带第三方分发站标识。
- 内含 `ironsource`、`startapp`、`google ads` 等广告 SDK 与大量广告 Activity/Service。
- `assets/User_Manual_for_MAC_OS.html` / `User_Manual_for_WIN.html` 让用户去
  `easytinytech.com` 下载「Handshaker for MAC」，而非锤子官方渠道。
- 构建时间 2020 年，晚于 Mac 端样本的 2018 年；版本号 2.5.5 与 Mac 端 2.5.6 也不一致。

但它**直接附带了完整的 `main/proto/SmartSyncProtocol.proto`**，并且 dex 中的
`SmartSyncProtocolProtos.java`、`SSP*` 命令枚举、`_handshaker_ssp._tcp` 等与 Mac 端
`SmartFinderCore` 的类名、字符串完全对应。因此用它来还原**协议与安卓侧行为**是可靠的，
凡涉及官方实现细节的地方都应标注为推断。

## 2. 目录结构

```
AndroidManifest.xml          二进制 AXML，用 Python 解出字符串池
classes.dex                  单 dex，4.3 MB
resources.arsc               218 KB
assets/                      version.properties、用户手册 HTML、share_image.png
lib/<7 个 ABI>/libsmartfolder.so   arm64-v8a / armeabi-v7a / armeabi /
                                   mips / mips64 / x86 / x86_64
main/proto/SmartSyncProtocol.proto  ← 协议定义（741 行）
main/jni/codex.c / codex.h / smartfolder.c  ← native 源码
res/xml/accessory_filter.xml       ← AOA 配件过滤
res/xml/network_security_config.xml
res/raw/beep.ogg / zxing_beep.ogg ← 扫码提示音
META-INF/MANIFEST.MF / CERT.SF / CERT.RSA
```

**注意**：`main/proto/` 与 `main/jni/` 这种源码目录出现在发布包里很不寻常，
一般来自构建产物未清理。它恰好给了本次分析最完整的一手材料。

## 3. 协议定义：最权威的证据

`main/proto/SmartSyncProtocol.proto` 全文 741 行，包含：

- 数据结构：`SSPFile`、`SSPImageFile`、`SSPAudioFile`、`SSPVideoFile`、
  `SSPImageAlbum`、`SSPAudioAlbum`、`SSPVideoAlbum`、`SSPDataRange`、`SSPFileEvent`、
  `SSPClipboard`、`SSPFileChangeItem` 等。
- 枚举：`SSPRequestType`（41 个命令）、`SSPFileEventType`（8）、`SSPFileIOError`（12）、
  `SSPFileIOPermission`、`SSPHandShakeTrustType`（6）、`SSPCancelErrorCode`、
  `SSPFileType`、`SSPFileChangeStatus`（5）。
- 全部请求/响应消息，含两轮握手、心跳、设备信息、目录、上传下载、媒体库、
  缩略图、剪贴板、目录监控、照片同步、实时同步。

它明确写了两点关键设计：

1. 「定义里出现的 timestamp 都是标准 unix timestamp」「文件大小单位是 byte」。
2. 大文件传输**不走** `bytes` 字段，而是「session_id + binary 方式传输」
   （`SSPDownloadFileResponseBody` / `SSPUploadFileRequestBody` 两处注释均被注释掉了）。

Mac 端 `SmartFinderCore` 的类名清单（`SSPHandShakeRequest01` …
`SSPUpdateFileResponse`、`SSPGetClipboardRequestOperation` 等）与该 proto 一一对应，
说明**两端共享同一份 .proto，分别用 Objective-C 与 Java 生成代码**。这是整个项目最关键
的工程决策。

## 4. Manifest、权限与 AOA

解出的权限（`apk_manifest_strings.txt`）：

`ACCESS_WIFI_STATE`、`INTERNET`、`WRITE_EXTERNAL_STORAGE`、`READ_EXTERNAL_STORAGE`、
`ACCESS_ALL_DOWNLOADS`、`WAKE_LOCK`、`SYSTEM_ALERT_WINDOW`、`ACCESS_NETWORK_STATE`、
`WRITE_MEDIA_STORAGE`、`GET_PACKAGE_SIZE`、`READ_PHONE_STATE`、
`ACCESS_COARSE_LOCATION`、`ACCESS_FINE_LOCATION`、`MOUNT_UNMOUNT_FILESYSTEMS`、
`BOOT_COMPLETED` 等。

主要组件：

| 组件 | 作用 |
| --- | --- |
| `com.smartisanos.smartfolder.aoa.FolderApp` | Application |
| `...aoa.MainActivity` | 启动入口（LAUNCHER） |
| `...aoa.activity.SettingsActivity` / `SwitchLanguageActivity` / `UserExperienceActivity` / `HelpMacActivity` / `HelpWinActivity` | 设置、语言、帮助 |
| `...aoa.qrcode.ScanActivity` | 扫码（ZXing / journeyapps barcodescanner） |
| `...aoa.service.ConnectionManagerService` | **连接与协议主服务** |
| `...aoa.service.MediaScannerService` | 媒体扫描 / 通知系统相册刷新 |
| `...aoa.service.UiDialogService` | 信任授权弹窗（对应握手 `TRUST_WAITING`） |

Intent filter：`android.hardware.usb.action.USB_ACCESSORY_ATTACHED` /
`USB_ACCESSORY_DETACHED`。`res/xml/accessory_filter.xml` 解出的内容为：

```
manufacturer = Smartisan
model        = HandShaker
version      = 1.0
```

这与 Mac 端 `Accessory Identification sent.` 时发送的 `Smartisan` / `HandShaker` 完全一致，
**双向印证了 USB-AOA 通道**（见 `03-SSP协议与工作原理.md` §2.1）。

`network_security_config.xml`：`base-config cleartextTrafficPermitted="true"`，
允许明文 HTTP，与局域网自建服务一致。

## 5. dex 中的关键类与字符串

- 协议/传输：`SmartSyncProtocolProtos.java`、`SspPacket.java`、`SspReader`、
  `SspExecutorManager`、`SspTask`、`SspFileTransferTask`、
  `Reader cannot read packet anymore, disconnecting...`、
  `RunServerSocket...... mSocket.accept return null!!??`、
  `Start Wi-Fi ServerSocket...`、`ServerSocket is already running`。
- 服务发现：`_handshaker_ssp._tcp.`、`NsdManager`、`NsdServiceInfo`、
  `registerService` / `unregisterService`、
  `cdoStartNsdBroadcast fail, maybe has been registered or serversocket create fail`。
- AOA：`UsbAccessory`、`AccessoryManager.java`、`openAccessory succeeded`、
  `Open accessory FAILED, may be caused by duplicated usb connection intent`、
  `Close fd of accessory failed.`。
- 握手与信任：`HANDSHAKE_REQUEST_01/02` / `RESPONSE_01/02`、`HEART_BEAT_REQUEST`、
  `TRUST_WAITING/UNKNOW/NO/ONCE/ALWAYS/REMOVE`、`MESSAGE_TRUST_TIMEOUT`、
  `derivedKey`、`RSA/ECB/PKCS1Padding`、`SHA256withRSA`、`RSAPublicKeySpec`、
  `rsa verify failed`、`writeKeyExchangeInfo====rsaResultStr===`。
- 会话：`sessionId`、`session_id`、`clientSessionId`、`sessionId[`、`getSessionId` /
  `setSessionId`、`downloadFile register sessionId =`、`stop sessionId =`。
- 剪贴板：`ClipboardHandler`、`ACTION_CLIPBOARD_COPY_HISTORY`、`CLIPBOARD`、
  `CLIPBOARD_CHANGE`、`GET_CLIPBOARD_REQUEST`、`CLEAR_CLIPBOARD_REQUEST`、
  `DELETE_CLIPBOARD_REQUEST`、`ClipboardManager`。
- 扫码：`com.journeyapps.barcodescanner.CaptureActivity`、`SCAN_RESULT`、
  `BarcodeFormat.java`、`res/raw/zxing_beep.ogg`。
- 其它：`HandShake_test_write_permission_`（写权限探测）、
  `/smartisan/smartfolder/`、`/smartisan/smartfolder/share/`（工作目录）、
  `HandShaker`、`/storage/emulated/0`（Mac 端同样有该路径字符串）。

## 6. JNI / native 层：混淆与硬编码密钥

`main/jni/codex.h` 是 Brad Conte 的公开 AES 实现头文件，但用宏把符号全部重命名以做混淆：

```c
#define aes_key_setup        kysp_1
#define aes_decrypt_cbc      dtcc_5
#define aes_encrypt_cbc      etcc_4
...
```

`main/jni/smartfolder.c` 只有一个 JNI 函数：

```c
Java_com_smartisanos_smartfolder_aoa_decoder_C_parseIoBuffer(...)
```

它把传入的 byte 数组用**硬编码的 AES-256 key 与 IV** 做 CBC 解密后返回。
也就是说，接收侧有一层「native 解码」，`SspReader`/`parseIoBuffer` 会先解开这层再交给协议层。
dex 里也确实存在 `parseIoBuffer` 字符串。

**评价【推断】**：这是把密钥藏进 `.so` + 重命名符号来增加静态分析成本的做法，
并非真正的安全边界（密钥随包分发，任何人都能提取）。新项目**不要照抄**，
应改用标准 TLS + 短时配对码，见 `05-同等策略的新项目设计.md`。

## 7. 与 Mac 端的对照表

| 能力 | Mac 端（SmartFinderCore） | Android 端 |
| --- | --- | --- |
| 协议生成代码 | `SSP*`（GPBMessage 子类） | `SmartSyncProtocolProtos.java` |
| 协议定义 | 编译进 framework | **源码 `main/proto/SmartSyncProtocol.proto` 随包附带** |
| 帧读写 | `SSPRequestOperation` / `SSPManager` | `SspPacket` / `SspReader` / `SspExecutorManager` |
| 服务发现 | `NSNetServiceBrowser` browse `_handshaker_ssp._tcp` | `NsdManager` registerService `_handshaker_ssp._tcp.` |
| TCP | `GCDAsyncSocket`（连 + `didAcceptNewSocket`） | `java.net.ServerSocket`（accept） |
| USB | `libusb` + AOA 控制请求 + bulk 端点 | `UsbAccessory` + `USB_ACCESSORY_ATTACHED` |
| ADB 转发 | 自带 `adb`、`adb forward tcp:10086/19999` | `.AdbForwardService`（由 Mac 端拉起） |
| 握手/RSA | OpenSSL 1.0.2d、`enckey` / `derived_key` | `RSA/ECB/PKCS1Padding`、`SHA256withRSA`、`derivedKey` |
| 信任弹窗 | 显示二维码/提示用户在手机上点「信任」 | `UiDialogService`、`TRUST_*` |
| 本地存储 | `FMDB` 保存设备与同步状态 | SQLite / 快照（推断） |
| 媒体库 | `GET_*_LIB_REQUEST` 消费方 | MediaStore 生产方 |

## 8. 证据与局限

- 【事实】proto 全文、权限、组件、AOA 过滤、native 源码、类/字符串清单。
- 【强推断】两端共享同一份 proto、AOA 由配件过滤自动拉起服务、`10086` 为 SSP 端口。
- 【推断/未验证】`parseIoBuffer` 解密的是全部 SSP 帧还是仅密钥交换材料；
  广告 SDK 是否改动过协议逻辑。
- 【已确认】官方手机端同样带有该 native 混淆：见 `07-官方HandShaker-APK对照分析.md`
  （官方 1.1.0 系统 APK 的 JNI 源码与 7 个 ABI `.so` 与本样本逐字节一致）。
- 建议的动态验证见 `06-待验证问题与后续分析计划.md`。
