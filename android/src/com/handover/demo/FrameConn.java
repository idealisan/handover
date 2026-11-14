package com.handover.demo;

import org.json.JSONObject;

import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.net.Socket;
import java.nio.charset.StandardCharsets;

/** 与 Python demo/protocol.py 完全一致的 HOVR 帧编解码。 */
final class FrameConn {
    static final int FLAG_CONTROL = 1;
    static final int FLAG_DATA = 2;
    private static final byte[] MAGIC = new byte[]{'H', 'O', 'V', 'R'};

    private final Socket socket;
    private final DataInputStream in;
    private final DataOutputStream out;
    private final Object writeLock = new Object();
    private volatile boolean closed = false;

    FrameConn(Socket socket) throws IOException {
        this.socket = socket;
        this.in = new DataInputStream(socket.getInputStream());
        this.out = new DataOutputStream(socket.getOutputStream());
    }

    boolean isClosed() { return closed; }

    void close() {
        closed = true;
        try { socket.close(); } catch (IOException ignored) { }
    }

    static final class Frame {
        final int flags;
        final int sessionId;
        final byte[] payload;

        Frame(int flags, int sessionId, byte[] payload) {
            this.flags = flags;
            this.sessionId = sessionId;
            this.payload = payload;
        }

        boolean isData() { return (flags & FLAG_DATA) != 0; }
    }

    Frame read() throws IOException {
        byte[] magic = new byte[4];
        in.readFully(magic);
        for (int i = 0; i < 4; i++) {
            if (magic[i] != MAGIC[i]) throw new IOException("bad magic");
        }
        int version = in.readUnsignedByte();
        if (version != 1) throw new IOException("bad version");
        int flags = in.readUnsignedByte();
        int sessionId = in.readInt();
        int length = in.readInt();
        if (length < 0 || length > 16 * 1024 * 1024) throw new IOException("bad length");
        byte[] payload = new byte[length];
        in.readFully(payload);
        return new Frame(flags, sessionId, payload);
    }

    void sendControl(JSONObject msg) throws IOException {
        byte[] payload = msg.toString().getBytes(StandardCharsets.UTF_8);
        writeFrame(FLAG_CONTROL, msg.optInt("session_id", 0), payload);
    }

    void sendData(int sessionId, byte[] chunk) throws IOException {
        writeFrame(FLAG_DATA, sessionId, chunk);
    }

    private void writeFrame(int flags, int sessionId, byte[] payload) throws IOException {
        synchronized (writeLock) {
            out.write(MAGIC);
            out.writeByte(1);
            out.writeByte(flags);
            out.writeInt(sessionId);
            out.writeInt(payload.length);
            out.write(payload);
            out.flush();
        }
    }
}
