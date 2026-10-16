import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.lang.reflect.*;

/** One authenticated, loopback-only worker per desktop connection. No parameter writes at startup. */
public final class ToolboxSession {
    private static final int LIMIT = 1024 * 1024;

    private static String receive(DataInputStream input) throws IOException {
        int size = input.readInt();
        if (size < 1 || size > LIMIT) throw new IOException("Invalid request length");
        byte[] data = new byte[size];
        input.readFully(data);
        return new String(data, StandardCharsets.UTF_8);
    }

    private static void send(DataOutputStream output, String text) throws IOException {
        byte[] data = text.getBytes(StandardCharsets.UTF_8);
        output.writeInt(data.length);
        output.write(data);
        output.flush();
    }

    private static String execute(String tool, String[] arguments) throws Exception {
        if ("native".equals(tool)) return MtkDirectTool.executeSession(arguments);
        if ("led".equals(tool) && arguments.length == 2) {
            int mode = Integer.parseInt(arguments[0]), color = Integer.parseInt(arguments[1]);
            boolean valid = mode == 0 ? color >= 0 && color <= 11
                : mode >= 1 && mode <= 4 ? color >= 1 && color <= 12
                : mode == 5 && (color == 0 || color == 1);
            if (!valid)
                throw new IllegalArgumentException("Invalid LED command");
            Method setter = Class.forName("ColorfulLedTool").getDeclaredMethod("setColorfulLed", int.class, int.class);
            setter.setAccessible(true);
            int result = (Integer) setter.invoke(null, mode, color);
            return "mode=" + mode + "\ncolor=" + color + "\nreturn=" + result + "\n__complete=1\n";
        }
        throw new IllegalArgumentException("Unknown session tool");
    }

    public static void main(String[] args) throws Exception {
        if ((args.length != 1 && !(args.length == 2 && "readonly".equals(args[1])))
                || !args[0].matches("/sdcard/Download/Mimonitor_Toolbox/\\.session_[a-f0-9]{32}"))
            throw new IllegalArgumentException("Invalid session directory");
        File directory = new File(args[0]);
        if (!directory.isDirectory()) throw new IOException("Session directory missing");
        String token = directory.getName().substring(".session_".length());
        runSessionAndExit(directory, token, args.length == 2);
    }

    static void runSessionAndExit(File directory, String token, boolean readOnly) throws Exception {
        try {
            serve(directory, token, readOnly);
        } finally {
            // TVNative starts Binder/native threads. Returning from main alone
            // leaves the Android app_process alive after its socket is closed.
            System.exit(0);
        }
    }

    static void serve(File directory, String token, boolean readOnly) throws Exception {
        File ready = new File(directory, "ready");
        // Cache the TV class loader and native bindings once; every request still reads live values.
        MtkDirectTool.prepareSession();
        try (ServerSocket server = new ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"))) {
            server.setSoTimeout(600000);
            File temporary = new File(directory, "ready.tmp");
            try (FileWriter writer = new FileWriter(temporary)) {
                writer.write("1\n" + token + "\n" + server.getLocalPort() + "\n");
            }
            if (!temporary.renameTo(ready)) throw new IOException("Cannot publish session");
            while (true) {
                try (Socket client = server.accept()) {
                    client.setSoTimeout(10000);
                    client.setTcpNoDelay(true);
                    DataInputStream input = new DataInputStream(client.getInputStream());
                    DataOutputStream output = new DataOutputStream(client.getOutputStream());
                    String[] request = receive(input).split("\n", -1);
                    if (request.length < 3 || !token.equals(request[0])) {
                        send(output, "ERROR\nSession authentication failed");
                        continue;
                    }
                    // A request waiting behind a slow native call needs a live
                    // client before execution. Timed-out queued writes are discarded.
                    send(output, "READY");
                    if (!"GO".equals(receive(input))) continue;
                    String[] arguments = new String[request.length - 2];
                    System.arraycopy(request, 2, arguments, 0, arguments.length);
                    if ("close".equals(request[1])) {
                        send(output, "OK\nclosed");
                        break;
                    }
                    String result;
                    try {
                        if (readOnly && !("native".equals(request[1]) && arguments.length > 0
                                && ("getBatch".equals(arguments[0]) || "getPictureState".equals(arguments[0]))))
                            throw new IllegalArgumentException("Read-only session");
                        result = "OK\n" + execute(request[1], arguments);
                    }
                    catch (Throwable error) { result = "ERROR\n" + error; }
                    // A lost reply must never cause an automatic repeat of a setter.
                    send(output, result);
                } catch (SocketTimeoutException error) {
                    // An inactive worker exits; the desktop opens a new worker on next use.
                    break;
                } catch (IOException error) {
                    // A disconnected desktop does not make a completed command run twice.
                }
            }
        } finally {
            ready.delete();
            directory.delete();
        }
    }
}
