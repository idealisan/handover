package com.handover.demo;

import android.content.Context;
import android.os.StatFs;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.Arrays;
import java.util.Comparator;

/** 安卓端虚拟存储：应用专属外部目录，避免分区存储权限问题。 */
final class PhoneStorage {
    private static final String TAG = "HandoverDemo";
    private final File root;
    private final File trash;

    PhoneStorage(Context ctx) {
        File base = ctx.getExternalFilesDir(null);
        if (base == null) base = ctx.getFilesDir();
        root = new File(base, "phone");
        ensure(root);
        trash = new File(root, ".Trash");
        ensure(trash);
        seed();
    }

    File getRoot() { return root; }

    private static void ensure(File dir) {
        if (!dir.exists()) dir.mkdirs();
    }

    private void seed() {
        String[][] dirs = {
                {"DCIM", "Camera"}, {"Pictures", "Screenshots"},
                {"Music"}, {"Download"}, {"Documents"}
        };
        for (String[] parts : dirs) {
            File d = root;
            for (String p : parts) d = new File(d, p);
            ensure(d);
        }
        writeIfMissing(new File(root, "Documents/欢迎.txt"), "Handover Demo 安卓端虚拟存储\n");
        writeIfMissing(new File(root, "Documents/协议说明.txt"), "控制面 JSON；数据面按 session_id 走裸字节流\n");
        writeIfMissing(new File(root, "DCIM/Camera/photo_001.txt"), "示例图片占位\n");
        writeIfMissing(new File(root, "Music/track_001.txt"), "示例音频占位\n");
    }

    private void writeIfMissing(File f, String text) {
        try {
            if (!f.exists()) {
                File p = f.getParentFile();
                if (p != null) ensure(p);
                FileOutputStream fos = new FileOutputStream(f);
                fos.write(text.getBytes("UTF-8"));
                fos.close();
            }
        } catch (IOException e) {
            Log.w(TAG, "seed failed", e);
        }
    }

    private static String normalize(String path) {
        if (path == null || path.isEmpty()) return "/";
        String p = path.replace('\\', '/').trim();
        if (!p.startsWith("/")) p = "/" + p;
        while (p.contains("//")) p = p.replace("//", "/");
        return p;
    }

    private File resolve(String path) throws IOException {
        String p = normalize(path);
        File f = new File(root, p.substring(1)).getCanonicalFile();
        String rootPath = root.getCanonicalPath();
        if (!f.getPath().equals(rootPath)
                && !f.getPath().startsWith(rootPath + File.separator)) {
            throw new IOException("路径越界");
        }
        return f;
    }

    synchronized JSONObject listDir(String path) throws Exception {
        File dir = resolve(path);
        if (!dir.isDirectory()) throw new IOException("不是目录");
        JSONArray arr = new JSONArray();
        File[] children = dir.listFiles();
        if (children != null) {
            Arrays.sort(children, new Comparator<File>() {
                public int compare(File a, File b) {
                    if (a.isDirectory() != b.isDirectory()) return a.isDirectory() ? -1 : 1;
                    return a.getName().compareToIgnoreCase(b.getName());
                }
            });
            for (File c : children) {
                if (c.getName().equals(".Trash")) continue;
                JSONObject o = new JSONObject();
                o.put("name", c.getName());
                o.put("path", "/" + relativize(c));
                o.put("size", c.isDirectory() ? 0 : c.length());
                o.put("is_dir", c.isDirectory());
                o.put("mtime", c.lastModified() / 1000);
                arr.put(o);
            }
        }
        JSONObject res = new JSONObject();
        res.put("path", normalize(path));
        res.put("entries", arr);
        return res;
    }

    private String relativize(File f) throws IOException {
        String base = root.getCanonicalPath();
        String p = f.getCanonicalPath();
        if (p.startsWith(base + File.separator)) {
            return p.substring(base.length() + 1).replace(File.separatorChar, '/');
        }
        return f.getName();
    }

    synchronized JSONObject mkdir(String parent, String name) throws Exception {
        String n = safeName(name);
        File dir = new File(resolve(parent), n);
        if (dir.exists()) throw new IOException("同名文件已存在");
        if (!dir.mkdirs()) throw new IOException("创建目录失败");
        JSONObject o = new JSONObject();
        o.put("path", "/" + relativize(dir));
        return o;
    }

    synchronized JSONObject rename(String path, String newName) throws Exception {
        String n = safeName(newName);
        File src = resolve(path);
        if (!src.exists()) throw new IOException("源文件不存在");
        File dst = new File(src.getParentFile(), n);
        if (dst.exists()) throw new IOException("目标已存在");
        if (!src.renameTo(dst)) throw new IOException("重命名失败");
        JSONObject o = new JSONObject();
        o.put("path", "/" + relativize(dst));
        return o;
    }

    synchronized JSONObject delete(JSONArray paths) throws Exception {
        JSONArray moved = new JSONArray();
        if (paths != null) {
            for (int i = 0; i < paths.length(); i++) {
                File src = resolve(paths.getString(i));
                if (!src.exists()) continue;
                File dst = new File(trash, System.currentTimeMillis() + "_" + src.getName());
                if (src.renameTo(dst)) moved.put(paths.getString(i));
            }
        }
        JSONObject o = new JSONObject();
        o.put("moved", moved);
        o.put("trash", true);
        return o;
    }

    private static String safeName(String name) throws IOException {
        if (name == null) throw new IOException("名称为空");
        String n = new File(name).getName().trim();
        if (n.isEmpty() || n.equals(".") || n.equals("..") || n.contains("/")) {
            throw new IOException("名称不合法");
        }
        return n;
    }

    synchronized File fileFor(String path) throws IOException {
        File f = resolve(path);
        if (!f.isFile()) throw new IOException("文件不存在");
        return f;
    }

    synchronized void writeFile(String path, byte[] data) throws IOException {
        File f = resolve(path);
        File p = f.getParentFile();
        if (p != null) ensure(p);
        FileOutputStream fos = new FileOutputStream(f);
        fos.write(data);
        fos.close();
    }

    synchronized JSONObject usage() {
        JSONObject o = new JSONObject();
        try {
            o.put("used", sizeOf(root));
            StatFs stat = new StatFs(root.getAbsolutePath());
            o.put("total", stat.getTotalBytes());
        } catch (Exception ignored) { }
        return o;
    }

    private long sizeOf(File f) {
        if (f.isFile()) return f.length();
        long s = 0;
        File[] cs = f.listFiles();
        if (cs != null) for (File c : cs) s += sizeOf(c);
        return s;
    }
}
