# 09 安卓端 APK 构建与联调

> 目标：在 Android 16（API 36）虚拟机上跑一个能与 Python demo 通信的安卓端。
> 现有官方/第三方 APK 均不可用，因此在本仓库内用无 Gradle 的方式自建了一个最小 APK。

## 1. 现有 APK 的实测结果

测试设备：Android 16（API 36），arm64-v8a，三星 SM-A536B，通过 `adb connect 127.0.0.1:6520` 接入。

| 样本 | targetSdk | 结果 |
| --- | --- | --- |
| `tmp/HandShaker.apk`（官方 1.1.0） | 22 | 安装失败：`INSTALL_FAILED_DEPRECATED_SDK_VERSION: App package must target at least SDK version 24, but found 22` |
| `tmp/` 下的重打包 2.5.5 | 29 | 安装成功，但启动即崩溃：`ClassNotFoundException: android.support.v4.util.SimpleArrayMap`，`FolderApp.<clinit>` 初始化失败 |

结论：两者都无法用于 Android 16 联调。官方包受最低 targetSdk 限制，重打包包依赖的旧 support 库
在 Android 16 上缺失。因此需要自建 APK。

## 2. 工具链

本机已有完整 Android SDK（默认位置 `$HOME/Library/Android/sdk`）：

- build-tools 36.0.0（aapt2 / d8 / zipalign / apksigner）
- platform android-36（android.jar）
- platform-tools（adb）
- JDK 17（javac / keytool / jar）

**不使用 Gradle**（本机未安装，且无需为最小 APK 引入）。构建链路：

```
aapt2 link  ->  javac  ->  jar + d8  ->  zip(classes.dex)  ->  zipalign  ->  apksigner
```

构建脚本为 `android/build.sh`。它把中间产物放在 `tmp/android-build.XXXXXX`（`mktemp` 新建的
独立目录），**不删除任何已有文件**；SDK 优先读 `ANDROID_HOME` / `ANDROID_SDK_ROOT`，
否则回落到 `$HOME/Library/Android/sdk`。调试密钥固定在 `tmp/handover-debug.keystore`，
每次构建复用同一把，保证 `adb install -r` 覆盖安装不会因签名变化而失败。

## 3. 构建与安装

```
bash android/build.sh
adb install -r tmp/HandoverDemo.apk
# 授予真实存储/相册权限
for p in android.permission.READ_MEDIA_IMAGES android.permission.READ_MEDIA_VIDEO \
         android.permission.READ_MEDIA_AUDIO android.permission.POST_NOTIFICATIONS; do \
  adb shell pm grant com.handover.demo "$p"; done
adb shell appops set com.handover.demo MANAGE_EXTERNAL_STORAGE allow
adb shell am force-stop com.handover.demo
adb shell am start -n com.handover.demo/.MainActivity
adb forward tcp:10086 tcp:10086
```

产物：`tmp/HandoverDemo.apk`（调试密钥签名，仅用于测试；不用于发布）。
`MANAGE_EXTERNAL_STORAGE` 是特殊权限，正式使用需在系统设置里开启「所有文件访问」；
界面也提供「授权文件访问」按钮跳转设置页。

## 4. APK 设计

| 项 | 值 |
| --- | --- |
| 包名 | `com.handover.demo` |
| minSdk / targetSdk | 26 / 36 |
| 组件 | `MainActivity`（程序化 UI）+ `PhoneService`（前台服务，`dataSync`） |
| 权限 | MANAGE_EXTERNAL_STORAGE、READ_MEDIA_IMAGES/VIDEO/AUDIO、READ/WRITE_EXTERNAL_STORAGE（旧版）、INTERNET、ACCESS_NETWORK_STATE、CHANGE_WIFI_MULTICAST_STATE、FOREGROUND_SERVICE、FOREGROUND_SERVICE_DATA_SYNC、POST_NOTIFICATIONS |
| 端口 | TCP 10086，绑定 0.0.0.0 |
| 发现 | `NsdManager` 注册 `_handshaker_ssp._tcp`，并持有 MulticastLock |
| 存储 | **设备公共存储 `/sdcard`**（`Environment.getExternalStorageDirectory()`），无示例/占位文件 |
| 剪贴板 | 系统剪贴板 + 内存缓存（Android 10+ 后台读取受限，GET 返回缓存） |
| 设备信息 | Build、BatteryManager、StatFs |

安卓端**真实访问系统目录**：申请并获取「所有文件访问」（MANAGE_EXTERNAL_STORAGE）与
相册/媒体权限后，浏览的是手机公共存储根目录 `/sdcard`，能看到 DCIM、Pictures、
Download、Music、Documents 以及用户截图等真实文件。回收站放在应用专属目录，
不污染公共存储。运行时权限在 `MainActivity` 申请，「所有文件访问」需跳转系统设置
（测试时用 `appops set com.handover.demo MANAGE_EXTERNAL_STORAGE allow` 授予）。
早期版本的应用专属虚拟目录与示例文件已按需求删除（见 doc/10）。

## 5. 协议实现

与 Python 端逐字节一致：HOVR magic、14 字节帧头、flags、session_id、length，
控制帧为 UTF-8 JSON，数据帧为裸字节。

| 方向 | 命令 |
| --- | --- |
| 握手 | HELLO / PAIR_REQUEST（ONCE / ALWAYS / NO） |
| 保活 | HEARTBEAT |
| 设备与文件 | GET_DEVICE_INFO、LIST_DIR、MKDIR、RENAME、DELETE |
| 剪贴板 | GET_CLIPBOARD、POST_CLIPBOARD、CLEAR_CLIPBOARD |
| 传输 | UPLOAD_INIT → DATA… → UPLOAD_DONE；DOWNLOAD_INIT → DATA… → DOWNLOAD_DONE；CANCEL |
| 推送 | FILE_CHANGE、CLIPBOARD_CHANGE、DOWNLOAD_DONE、DOWNLOAD_ABORT |

实现要点：

- 每个 `X` 请求回复 `X_ACK`，带 `seq` 与 `session_id`；客户端按 `seq` 匹配。
- 上传时数据帧先于 `UPLOAD_DONE` 到达（同一 TCP 连接有序），服务端在 done 时校验 MD5。
- 下载由独立线程发数据帧，每 64 KB 停 6 ms，便于取消与进度展示。
- 路径统一做 canonical 校验，拒绝越出 `/sdcard` 根目录。

## 6. 联调结果

1. 安装：`Success`。
2. 启动：`MainActivity` 正常显示，前台服务启动，日志出现
   `HandoverDemo: nsd registered: Handover Demo`。
3. 端口转发：`adb forward tcp:10086 tcp:10086` 成功。
4. Python 探测：

```
.venv/bin/python run_demo.py --probe 127.0.0.1:10086
PASS  连接 + HELLO  need_trust
PASS  信任握手  ok
PASS  设备信息  SM-A536B
PASS  目录浏览  13 项          # /sdcard 真实根目录
PASS  上传下载往返  done
PASS  剪贴板  1
探测结果：6/6 通过
```

5. 安卓端落盘核验：`probe.txt` 等文件写入公共存储，`probe from desktop` 内容 MD5 往返一致。
6. Web GUI 联调：`GET /` 返回 200；通过 `/api/action` 依次执行 connect → pair → list_dir，
   状态从 `need_trust` 变为 `paired`，设备型号 `SM-A536B`，目录列出
   `/sdcard` 真实内容：Alarms / Audiobooks / DCIM / Documents / Download / Movies /
   Music / Notifications / Pictures / Podcasts / Recordings / Ringtones 等。
7. **真实截图可见**：`/Pictures/Screenshots/Screenshot_20261114-042107_Handover Demo.png`
   （84925 字节）可在界面浏览、下载，且与设备原图字节一致；双向上传亦落到公共存储。

## 7. 已知限制

- **剪贴板后台读取**：Android 10+ 限制后台应用读剪贴板，GET_CLIPBOARD 返回的是服务内缓存，
  不是系统实时内容；POST 会同时写入系统剪贴板。
- **mDNS**：虚拟机与主机之间不一定能互相收到组播，联调实际走 `adb forward`；
  同一局域网的真机可尝试直接用 NSD 发现。
- **前台服务**：息屏或厂商省电策略可能限制长连接；演示中保持 Activity 在前台最稳。
- **无加密**：当前是明文 TCP，没有 TLS 与配对密钥，仅用于本机/可信局域网演示。
- **签名**：使用构建时生成的调试密钥，不能用于分发。
- **协议不兼容官方**：帧头与 JSON 控制面是本项目自定义的，不能与 HandShaker 官方端互通。

## 8. 复现步骤

```
# 1. 确认设备
adb connect 127.0.0.1:6520
adb devices -l

# 2. 构建并安装
bash android/build.sh
adb install -r tmp/HandoverDemo.apk

# 3. 启动并转发
adb shell am start -n com.handover.demo/.MainActivity
adb forward tcp:10086 tcp:10086

# 4. 探测
.venv/bin/python run_demo.py --probe 127.0.0.1:10086

# 5. 或者直接开 GUI，在界面里手动连接 127.0.0.1:10086
.venv/bin/python run_demo.py
```

## 9. 产物与清理

- 源码：`android/AndroidManifest.xml`、`android/src/com/handover/demo/*.java`、`android/build.sh`。
- 构建产物：`tmp/HandoverDemo.apk`、`tmp/android-build.*`（均被 `.gitignore` 排除）。
- 全程未删除或清理任何文件；结束时可按需自行删除 `tmp/` 下的构建目录与 APK。
