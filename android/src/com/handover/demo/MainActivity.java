package com.handover.demo;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
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
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
        }
        startPhoneService();
        handler.post(tick);
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacks(tick);
        super.onDestroy();
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
        Button stop = new Button(this);
        stop.setText("停止服务");
        stop.setOnClickListener(new android.view.View.OnClickListener() {
            public void onClick(android.view.View v) {
                stopService(new Intent(MainActivity.this, PhoneService.class));
            }
        });
        row.addView(start);
        row.addView(stop);
        root.addView(row);

        TextView hint = new TextView(this);
        hint.setTextSize(12);
        hint.setPadding(0, 28, 0, 0);
        hint.setText("电脑端：\n  adb forward tcp:10086 tcp:10086\n"
                + "然后在 Handover Demo 里手动连接 127.0.0.1:10086。\n\n"
                + "协议：HOVR 帧 + JSON 控制面 + session_id 裸流数据面。\n"
                + "存储根目录：应用专属外部目录下的 phone/。");
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
                + "本机 IP：" + localIp());
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
