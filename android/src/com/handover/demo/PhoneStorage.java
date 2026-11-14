package com.handover.demo;

import android.content.Context;
import android.os.Environment;
import android.os.StatFs;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.Arrays;
import java.util.Comparator;

/**
 * 安卓端真实存储：根目录是设备公共存储 /sdcard（Environment.getExternalStorageDirectory）。
 * 不创建任何示例/占位文件，界面看到的就是手机上真实存在的目录与文件。
 * 需要 MANAGE_EXTERNAL_STORAGE（所有文件访问）+ READ_MEDIA_* 权限，见 AndroidManifest
 * 与 MainActivity 的申请逻辑。
 */
final class PhoneStorage {
    private static final String TAG = "HandoverDemo";
    private final File root;
    private final File trash;

    PhoneStorage(Context ctx) {
        // 真实手机公共存储根目录
        root = Environment.getExternalStorageDirectory();
        // 回收站放在应用专属目录，避免往公共存储里塞不必要的东西
        File base = ctx.getExternalFilesDir(null);
        if (base == null) base = ctx.getFilesDir();
        trash = new File(base, "trash");
        if (!trash.exists()) trash.mkdirs();
    }

    File getRoot() { return root; }

    /** 是否已拿到「所有文件访问」权限。 */
    static boolean hasAllFilesAccess() {
        if (android.os.Build.VERSION.SDK_INT >= 30) {
            return Environment.isExternalStorageManager();
        }
        return true;
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
                // 跳过应用私有 Android/data 等无权限目录，避免噪音
                if (c.getName().equals("Android") && c.isDirectory()) continue;
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
        res.put("root", root.getAbsolutePath());
        res.put("all_files_access", hasAllFilesAccess());
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
        if (!dir.mkdirs()) throw new IOException("创建目录失败（检查存储权限）");
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
        if (p != null && !p.exists()) p.mkdirs();
        FileOutputStream fos = new FileOutputStream(f);
        fos.write(data);
        fos.close();
    }

    synchronized JSONObject usage() {
        JSONObject o = new JSONObject();
        try {
            StatFs stat = new StatFs(root.getAbsolutePath());
            long total = stat.getTotalBytes();
            long avail = stat.getAvailableBytes();
            o.put("used", total - avail);
            o.put("total", total);
        } catch (Exception e) {
            Log.w(TAG, "usage failed", e);
        }
        return o;
    }
}
