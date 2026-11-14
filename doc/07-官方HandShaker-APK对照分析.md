# 07 官方 HandShaker APK 对照分析（新增样本）

> 用户重新下载了 `tmp/HandShaker.apk`（5.5 MB）。本报告对它与前一份 APK 做身份鉴定、
> 协议版本对照，并把前序报告中若干「推断/未验证」升级为「事实」。

## 1. 结论速览

- **新 APK 是官方 Smartisan 系统应用**：证书 `O=smartisan`、包名
  `com.smartisanos.smartfolder.aoa`、`versionName=1.1.0`、
  `sharedUserId="android.uid.system"`、零广告 SDK。
- **前一份 APK 确认是第三方重打包**：证书组织为 `O=CCIC`（个人 CN/邮箱已略去）、包名
  `com.smartutils.smartfolder.airshare`、`2.5.5`、
  dex 中 741 处广告 SDK 字符串、额外定位权限、帮助页指向第三方站点。
- 新样本带来三项实质修订：手机端是**系统预置应用**；native 层硬编码 AES 混淆
  **确为官方实现**；「USB / Wi-Fi 跑同一套 SSP」有了官方代码的直接日志证据。
- 两份 proto **命令集完全一致（41 个）**，差异只有 3 处字段级演进，说明协议骨架长期稳定。

## 2. 样本身份鉴定

| 维度 | 新 APK（官方） | 旧 APK（重打包） |
| --- | --- | --- |
| 文件 | `tmp/HandShaker.apk`，5.5 MB | `tmp/` 下另一 APK，6.5 MB |
| 签名 subject（个人 CN/邮箱已略去） | `O=smartisan, OU=smartisan`（自签，北京） | `O=CCIC, OU=CCIC`（第三方重签名，非 smartisan） |
| 包名 | `com.smartisanos.smartfolder.aoa` | `com.smartutils.smartfolder.airshare` |
| versionName | `1.1.0` | `2.5.5` |
| `version.properties` | `VERSION_CODE=182`，2017-05-03 | `VERSION_CODE=401`，2020-10-08 |
| 构建信息 | `Created-By: Android Gradle 2.3.3`、`Built-By: Generated-by-ADT`，zip 时间戳规范化为 1980 | 2020 年时间戳 |
| 广告 SDK 字符串命中数 | **0** | **741**（ironsource / startapp / admob / apksum / easytinytech 等） |
| dex | 1.7 MB，11,805 行字符串 | 4.3 MB，40,891 行字符串 |
| 权限差异 | `CAMERA` + camera/autofocus/flash 等 uses-feature、`android.hardware.usb.accessory`、`sharedUserId=android.uid.system` | 多出 `ACCESS_COARSE_LOCATION`、`ACCESS_FINE_LOCATION`、`BIND_JOB_SERVICE`、`BOOT_COMPLETED` |
| 组件差异 | 无 HelpMac/HelpWin | 多 `HelpMacActivity` / `HelpWinActivity`、多个广告 Activity/Service、BootCompleteListener |
| assets | 三语 `smartisan_experience_plan_content{,_en,_tw}.html`、`share_image.png`、`version.properties` | 另含 `User_Manual_for_MAC_OS.html` / `User_Manual_for_WIN.html`，引导去第三方站点 |
| `res/xml` | 仅 `accessory_filter.xml` | 另有 `network_security_config.xml`（`cleartextTrafficPermitted=true`，因 targetSdk 升高） |
| `main/` | `main/proto/SmartSyncProtocol.proto` + `main/jni/{codex.c,codex.h,smartfolder.c}` | 同样附带，JNI 三份源码逐字节一致 |

**鉴定方法**：`openssl pkcs7 -inform DER -in META-INF/CERT.RSA -print_certs -noout`
读取签名证书；用 Python 解析二进制 AXML 的字符串池，取出 `package`、`versionName`、
`sharedUserId`、权限与组件名（无需 apktool/aapt）。

## 3. 三项实质修订

### 3.1 手机端是系统预置应用，而非普通安装应用

新 Manifest 明确带 `sharedUserId="android.uid.system"`。该属性要求 APK 使用
**平台签名**，与证书里的 `O=smartisan` 吻合；同时它能解释官方包申请
`WRITE_MEDIA_STORAGE`、`MOUNT_UNMOUNT_FILESYSTEMS` 这类系统级权限，以及
`uses-feature android.hardware.usb.accessory` 的声明。

推论【强推断】：Smartisan OS 手机里预置了这套 SSP 服务，因此官方手机上插线即可用，
无需用户安装任何东西。Mac 端通过 ADB 安装/启动的「传输服务」
（`com.smartisanos.smartfolder/.AdbForwardService`，包名**不带** `.aoa`、
`SmartFolder.apk`）应是面向**非锤子手机**的独立分发包。两者包名不同，
是否同一份代码的不同构建，静态样本不足以断定。

### 3.2 native 层硬编码 AES 混淆确属官方实现

- 7 个 ABI 的 `libsmartfolder.so` 与旧 APK **逐字节一致**（`cmp` 全部通过）。
- `main/jni/codex.c`、`codex.h`、`smartfolder.c` 三份源码也逐字节一致。
- 新 `.so` 中确有导出符号
  `Java_com_smartisanos_smartfolder_aoa_decoder_C_parseIoBuffer`。
- `smartfolder.c` 中 `parseIoBuffer` 用**硬编码的 AES-256 key/IV** 做 CBC 解密，
  `codex.h` 用 `#define aes_decrypt_cbc dtcc_5` 之类宏重命名符号做混淆。

因此 `doc/04-Android端APK对照分析.md` §6 的推断成立并升级为**事实**：
这不是重打包者塞进去的，而是官方客户端本身的做法。
`doc/06` 待验证清单第 12 项由此解决。

同时这也强化了 `doc/05` 的设计结论：不要把密钥硬编码在随包分发的 native 库里，
应改用标准 TLS + 短时配对码。

### 3.3 「传输层与协议层解耦」有了官方侧直接证据

官方 dex 中同时存在两条日志串：

```
USB SSPGetDeviceInfoResponse send
WIFI SSPGetDeviceInfoResponse send
```

以及 `SSPEventDispatcher.java` / `SSPEventListener.java`、`decode HANDSHAKE_FLAG`、
`SspPacket.java` / `SspReader` / `SspExecutorManager` / `SspFileTransferTask`、
`ADB_PORT`、`openAdb  port : `、`openAccessory`、`_handshaker_ssp._tcp.`、
`handshaker_ssp_`、`UsbAccessory`、`NsdManager`、`ServerSocket`。

即 USB 与 Wi-Fi 两条物理通道发出的是**同一个 SSP 消息**。
`doc/03` §1 的三层解耦由「强推断」升级为**事实**；也说明 ADB 通道
（`ADB_PORT` / `openAdb`）在 2017 年的官方 1.1.0 中就已经存在，
并非后期或第三方新增。

## 4. SSP 协议版本演进（2017 → 2020）

两份 proto 都是 `syntax = "proto2"`、`package smartsync`、**41 个 `SSPRequestType`
命令且命令名完全一致**。`diff -u` 只有 3 个 hunk：

| # | 位置 | 2017 官方 1.1.0 | 2020 重打包 2.5.5 |
| --- | --- | --- | --- |
| 1 | `SSPFile` | 字段到 `ext_data`(10) 为止 | 增加 `is_trash`(11)、`succeed`(12)、`error_code`(13)、`id`(14)，分别用于回收站删除、删除结果、删除错误码、媒体库文件 id |
| 2 | `SSPFileIOError` | 到 `FILE_IO_SDCARD_NO_PERMISSION`(10) | 增加 `FILE_IO_PATH_OR_NAME_TOO_LONG`(11)（文件名 255 / 路径 4096）、`FILE_IO_CANCEL_ACTION`(12) |
| 3 | `SSPDeleteFileRequest` / `Response` | `optional SSPFile file`（单文件删除） | `repeated SSPFile file`（批量删除） |

**解读【强推断】**：命令集在整个生命周期保持稳定，演进集中在删除/回收站/错误码这类
细粒度能力上，靠「加 optional 字段 + 改 optional→repeated」完成，正是 proto2
向后兼容的典型用法。这对新项目是重要参考：**协议骨架要早定、少改，扩展靠加字段**。

**局限**：较新的 proto 来自第三方重打包 APK，所以这 3 处差异同时可能混入
「版本演进」与「重打包者改动」两种因素，无法完全分离；中间官方版本的 proto 未取得。

## 5. 官方云端与外围端点（补充证据）

官方 dex 中的端点：

- 更新：`http://update.smartisanos.com/handshaker/update_info`
- 统计/日志：`http://auto.smartisan.com/v2/api/log?tid=`、
  `http://auto.smartisan.com/v2/api/report`、
  `https://dc.smartisan.com/v1/tracker/android_uid`、
  `https://dc.smartisan.com/v1/tracker/app`
- 配置：`http://setting.smartisan.com/config/app/i18n(_version)`
- 帮助/活动：`http://bbs.smartisan.com/thread-516359-1-1.html`（Mac 端也有同一条）、
  `http://www.smartisan.com/apps/gx.html?utm_source=handshaker&...`

与 Mac 端 `SUFeedURL`（`sf.smartisan.com/update.plist`）、
`FRApptrackerURL`（`dc.smartisan.com/v1/tracker/app`）、
`sf.smartisan.com/sf/release/apk` 相互对应。再次印证：
**账户/统计/自动更新是外围体系，不是局域网互传的必要条件**，`doc/05` 中把这些剔除是对的。

## 6. 三份样本的时间线

| 时间 | 样本 | 版本 | 性质 |
| --- | --- | --- | --- |
| 2017-05-03 | 官方系统 APK | 1.1.0 / code 182 | Smartisan OS 预置、平台签名 |
| 2018-03-29 | `HandShaker.app`（Mac） | 2.5.6 / build 408 | 官方桌面端 |
| 2020-10-08 | 第三方重打包 APK | 2.5.5 / code 401 | 兼容实现，带广告 |

三者不是同一构建配对。跨版本互通靠握手阶段的
`host_smart_sync_protocol_version` / `client_smart_sync_protocol_version` 与
`host_min_client_version` / `client_min_host_version` 协商。Mac 端文案
「传输服务版本低于已经安装的版本」「请根据手机端提示或扫描下面二维码升级手机中的
HandShaker」「请更新电脑端 HandShaker 程序后再尝试连接」正是协商失败的兜底提示。

## 7. 对前序报告的修订清单

| 报告 | 修订 |
| --- | --- |
| `01-分析范围与方法.md` §2 | 增加官方样本；旧 APK 的「第三方重打包」定性由签名证据确认 |
| `03-SSP协议与工作原理.md` §1 | 三层解耦由「强推断」升级为「事实」（官方日志串） |
| `04-Android端APK对照分析.md` §1/§8 | 「官方手机端是否也带同样 native 混淆」→ **确认为「是」**；补充系统应用身份 |
| `05-同等策略的新项目设计.md` | 结论不变；新增一条依据：官方也在 native 层硬编码密钥，因此更不应照抄 |
| `06-待验证问题与后续分析计划.md` | 第 12 项已解决；第 1–11、13 项仍待动态验证 |

## 8. 仍需注意的局限

- 新 APK 是 2017 年的 1.1.0 系统应用，早于 Mac 端 2.5.6；用它和 Mac 端 2.5.6
  逐字段对照时，proto 差异无法完全归因于版本演进。
- Mac 端 ADB 安装的「传输服务」`com.smartisanos.smartfolder` 原包仍未取得。
- 全程静态分析，未运行、未抓包；帧头字节布局、密钥派生、二维码载荷等仍见 `doc/06`。

## 9. 本次产物

`tmp/analysis/apk_new/`（解包目录）、`tmp/analysis/apk_new_manifest_strings.txt`、
`tmp/analysis/apk_new_classes_strings.txt`、`tmp/analysis/proto_diff.txt`。
按规则未删除或清理任何文件。
