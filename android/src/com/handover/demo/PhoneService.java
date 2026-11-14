package com.handover.demo;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import android.net.wifi.WifiManager;
import android.os.BatteryManager;
import android.os.Build;
import android.os.IBinder;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 安卓端 SSP-like 服务：监听 10086，注册 _handshaker_ssp._tcp，
 * 与 Python demo 的桌面客户端使用同一套 HOVR/JSON 协议。
 */
public class PhoneService extends Service {
    static final String TAG = "HandoverDemo";
    static final int PORT = 10086;
    static volatile String status = "未启动";
    static volatile boolean running = false;

    private ServerSocket serverSocket;
    private PhoneStorage storage;
    private NsdManager nsdManager;
    private NsdManager.RegistrationListener nsdListener;
    private WifiManager.MulticastLock multicastLock;

    private final Set<FrameConn> clients = new HashSet<FrameConn>();
    private final Map<Integer, Upload> uploads = new HashMap<Integer, Upload>();
    private final Set<Integer> cancelled =
            Collections.synchronizedSet(new HashSet<Integer>());
    private final List<String> clipboardCache = new ArrayList<String>();

    private static final class Upload {
        final String path;
        final String md5;
        final ByteArrayOutputStream buf = new ByteArrayOutputStream();

        Upload(String path, String md5) {
            this.path = path;
            this.md5 = md5;
        }
    }

    @Override
    public void onCreate() {
        super.onCreate();
        storage = new PhoneStorage(this);
        createChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForeground(1, buildNotification("SSP 服务运行中 · 端口 " + PORT));
        if (!running) startServer();
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }

    @Override
    public void onDestroy() {
        stopServer();
        super.onDestroy();
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel(
                    "handover", "Handover Demo", NotificationManager.IMPORTANCE_LOW);
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) nm.createNotificationChannel(ch);
        }
    }

    private Notification buildNotification(String text) {
        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= 26) {
            b = new Notification.Builder(this, "handover");
        } else {
            b = new Notification.Builder(this);
        }
        return b.setContentTitle("Handover Demo")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setOngoing(true)
                .build();
    }

    private void startServer() {
        running = true;
        status = "启动中";
        Thread t = new Thread(new Runnable() {
            public void run() { acceptLoop(); }
        }, "phone-accept");
        t.start();
        registerNsd();
        acquireMulticast();
    }

    private void stopServer() {
        running = false;
        status = "已停止";
        try { if (serverSocket != null) serverSocket.close(); } catch (IOException ignored) { }
        synchronized (clients) {
            for (FrameConn c : clients) c.close();
            clients.clear();
        }
        unregisterNsd();
        releaseMulticast();
        stopForeground(STOP_FOREGROUND_REMOVE);
    }

    private void acceptLoop() {
        try {
            serverSocket = new ServerSocket();
            serverSocket.setReuseAddress(true);
            serverSocket.bind(new InetSocketAddress(PORT));
            status = "监听 0.0.0.0:" + PORT;
            while (running) {
                final Socket s = serverSocket.accept();
                Thread t = new Thread(new Runnable() {
                    public void run() { handleClient(s); }
                }, "phone-client");
                t.start();
            }
        } catch (IOException e) {
            if (running) {
                status = "监听失败: " + e.getMessage();
                Log.e(TAG, "accept failed", e);
            }
        }
    }

    private void handleClient(Socket s) {
        FrameConn conn = null;
        try {
            conn = new FrameConn(s);
            synchronized (clients) { clients.add(conn); }
            status = "已连接: " + s.getRemoteSocketAddress();
            while (!conn.isClosed()) {
                FrameConn.Frame f = conn.read();
                if (f.isData()) {
                    onData(f.sessionId, f.payload);
                } else {
                    onControl(new JSONObject(new String(f.payload, "UTF-8")), conn);
                }
            }
        } catch (Exception e) {
            Log.d(TAG, "client closed: " + e.getMessage());
        } finally {
            if (conn != null) {
                synchronized (clients) { clients.remove(conn); }
                conn.close();
            }
            if (running) status = "运行中 · 端口 " + PORT;
        }
    }

    private void onControl(JSONObject msg, FrameConn conn) {
        String cmd = msg.optString("cmd", "");
        int seq = msg.optInt("seq", 0);
        int sid = msg.optInt("session_id", 0);
        JSONObject d = msg.optJSONObject("data");
        if (d == null) d = new JSONObject();
        try {
            if ("HELLO".equals(cmd)) {
                hello(conn, seq);
            } else if ("PAIR_REQUEST".equals(cmd)) {
                pair(conn, seq, d);
            } else if ("HEARTBEAT".equals(cmd)) {
                ack(conn, cmd, seq, 0, new JSONObject(), true, null);
            } else if ("GET_DEVICE_INFO".equals(cmd)) {
                ack(conn, cmd, seq, 0, deviceInfo(), true, null);
            } else if ("LIST_DIR".equals(cmd)) {
                ack(conn, cmd, seq, 0, storage.listDir(d.optString("path", "/")), true, null);
            } else if ("MKDIR".equals(cmd)) {
                JSONObject r = storage.mkdir(d.optString("path", "/"), d.optString("name", ""));
                ack(conn, cmd, seq, 0, r, true, null);
                push(conn, "FILE_CHANGE", 0, r);
            } else if ("RENAME".equals(cmd)) {
                JSONObject r = storage.rename(d.optString("path", ""), d.optString("new_name", ""));
                ack(conn, cmd, seq, 0, r, true, null);
                push(conn, "FILE_CHANGE", 0, r);
            } else if ("DELETE".equals(cmd)) {
                JSONObject r = storage.delete(d.optJSONArray("paths"));
                ack(conn, cmd, seq, 0, r, true, null);
                push(conn, "FILE_CHANGE", 0, r);
            } else if ("GET_CLIPBOARD".equals(cmd)) {
                ack(conn, cmd, seq, 0, clipboardData(), true, null);
            } else if ("POST_CLIPBOARD".equals(cmd)) {
                postClipboard(d.optString("text", ""));
                ack(conn, cmd, seq, 0, okData(), true, null);
                push(conn, "CLIPBOARD_CHANGE", 0, clipboardData());
            } else if ("CLEAR_CLIPBOARD".equals(cmd)) {
                clipboardCache.clear();
                setSystemClipboard("");
                ack(conn, cmd, seq, 0, okData(), true, null);
                push(conn, "CLIPBOARD_CHANGE", 0, clipboardData());
            } else if ("UPLOAD_INIT".equals(cmd)) {
                uploadInit(conn, seq, sid, d);
            } else if ("UPLOAD_DONE".equals(cmd)) {
                uploadDone(conn, seq, sid);
            } else if ("DOWNLOAD_INIT".equals(cmd)) {
                downloadInit(conn, seq, sid, d);
            } else if ("CANCEL".equals(cmd)) {
                cancelled.add(sid);
                ack(conn, cmd, seq, sid, okData(), true, null);
            } else if ("QUIT".equals(cmd)) {
                conn.close();
            } else {
                ack(conn, cmd, seq, sid, null, false, "未知命令: " + cmd);
            }
        } catch (Exception e) {
            ack(conn, cmd, seq, sid, null, false, String.valueOf(e.getMessage()));
        }
    }

    private void ack(FrameConn conn, String cmd, int seq, int sid,
                     JSONObject data, boolean ok, String error) {
        try {
            JSONObject o = new JSONObject();
            o.put("cmd", cmd + "_ACK");
            o.put("seq", seq);
            o.put("session_id", sid);
            o.put("ok", ok);
            o.put("data", data == null ? new JSONObject() : data);
            o.put("error", error);
            conn.sendControl(o);
        } catch (Exception e) {
            Log.w(TAG, "ack failed", e);
        }
    }

    private void push(FrameConn conn, String cmd, int sid, JSONObject data) {
        try {
            JSONObject o = new JSONObject();
            o.put("cmd", cmd);
            o.put("seq", 0);
            o.put("session_id", sid);
            o.put("ok", true);
            o.put("data", data == null ? new JSONObject() : data);
            o.put("error", JSONObject.NULL);
            conn.sendControl(o);
        } catch (Exception e) {
            Log.w(TAG, "push failed", e);
        }
    }

    private static JSONObject okData() throws Exception {
        JSONObject o = new JSONObject();
        o.put("succeed", true);
        return o;
    }

    private void hello(FrameConn conn, int seq) {
        try {
            JSONObject r = new JSONObject();
            r.put("device_uuid", "ANDROID-" + Build.FINGERPRINT.hashCode());
            r.put("device_name", Build.MANUFACTURER + " " + Build.MODEL);
            r.put("apk_version", "0.1.0");
            r.put("client_protocol_version", "1.0-demo");
            r.put("client_min_host_version", "0.1.0");
            r.put("is_smartisan_device", false);
            ack(conn, "HELLO", seq, 0, r, true, null);
        } catch (Exception e) {
            ack(conn, "HELLO", seq, 0, null, false, e.getMessage());
        }
    }

    private void pair(FrameConn conn, int seq, JSONObject d) {
        try {
            String trust = d.optString("trust", "NO");
            String result = ("ONCE".equals(trust) || "ALWAYS".equals(trust)) ? "ok" : "failed";
            JSONObject r = new JSONObject();
            r.put("trust", trust);
            r.put("result", result);
            r.put("device_uuid", "ANDROID-" + Build.FINGERPRINT.hashCode());
            r.put("derived_key", "demo-derived-key");
            ack(conn, "PAIR_REQUEST", seq, 0, r, true, null);
        } catch (Exception e) {
            ack(conn, "PAIR_REQUEST", seq, 0, null, false, e.getMessage());
        }
    }

    private JSONObject deviceInfo() throws Exception {
        JSONObject usage = storage.usage();
        JSONObject o = new JSONObject();
        o.put("device_uuid", "ANDROID-" + Build.FINGERPRINT.hashCode());
        o.put("device_name", Build.MANUFACTURER + " " + Build.MODEL);
        o.put("phone_model", Build.MODEL);
        o.put("phone_name", Build.MANUFACTURER + " " + Build.MODEL);
        o.put("product_brand", Build.BRAND);
        o.put("smartisan_version", "Android " + Build.VERSION.RELEASE);
        o.put("battery_percentage", battery());
        o.put("battery_capacity", 5000);
        o.put("phone_locked", false);
        o.put("used_disk_size", usage.optLong("used"));
        o.put("disk_size", usage.optLong("total"));
        o.put("root_path", "/");
        o.put("apk_version", "0.1.0");
        o.put("client_protocol_version", "1.0-demo");
        o.put("client_min_host_version", "0.1.0");
        o.put("external_storage_permission", "ALLOW_READ_WRITE");
        o.put("debug_build_time", "manual-build");
        return o;
    }

    private int battery() {
        try {
            BatteryManager bm = (BatteryManager) getSystemService(Context.BATTERY_SERVICE);
            if (bm != null) return bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY);
        } catch (Exception ignored) { }
        return -1;
    }

    private JSONObject clipboardData() throws Exception {
        JSONArray arr = new JSONArray();
        for (int i = 0; i < clipboardCache.size(); i++) {
            JSONObject o = new JSONObject();
            o.put("text", clipboardCache.get(i));
            o.put("ts", System.currentTimeMillis());
            arr.put(o);
        }
        JSONObject r = new JSONObject();
        r.put("items", arr);
        return r;
    }

    private void postClipboard(String text) {
        clipboardCache.add(0, text);
        setSystemClipboard(text);
    }

    private void setSystemClipboard(String text) {
        try {
            ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            if (cm != null) cm.setPrimaryClip(ClipData.newPlainText("Handover", text));
        } catch (Exception ignored) { }
    }

    private void uploadInit(FrameConn conn, int seq, int sid, JSONObject d) {
        try {
            cancelled.remove(sid);
            synchronized (uploads) {
                uploads.put(sid, new Upload(d.optString("path", ""), d.optString("md5", "")));
            }
            JSONObject r = new JSONObject();
            r.put("ready", true);
            ack(conn, "UPLOAD_INIT", seq, sid, r, true, null);
        } catch (Exception e) {
            ack(conn, "UPLOAD_INIT", seq, sid, null, false, e.getMessage());
        }
    }

    private void onData(int sid, byte[] chunk) {
        Upload u;
        synchronized (uploads) { u = uploads.get(sid); }
        if (u == null || cancelled.contains(sid)) return;
        u.buf.write(chunk, 0, chunk.length);
    }

    private void uploadDone(FrameConn conn, int seq, int sid) {
        Upload u;
        synchronized (uploads) { u = uploads.remove(sid); }
        if (u == null) {
            ack(conn, "UPLOAD_DONE", seq, sid, null, false, "上传会话不存在");
            return;
        }
        try {
            byte[] data = u.buf.toByteArray();
            String md5 = md5(data);
            if (u.md5 != null && u.md5.length() > 0 && !u.md5.equals(md5)) {
                ack(conn, "UPLOAD_DONE", seq, sid, null, false, "MD5 校验失败");
                return;
            }
            storage.writeFile(u.path, data);
            JSONObject r = new JSONObject();
            r.put("path", u.path);
            r.put("size", data.length);
            r.put("md5", md5);
            ack(conn, "UPLOAD_DONE", seq, sid, r, true, null);
            push(conn, "FILE_CHANGE", 0, r);
        } catch (Exception e) {
            ack(conn, "UPLOAD_DONE", seq, sid, null, false, String.valueOf(e.getMessage()));
        }
    }

    private void downloadInit(FrameConn conn, int seq, int sid, JSONObject d) {
        try {
            final File f = storage.fileFor(d.optString("path", ""));
            cancelled.remove(sid);
            JSONObject r = new JSONObject();
            r.put("size", f.length());
            r.put("md5", md5OfFile(f));
            ack(conn, "DOWNLOAD_INIT", seq, sid, r, true, null);
            final FrameConn c = conn;
            final int session = sid;
            Thread t = new Thread(new Runnable() {
                public void run() { streamFile(c, session, f); }
            }, "download");
            t.start();
        } catch (Exception e) {
            ack(conn, "DOWNLOAD_INIT", seq, sid, null, false, String.valueOf(e.getMessage()));
        }
    }

    private void streamFile(FrameConn conn, int sid, File f) {
        try {
            FileInputStream fis = new FileInputStream(f);
            byte[] buf = new byte[64 * 1024];
            int n;
            while ((n = fis.read(buf)) > 0) {
                if (cancelled.contains(sid) || conn.isClosed()) {
                    fis.close();
                    JSONObject ab = new JSONObject();
                    ab.put("session_id", sid);
                    push(conn, "DOWNLOAD_ABORT", sid, ab);
                    return;
                }
                byte[] chunk = new byte[n];
                System.arraycopy(buf, 0, chunk, 0, n);
                conn.sendData(sid, chunk);
                Thread.sleep(6);
            }
            fis.close();
            JSONObject r = new JSONObject();
            r.put("session_id", sid);
            r.put("md5", md5OfFile(f));
            r.put("size", f.length());
            push(conn, "DOWNLOAD_DONE", sid, r);
        } catch (Exception e) {
            Log.w(TAG, "stream failed", e);
        }
    }

    private static String md5(byte[] data) throws Exception {
        MessageDigest md = MessageDigest.getInstance("MD5");
        return hex(md.digest(data));
    }

    private static String md5OfFile(File f) throws Exception {
        MessageDigest md = MessageDigest.getInstance("MD5");
        FileInputStream fis = new FileInputStream(f);
        byte[] buf = new byte[64 * 1024];
        int n;
        while ((n = fis.read(buf)) > 0) md.update(buf, 0, n);
        fis.close();
        return hex(md.digest());
    }

    private static String hex(byte[] dig) {
        StringBuilder sb = new StringBuilder();
        for (byte b : dig) sb.append(String.format("%02x", b & 0xff));
        return sb.toString();
    }

    private void registerNsd() {
        try {
            nsdManager = (NsdManager) getSystemService(Context.NSD_SERVICE);
            if (nsdManager == null) return;
            NsdServiceInfo info = new NsdServiceInfo();
            info.setServiceName("Handover Demo");
            info.setServiceType("_handshaker_ssp._tcp");
            info.setPort(PORT);
            nsdListener = new NsdManager.RegistrationListener() {
                public void onServiceRegistered(NsdServiceInfo i) {
                    Log.i(TAG, "nsd registered: " + i.getServiceName());
                }
                public void onRegistrationFailed(NsdServiceInfo i, int e) {
                    Log.w(TAG, "nsd register failed: " + e);
                }
                public void onServiceUnregistered(NsdServiceInfo i) { }
                public void onUnregistrationFailed(NsdServiceInfo i, int e) { }
            };
            nsdManager.registerService(info, NsdManager.PROTOCOL_DNS_SD, nsdListener);
        } catch (Exception e) {
            Log.w(TAG, "nsd failed", e);
        }
    }

    private void unregisterNsd() {
        try {
            if (nsdManager != null && nsdListener != null) {
                nsdManager.unregisterService(nsdListener);
            }
        } catch (Exception ignored) { }
    }

    private void acquireMulticast() {
        try {
            WifiManager wm = (WifiManager) getApplicationContext()
                    .getSystemService(Context.WIFI_SERVICE);
            if (wm != null) {
                multicastLock = wm.createMulticastLock("handover");
                multicastLock.acquire();
            }
        } catch (Exception ignored) { }
    }

    private void releaseMulticast() {
        try {
            if (multicastLock != null && multicastLock.isHeld()) multicastLock.release();
        } catch (Exception ignored) { }
    }
}
