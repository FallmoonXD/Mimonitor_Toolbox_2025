import java.io.FileWriter;

public class ColorfulLedTool {
    private static final String BSP_IFACE = "vendor.mi.hardware.bspmserver@2.0::IBspMServer";
    private static final String CONFIG_IFACE = "vendor.mi.hardware.bspmserver@2.0::IVendorConfig";

    private static final Class<?> PARCEL;
    private static final Class<?> BINDER;
    static {
        try {
            PARCEL = Class.forName("android.os.HwParcel");
            BINDER = Class.forName("android.os.IHwBinder");
        } catch (Exception error) {
            throw new ExceptionInInitializerError(error);
        }
    }
    private static void transact(Object binder, int code, Object req, Object reply) throws Exception {
        BINDER.getMethod("transact", int.class, PARCEL, PARCEL, int.class).invoke(binder, code, req, reply, 0);
        PARCEL.getMethod("verifySuccess").invoke(reply);
        PARCEL.getMethod("releaseTemporaryStorage").invoke(req);
    }
    private static Object getConfigBinder() throws Exception {
        Object bsp = Class.forName("android.os.HwBinder").getMethod("getService", String.class, String.class)
                .invoke(null, BSP_IFACE, "default");
        Object req = PARCEL.getConstructor().newInstance();
        Object reply = PARCEL.getConstructor().newInstance();
        PARCEL.getMethod("writeInterfaceToken", String.class).invoke(req, BSP_IFACE);
        try {
            transact(bsp, 6, req, reply);
            int status = (Integer) PARCEL.getMethod("readInt32").invoke(reply);
            Object config = PARCEL.getMethod("readStrongBinder").invoke(reply);
            if (status != 0 || config == null) {
                throw new RuntimeException("CreateConfigInterface failed status=" + status + " binder=" + config);
            }
            return config;
        } finally {
            PARCEL.getMethod("release").invoke(reply);
        }
    }

    private static int setColorfulLed(int mode, int color) throws Exception {
        Object config = getConfigBinder();
        Object req = PARCEL.getConstructor().newInstance();
        Object reply = PARCEL.getConstructor().newInstance();
        PARCEL.getMethod("writeInterfaceToken", String.class).invoke(req, CONFIG_IFACE);
        PARCEL.getMethod("writeInt32", int.class).invoke(req, mode);
        PARCEL.getMethod("writeInt32", int.class).invoke(req, color);
        try {
            transact(config, 2, req, reply);
            return (Integer) PARCEL.getMethod("readInt32").invoke(reply);
        } finally {
            PARCEL.getMethod("release").invoke(reply);
        }
    }

    private static int lightingColor(int illumination, int colorTemp) {
        illumination = clamp(illumination, 0, 14);
        colorTemp = clamp(colorTemp, 0, 2);
        if (colorTemp == 1) {
            return 13 + illumination;
        }
        if (colorTemp == 0) {
            return 28 + illumination;
        }
        return 43 + illumination;
    }

    private static int solidColor(int illumination, int colorValue) {
        illumination = clamp(illumination, 0, 14);
        colorValue = clamp(colorValue, 0, 4);
        int[] base = {58, 73, 103, 88, 118};
        return base[colorValue] + illumination;
    }

    private static int clamp(int v, int lo, int hi) {
        return Math.max(lo, Math.min(hi, v));
    }

    private static int parse(String s, int def) {
        try {
            return Integer.parseInt(s);
        } catch (Exception e) {
            return def;
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.out.println("Usage: ColorfulLedTool <off|ambient|cycle|lighting|solid|raw> ...");
            return;
        }
        String cmd = args[0];
        int mode;
        int color;
        if ("off".equals(cmd)) {
            mode = 0;
            color = 1;
        } else if ("ambient".equals(cmd)) {
            mode = 12;
            color = 1;
        } else if ("cycle".equals(cmd)) {
            mode = 3;
            color = 1;
        } else if ("lighting".equals(cmd)) {
            mode = 11;
            color = lightingColor(parse(args.length > 1 ? args[1] : "9", 9), parse(args.length > 2 ? args[2] : "1", 1));
        } else if ("solid".equals(cmd)) {
            mode = 1;
            color = solidColor(parse(args.length > 1 ? args[1] : "9", 9), parse(args.length > 2 ? args[2] : "0", 0));
        } else if ("raw".equals(cmd)) {
            mode = parse(args.length > 1 ? args[1] : "0", 0);
            color = parse(args.length > 2 ? args[2] : "0", 0);
        } else {
            throw new IllegalArgumentException("Unknown command: " + cmd);
        }
        int ret = setColorfulLed(mode, color);
        System.out.println("SetColorfulLed mode=" + mode + " color=" + color + " ret=" + ret);
        if (args.length == 4 && "raw".equals(cmd)) {
            String path = args[3];
            if (!path.matches("/sdcard/Download/Mimonitor_Toolbox/\\.led_action_[a-f0-9]+\\.txt")) {
                throw new IllegalArgumentException("Invalid LED result path");
            }
            try (FileWriter writer = new FileWriter(path)) {
                writer.write("mode=" + mode + "\ncolor=" + color + "\nreturn=" + ret + "\n__complete=1\n");
            }
        }
    }
}
