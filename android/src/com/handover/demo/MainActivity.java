package com.handover.demo;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public class MainActivity extends Activity {
    private TextView status;
    private TextView info;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable tick = new Runnable() {
        public void run() {
            refresh();
            handler.postDelayed(this, 1000);
        }
    };

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        buildUi();
        requestRuntimePermissions();
        startPhoneService();
        handler.post(tick);
    }

    @Override
    protected void onResume() {
        super.onResume();
        refresh();
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacks(tick);
        super.onDestroy();
    }

    /** 申请相册/通知等运行时权限；「所有文件访问」需单独跳转系统设置。 */
    private void requestRuntimePermissions() {
        List<String> need = new ArrayList<String>();
        if (Build.VERSION.SDK_INT >= 33) {
            if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED) {
                need.add(Manifest.permission.POST_NOTIFICATIONS);
            }
            if (checkSelfPermission(Manifest.permission.READ_MEDIA_IMAGES)
                    != PackageManager.PERMISSION_GRANTED) {
                need.add(Manifest.permission.READ_MEDIA_IMAGES);
            }
            if (checkSelfPermission(Manifest.permission.READ_MEDIA_VIDEO)
                    != PackageManager.PERMISSION_GRANTED) {
                need.add(Manifest.permission.READ_MEDIA_VIDEO);
            }
            if (checkSelfPermission(Manifest.permission.READ_MEDIA_AUDIO)
                    != PackageManager.PERMISSION_GRANTED) {
                need.add(Manifest.permission.READ_MEDIA_AUDIO);
            }
        } else {
            if (checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE)
                    != PackageManager.PERMISSION_GRANTED) {
                need.add(Manifest.permission.READ_EXTERNAL_STORAGE);
            }
        }
        if (!need.isEmpty()) {
            requestPermissions(need.toArray(new String[0]), 1);
        }
    }

    private void openAllFilesAccessSettings() {
        try {
            Intent i = new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION);
            i.setData(Uri.parse("package:" + getPackageName()));
            startActivity(i);
        } catch (Exception e) {
            Intent i = new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION);
            startActivity(i);
        }
    }

    private boolean allFilesGranted() {
        if (Build.VERSION.SDK_INT >= 30) {
            return Environment.isExternalStorageManager();
        }
        return checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE)
                == PackageManager.PERMISSION_GRANTED;
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(48, 72, 48, 48);

        TextView title = new TextView(this);
        title.setText("Handover Demo · 安卓端");
        title.setTextSize(22);
        root.addView(title);

        status = new TextView(this);
        status.setTextSize(16);
        status.setPadding(0, 28, 0, 10);
        root.addView(status);

        info = new TextView(this);
        info.setTextSize(13);
        info.setPadding(0, 0, 0, 28);
        root.addView(info);

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        Button start = new Button(this);
        start.setText("启动服务");
        start.setOnClickListener(new android.view.View.OnClickListener() {
            public void onClick(android.view.View v) { startPhoneService(); }
        });
        Button perm = new Button(this);
        perm.setText("授权文件访问");
        perm.setOnClickListener(new android.view.View.OnClickListener() {
            public void onClick(android.view.View v) {
                requestRuntimePermissions();
                openAllFilesAccessSettings();
            }
        });
        Button stop = new Button(this);
        stop.setText("停止服务");
        stop.setOnClickListener(new android.view.View.OnClickListener() {
            public void onClick(android.view.View v) {
                stopService(new Intent(MainActivity.this, PhoneService.class));
            }
        });
        row.addView(start);
        row.addView(perm);
        row.addView(stop);
        root.addView(row);

        TextView hint = new TextView(this);
        hint.setTextSize(12);
        hint.setPadding(0, 28, 0, 0);
        hint.setText("电脑端：\n  adb forward tcp:10086 tcp:10086\n"
                + "然后在 Handover Demo 里手动连接 127.0.0.1:10086。\n\n"
                + "协议：HOVR 帧 + JSON 控制面 + session_id 裸流数据面。\n"
                + "存储根目录：手机公共存储 /sdcard（真实文件，无模拟数据）。\n"
                + "需要「所有文件访问」+ 相册/媒体权限才能浏览完整目录。");
        root.addView(hint);

        ScrollView scroll = new ScrollView(this);
        scroll.addView(root);
        setContentView(scroll);
    }

    private void startPhoneService() {
        Intent i = new Intent(this, PhoneService.class);
        if (Build.VERSION.SDK_INT >= 26) {
            startForegroundService(i);
        } else {
            startService(i);
        }
    }

    private void refresh() {
        status.setText("状态：" + PhoneService.status);
        info.setText("设备：" + Build.MANUFACTURER + " " + Build.MODEL + "\n"
                + "系统：Android " + Build.VERSION.RELEASE
                + " (API " + Build.VERSION.SDK_INT + ")\n"
                + "端口：" + PhoneService.PORT + "\n"
                + "本机 IP：" + localIp() + "\n"
                + "公共存储：" + Environment.getExternalStorageDirectory().getAbsolutePath() + "\n"
                + "所有文件访问：" + (allFilesGranted() ? "已授权" : "未授权（点『授权文件访问』）"));
    }

    private String localIp() {
        try {
            List<NetworkInterface> ifs =
                    Collections.list(NetworkInterface.getNetworkInterfaces());
            for (NetworkInterface ni : ifs) {
                if (!ni.isUp() || ni.isLoopback()) continue;
                for (InetAddress a : Collections.list(ni.getInetAddresses())) {
                    if (a instanceof Inet4Address && !a.isLoopbackAddress()) {
                        return a.getHostAddress();
                    }
                }
            }
        } catch (Exception ignored) { }
        return "未知";
    }
}
