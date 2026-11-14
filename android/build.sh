#!/usr/bin/env bash
# 不使用 Gradle：aapt2 link -> javac -> d8 -> zipalign -> apksigner
set -eo pipefail

SDK="$ANDROID_HOME"
if [ -z "$SDK" ]; then SDK="$ANDROID_SDK_ROOT"; fi
if [ -z "$SDK" ]; then SDK="$HOME/Library/Android/sdk"; fi
if [ ! -d "$SDK" ]; then
  echo "找不到 Android SDK：$SDK"
  echo "请设置 ANDROID_HOME，或把 SDK 放到默认位置。"
  exit 1
fi

BT=""
for v in 36.0.0 36.1.0 37.0.0 35.0.0 34.0.0; do
  if [ -x "$SDK/build-tools/$v/aapt2" ]; then BT="$SDK/build-tools/$v"; break; fi
done
if [ -z "$BT" ]; then echo "找不到 build-tools"; exit 1; fi

PLATFORM="$SDK/platforms/android-36/android.jar"
if [ ! -f "$PLATFORM" ]; then
  for d in "$SDK"/platforms/android-*; do
    if [ -f "$d/android.jar" ]; then PLATFORM="$d/android.jar"; fi
  done
fi
if [ ! -f "$PLATFORM" ]; then echo "找不到 android.jar"; exit 1; fi

OUT="$(cd "$(mktemp -d tmp/android-build.XXXXXX)" && pwd)"
mkdir -p "$OUT/classes" "$OUT/dex" "$OUT/gen"
echo "build dir : $OUT"
echo "sdk       : $SDK"
echo "build-tool: $BT"
echo "platform  : $PLATFORM"

"$BT/aapt2" link -o "$OUT/base.apk" \
  -I "$PLATFORM" \
  --manifest android/AndroidManifest.xml \
  --java "$OUT/gen" \
  --min-sdk-version 26 --target-sdk-version 36

find android/src "$OUT/gen" -name '*.java' > "$OUT/sources.txt"
javac -encoding UTF-8 -source 8 -target 8 -classpath "$PLATFORM" \
  -d "$OUT/classes" @"$OUT/sources.txt"

(cd "$OUT/classes" && jar cf "$OUT/classes.jar" .)
"$BT/d8" --lib "$PLATFORM" --release --output "$OUT/dex" "$OUT/classes.jar"
cp "$OUT/dex/classes.dex" "$OUT/classes.dex"
(cd "$OUT" && zip -q base.apk classes.dex)

"$BT/zipalign" -f 4 "$OUT/base.apk" "$OUT/aligned.apk"

# 固定调试密钥：复用同一把，保证每次构建签名一致，可 adb install -r 覆盖
KS="tmp/handover-debug.keystore"
if [ ! -f "$KS" ]; then
  keytool -genkeypair -keystore "$KS" -storepass android -keypass android \
    -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Android Debug,O=Android,C=US" >/dev/null 2>&1
fi

"$BT/apksigner" sign --ks "$KS" --ks-pass pass:android --key-pass pass:android \
  --out "$OUT/HandoverDemo.apk" "$OUT/aligned.apk"

cp "$OUT/HandoverDemo.apk" tmp/HandoverDemo.apk
echo
echo "APK 已生成 : tmp/HandoverDemo.apk"
echo "安装       : adb install -r tmp/HandoverDemo.apk"
echo "转发端口   : adb forward tcp:10086 tcp:10086"
echo "启动       : adb shell am start -n com.handover.demo/.MainActivity"
