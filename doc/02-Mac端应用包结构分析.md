# 02 Mac 端应用包结构分析

样本：`tmp/HandShaker.app/`（HandShaker 2.5.6，构建 408，2018-03-29 签名，
Developer ID 签名的 x86_64 Mach-O，最低系统 10.10，SDK 10.12）。

## 1. 目录结构与职责

| 目录 | 体积 | 内容 |
| --- | --- | --- |
| `Contents/MacOS/` | 3.3 MB | 主可执行文件 `HandShaker` |
| `Contents/Frameworks/` | 13 MB | 自研 framework 与第三方库 |
| `Contents/Resources/` | 8.4 MB | 566 个文件中的大部分：244 个 tiff、116 个 strings、91 个 nib、23 个 plist |
| `Contents/PlugIns/` | 7.3 MB | `IdeaPills.plugin`（闪念胶囊相关插件） |
| `Contents/Library/LoginItems/` | 6.1 MB | 开机自启辅助程序 |
| `Contents/XPCServices/` | 564 KB | `SmartFinderAudioPlayer.xpc` |
| `Contents/_CodeSignature/` | 104 KB | 签名与资源清单 |

`NSPrincipalClass` 为 `SFApplication`，`NSMainNibFile` 为 `MainMenu`，是典型 Objective-C
AppKit 应用。

## 2. 关键元数据

`Contents/Info.plist` 要点：

- `CFBundleIdentifier`：`com.smartisan.smartfindercommon`（内部产品代号 SmartFinder）。
- `CFBundleShortVersionString` 2.5.6 / `CFBundleVersion` 408。
- `NSAppTransportSecurity` → `NSAllowsArbitraryLoads = true`：允许明文 HTTP，
  与局域网内自建 HTTP 服务/非 TLS 通道一致。
- `SUFeedURL`：`https://sf.smartisan.com/update.plist`，Sparkle 自动更新。
- `FRApptrackerURL` / `FRFeedbackURL`：统计上报与用户反馈的云端地址。
- `LSMinimumSystemVersion` 10.10。

entitlements：

- `com.apple.security.network.client` 与 `network.server` **同时开启**：既能主动连接，
  也能监听端口接受连接。这一点对后面理解 Wi-Fi 模式很关键。
- `com.apple.security.application-groups`、`files.bookmarks.app-scope`、
  `files.user-selected.read-write`：跨进程共享与文件访问授权。

主程序链接的自研库（`otool -L`）：

```
@rpath/HandShakerComponent.framework
@rpath/SmartFinderCore.framework
@rpath/SmartFinderNetwork.framework
@rpath/FMDB.framework
@rpath/Sparkle.framework
```

同时链接 `CoreWLAN`、`IOKit`、`SystemConfiguration`、`Security`、`CoreLocation` 等系统框架，
分别对应 Wi-Fi 信息、USB 设备、网络状态、证书/RSA、定位（用于 Wi-Fi 权限）。

## 3. 各 Framework 的角色（证据：类名与字符串）

| Framework | 角色 | 关键证据 |
| --- | --- | --- |
| `SmartFinderCore` | **协议与设备的核心层**，约 203 KB 字符串 | `SSPManager`、`SSPRequestOperation`、`SFWifiDeviceManager`、`SFUSBDeviceManager`、`SFADBManager`、`SFADBForwardOperation`、`SFFile` / `SFDirectoryFile` / `SFFileTransferItem`；内置 `adb` 与 OpenSSL 1.0.2d |
| `SmartFinderNetwork` | 云端账户/API 层 | 域名 `api.smartisan.com`、`api-sync-cloud.smartisan.com`、`api-account.smartisan.com`、`account.smartisan.com`、`tpassword.smartisan.com`、`small.smartisan.com`；`requestMethod` / `requestSerialType` 等 AFNetworking 风格封装 |
| `HandShakerComponent` | 通用网络与 UI 组件 | 内嵌 `GCDAsyncSocket` / `GCDAsyncUdpSocket`（CocoaAsyncSocket，含 `joinMulticastGroup`）、AFNetworking、WebView 相关类 |
| `FMDB` | SQLite 封装 | 本地缓存设备/同步状态 |
| `Sparkle` | 自动更新 | `Autoupdate.app`、`SUFeedURL` |
| `AliyunOSSOSX`（在 Helper 内） | 阿里云 OSS 上传 | `x-oss-*` 请求头，用于反馈附件/云端文件 |
| `EZAudioOSX` / `LAME` / `libMSC.dylib` | 音频播放、MP3 编码、讯飞语音 | 属于音乐播放与语音输入插件，非传输核心 |

`SmartFinderCore.framework/Versions/A/Resources/` 里还有三个值得注意的文件：

- `adb`：1.6 MB 的 Mach-O x86_64，**电脑端自带 adb 可执行文件**，说明 USB 链路不依赖
  用户机器上安装 Android SDK / adb。
- `VERSION`：`1.0.2d`；`LICENSE`：OpenSSL 许可证。即核心层静态带入了 OpenSSL 1.0.2d，
  用于 RSA、MD5、证书等。
- `rsa.h.bak`：OpenSSL RSA 头文件备份，佐证握手阶段使用 RSA。

## 4. 辅助进程与插件

- `Contents/Library/LoginItems/HandShakerAgent.app`：登录项，用于开机/插线时唤起主程序。
- `Contents/Library/LoginItems/...IdeaPillsHelper.app`：闪念胶囊助手，内含 `roots.pem`
  与 `AliyunOSSOSX.framework`，负责云端同步。
- `Contents/XPCServices/SmartFinderAudioPlayer.xpc`：独立 XPC 音频播放器，带
  `Flac.plugin` / `MonkeysAudio.plugin`，避免无损解码崩溃影响主进程。
- `Contents/PlugIns/IdeaPills.plugin`：闪念胶囊（Idea Pills）桌面端插件，与传输主流程无关。

**结论【事实】**：主传输功能集中在 `SmartFinderCore` + `HandShakerComponent` 两个 framework，
`SmartFinderNetwork` 只负责云端账户与统计，属于外围能力。新项目若只想复刻互传，
可以完全不要云账户体系。

## 5. 资源文件中的功能性线索

- `Resources/matchingdevices.plist`：一张 USB 厂商表，条目形如
  `{ deviceName, matchingDictionary: { IOProviderClass: IOUSBDevice, idVendor: <数字>, idProduct: "*" } }`，
  覆盖 Smartisan、HTC、HUAWEI、GOOGLE、ASUS、ACER 等大量 `idVendor`。
  这是 `IOKit` 的 USB 设备匹配字典，用于插线时识别「可能是安卓手机」。
- `Resources/apps.plist`：常见安卓应用包名 → SD 卡目录的映射表（QQ、微信、微博、
  淘宝、WPS、高德、AirDroid 等），用于把手机文件按「应用归属」归类展示。
- `Resources/SFSmartAlbumList.plist`：智能相册路径，`/ROOT__DIR/DCIM/Camera`、
  `/ROOT__DIR/Pictures/Screenshots`。`/ROOT__DIR/` 是协议层对手机存储根目录的占位符。
- `Resources/Intro` 系列图片：`intro_wifi.tiff`、`intro_usb.tiff`、`intro_trust_alert.tiff`、
  `qr_click.tiff`、`wifi_phone_smartisan_s.tiff`，与引导页的两种连接方式、信任弹窗、
  扫码连接相对应。
- `zh-Hans.lproj/Localizable.strings`（850 行）里有完整的功能词表，直接暴露产品行为：
  - 「请打开 HandShaker 手机客户端，扫描上方二维码连接」「二维码已过期，请点击刷新」
  - 「通过 USB 连接」「也可通过 USB 数据线连接到手机」「继续使用无线传输」
  - 「使用 HandShaker 需要在手机中安装数据传输服务应用，请在系统设置中打开允许从
    「未知来源」安装应用」「无法安装应用「传输服务」」「传输服务签名不一致」
  - 「请在手机弹出的『允许 USB 调试』对话框点击『确定』按钮」
  - 「手机『%@』拒绝信任这台电脑」「通过无线网络连接过的设备将出现在这里。你可以在
    与手机建立连接时选择『信任』」
  - 「手机剪贴板为空」「可以在这里输入文字，添加至手机剪贴板」「剪贴板」
  - 「已开始自动同步」「自动完全同步」「上次自动完全同步时间」
  - 「下载文件 MD5 检测错误」「建议使用 USB 数据线连接」「暂不支持连接多台设备」
  - 「Android 文件传输可能与 HandShaker 有冲突」（与 MTP/Android File Transfer 互斥）

**结论【强推断】**：产品提供 USB 与 Wi-Fi 两条主链路、扫码作为发现手段的补充、
需在手机安装「传输服务」应用、需要用户在手机上确认信任、支持剪贴板与照片自动同步、
单连接设备、以及 MD5 校验。

## 6. 与本报告后续章节的衔接

- 三条传输通道的实现细节见 `03-SSP协议与工作原理.md`。
- Mac 端 `SSP*` 类与安卓端 proto 定义的逐项对应见 `04-Android端APK对照分析.md`。
- 云账户、统计、自动更新、闪念胶囊属于外围，新项目设计里会明确剔除，见
  `05-同等策略的新项目设计.md`。
