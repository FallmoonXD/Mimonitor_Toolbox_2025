"""Execute the real Java receipt logic against fake native/Provider classes, without ADB."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

import _isolation  # noqa: F401

from mimonitor_toolbox.adb import parse_native_action_result, parse_native_picture_state, parse_native_input_signal


@unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "JDK is needed for Java receipt tests")
class JavaNativeReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="mimonitor-receipt-test-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root = Path(cls.directory.name)
        source = (Path(__file__).resolve().parents[1] / "tools/mtk_direct/MtkDirectTool.java").read_text(encoding="utf-8")
        # Only redirect the legacy diagnostic file into this test's temporary directory.
        source = source.replace('"/data/data/mitv.service/cache/.jni_result"',
                                '"' + (cls.root / "legacy-result.txt").as_posix() + '"')
        files = {
            "MtkDirectTool.java": source,
            "ToolboxSession.java": (Path(__file__).resolve().parents[1] / "tools/mtk_direct/ToolboxSession.java").read_text(encoding="utf-8"),
            "dalvik/system/PathClassLoader.java": """package dalvik.system;
public class PathClassLoader extends ClassLoader {
 public PathClassLoader(String path,String libraries,ClassLoader parent){super(parent);}
}
""",
            "SessionHarness.java": """import java.io.File;
public class SessionHarness {
 public static void main(String[] args) throws Exception {
  // Simulate Binder threads that outlive main() unless the worker exits explicitly.
  new Thread(() -> {try {Thread.sleep(600000);}catch(Exception ignored){}}).start();
  ToolboxSession.runSessionAndExit(new File(args[0]),args[1],Boolean.parseBoolean(args[2]));
 }
}
""",
            "ColorfulLedTool.java": """import com.mediatek.twoworlds.tv.TVNative;
public class ColorfulLedTool {
 private static int setColorfulLed(int mode,int color){TVNative.writes++;return 0;}
}
""",
            "android/util/Log.java": """package android.util;
public class Log { public static int d(String t,String m){return 0;} public static int e(String t,String m){return 0;} }
""",
            "com/mediatek/twoworlds/tv/TVNative.java": """package com.mediatek.twoworlds.tv;
public class TVNative {
 public static boolean lost=false,lossOnSecond=false; public static int lossReads=0;
 public static boolean isSignalLoss_native(){return lost || (lossOnSecond && ++lossReads>1);}
 public static int result=0, tone=0, forced=-2, bank=16, dovi=0, writes=0, red=1024, green=1024, blue=1024;
 public static int getConfigValue_native(int n,String k) {
  if(k.equals("test_write_count")) return writes;
  if(k.equals("g_video__picture_mode")) return bank;
  if(k.equals("g_dovi_info__")) return dovi;
  if(forced!=-2) return forced;
  if(k.equals("g_video__clr_gain_r")) return red;
  if(k.equals("g_video__clr_gain_g")) return green;
  if(k.equals("g_video__clr_gain_b")) return blue;
  return tone;
 }
 public static int afterDovi=-1;
 public static int getMinMaxConfigValue_native(int n,String k){return n==0?0:100;}
 public static int setConfigValue_native(int n,String k,int v,int u) {
  writes++; if(result==0){ if(k.equals("g_video__picture_mode")) bank=v; else tone=v; }
  if(afterDovi>=0)dovi=afterDovi;
  return result;
 }
}
""",
            "com/mediatek/twoworlds/tv/MtkTvAVMode.java": """package com.mediatek.twoworlds.tv;
public class MtkTvAVMode {
 public static boolean empty=false;
 public static MtkTvAVMode getInstance(){return new MtkTvAVMode();}
 public java.util.List<Video> getInputSourceVideoAvailableRecord(){return empty?java.util.Collections.emptyList():java.util.Collections.singletonList(new Video());}
 public static class Video {
  public int getVideoWidth(){return 3840;} public int getVideoHeight(){return 2160;}
  public int getVideoFrameRate(){return 160;} public int getVideoDolbyVision(){return TVNative.dovi;}
 }
}
""",
            "com/mediatek/twoworlds/factory/common/MtkTvFApiDisplayTypes.java": """package com.mediatek.twoworlds.factory.common;
public class MtkTvFApiDisplayTypes {
 public enum EnumColorTemperature { E_MTK_FAPI_COLOR_TEMP_USER }
 public static class ColorTempData {
  public int red,green,blue;
  public ColorTempData(int r,int g,int b,int ro,int go,int bo){red=r;green=g;blue=b;}
 }
}
""",
            "com/mediatek/twoworlds/factory/MtkTvFApiDisplay.java": """package com.mediatek.twoworlds.factory;
import com.mediatek.twoworlds.tv.TVNative;
import com.mediatek.twoworlds.factory.common.MtkTvFApiDisplayTypes.*;
public class MtkTvFApiDisplay {
 public static MtkTvFApiDisplay getInstance(){return new MtkTvFApiDisplay();}
 public int setWbGainOffsetEx(EnumColorTemperature e,ColorTempData d,int n){
  TVNative.writes++;if(TVNative.result==0){TVNative.red=d.red;TVNative.green=d.green;TVNative.blue=d.blue;}
  return TVNative.result;
 }
}
""",
            "xiaomi/hardware/mitv/provider/V1_0/IMiTVProvider.java": """package xiaomi.hardware.mitv.provider.V1_0;
import com.mediatek.twoworlds.tv.TVNative;
public class IMiTVProvider {
 public static int result=-1, afterBank=16;
 public static IMiTVProvider getService(boolean retry){return new IMiTVProvider();}
 public int setHdrAttr(int key,int value){TVNative.bank=afterBank;return result;}
}
""",
            "ReceiptHarness.java": """import java.lang.reflect.*;
import com.mediatek.twoworlds.tv.TVNative;
import xiaomi.hardware.mitv.provider.V1_0.IMiTVProvider;
public class ReceiptHarness {
 public static void main(String[] args) throws Exception {
  TVNative.result=Integer.parseInt(args[0]); IMiTVProvider.result=Integer.parseInt(args[1]);
  TVNative.forced=Integer.parseInt(args[2]); IMiTVProvider.afterBank=Integer.parseInt(args[3]);
  TVNative.bank=Integer.parseInt(args[4]);
  Class<?> helper=Class.forName("MtkDirectTool");
  Field file=helper.getDeclaredField("checkedResultFile");file.setAccessible(true);file.set(null,"in-memory-test");
  Field output=helper.getDeclaredField("checkedResult");output.setAccessible(true);
  StringBuilder receipt=(StringBuilder)output.get(null);
  String action=args.length>6?args[6]:"tone";
  boolean rgb=action.equals("rgb"), mode=action.equals("mode"), read=action.startsWith("read");
  TVNative.dovi=args.length>8?Integer.parseInt(args[8]):0;
  TVNative.afterDovi=args.length>9?Integer.parseInt(args[9]):-1;
  boolean signal=action.startsWith("read-signal");
  TVNative.lost=action.equals("read-signal-lost");TVNative.lossOnSecond=action.equals("read-signal-race");
  com.mediatek.twoworlds.tv.MtkTvAVMode.empty=action.equals("read-signal-empty");
  receipt.append("__version=1\\n__action=").append(signal?"getInputSignal":read?"getPictureState":mode?"setPictureMode":rgb?"setColorGains":"setHdrToneMapping").append("\\n");
  Method setter=TVNative.class.getMethod("setConfigValue_native",int.class,String.class,int.class,int.class);
  Method operation=helper.getDeclaredMethod("setHdrToneMapping",ClassLoader.class,Method.class,int.class,int.class);
  Method guard=helper.getDeclaredMethod("checkBank",ClassLoader.class,int.class);
  operation.setAccessible(true);guard.setAccessible(true);
  try {
   guard.invoke(null,ClassLoader.getSystemClassLoader(),Integer.parseInt(args[5]));
   if(read){
    if(action.equals("read-race"))TVNative.bank=IMiTVProvider.afterBank;
    Method state=helper.getDeclaredMethod(signal?"getInputSignal":"getPictureState",ClassLoader.class);
    state.setAccessible(true);state.invoke(null,ClassLoader.getSystemClassLoader());
   } else if(mode){
    Method picture=helper.getDeclaredMethod("setPictureMode",ClassLoader.class,Method.class,int.class,int.class);
    picture.setAccessible(true);picture.invoke(null,ClassLoader.getSystemClassLoader(),setter,Integer.parseInt(args[7]),3);
   } else if(rgb){
    Method gains=helper.getDeclaredMethod("setColorGains",ClassLoader.class,int.class,int.class,int.class);
    gains.setAccessible(true);gains.invoke(null,ClassLoader.getSystemClassLoader(),925,913,863);
   } else operation.invoke(null,ClassLoader.getSystemClassLoader(),setter,5,3);
  } catch(InvocationTargetException error) { receipt.append("fatal=").append(error.getCause()).append("\\n"); }
  receipt.append("__complete=1\\n__test_writes=").append(TVNative.writes).append("\\n");System.out.print(receipt);
 }
}
""",
        }
        for name, content in files.items():
            path = cls.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        result = subprocess.run([shutil.which("javac"), "-encoding", "UTF-8", "-d", str(cls.root)] +
                                [str(cls.root / name) for name in files], capture_output=True, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))

    def receipt(self, native=0, provider=-1, readback=-2, bank=16, before=16, expected=16, action="tone", target=59, dovi=0, after_dovi=-1):
        result = subprocess.run([shutil.which("java"), "-cp", str(self.root), "ReceiptHarness",
                                 str(native), str(provider), str(readback), str(bank), str(before), str(expected), action,
                                 str(target), str(dovi), str(after_dovi)],
                                capture_output=True, encoding="utf-8", errors="replace", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_real_helper_receipt_retains_2025_provider_warning(self):
        receipt = parse_native_action_result(self.receipt(), "setHdrToneMapping",
                                             {"g_video__vid_hdr_tone_mapping_mode": 5})
        self.assertEqual(receipt["provider_return"], -1)
        self.assertTrue(receipt["native_verified"])
        self.assertTrue(receipt["warnings"])

    def test_input_signal_reads_actual_native_timing_without_setters(self):
        output = self.receipt(action="read-signal", before=13, bank=13, expected=13, dovi=1)
        signal = parse_native_input_signal(output)
        self.assertEqual({key:signal[key] for key in ("lost","width","height","hz","dolby")},
                         {"lost":False,"width":3840,"height":2160,"hz":160,"dolby":1})
        self.assertIn("__test_writes=0", output)

    def test_lost_signal_does_not_return_old_video_timing(self):
        signal = parse_native_input_signal(self.receipt(action="read-signal-lost"))
        self.assertTrue(signal["lost"])
        self.assertNotIn("width", signal)

    def test_input_loss_race_and_absent_tracks_cannot_confirm_signal(self):
        for action in ("read-signal-race", "read-signal-empty"):
            with self.subTest(action=action), self.assertRaises(RuntimeError):
                parse_native_input_signal(self.receipt(action=action))

    def test_real_helper_native_failure_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "setter 返回 -1"):
            parse_native_action_result(self.receipt(native=-1), "setHdrToneMapping",
                                       {"g_video__vid_hdr_tone_mapping_mode": 5})

    def test_real_helper_wrong_readback_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "回读不一致"):
            parse_native_action_result(self.receipt(readback=0), "setHdrToneMapping",
                                       {"g_video__vid_hdr_tone_mapping_mode": 5})

    def test_real_helper_scene_change_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "场景变化"):
            parse_native_action_result(self.receipt(bank=13), "setHdrToneMapping",
                                       {"g_video__vid_hdr_tone_mapping_mode": 5})

    def test_real_helper_rejects_wrong_bank_before_calling_any_native_setter(self):
        output = self.receipt(before=13, expected=16)
        self.assertIn("__test_writes=0", output)
        with self.assertRaisesRegex(RuntimeError, "Picture bank changed"):
            parse_native_action_result(output, "setHdrToneMapping", {"g_video__vid_hdr_tone_mapping_mode": 5})

    def test_real_helper_rgb_group_uses_current_native_gain_readback(self):
        expected = {"g_video__clr_gain_r": 925, "g_video__clr_gain_g": 913, "g_video__clr_gain_b": 863}
        result = parse_native_action_result(self.receipt(action="rgb"), "setColorGains", expected)
        self.assertEqual(result["readback"], expected)
        self.assertEqual(result["warnings"], [])

    def test_get_picture_state_executes_no_setters(self):
        output = self.receipt(action="read", before=13, expected=13, dovi=1)
        state = parse_native_picture_state(output)
        self.assertEqual((state["g_video__picture_mode"], state["g_dovi_info__"]), (13, 1))
        self.assertIn("__test_writes=0", output)

    def test_get_picture_state_rejects_signal_change_without_writes(self):
        output = self.receipt(action="read-race", before=13, expected=13, bank=16, dovi=1)
        self.assertIn("__test_writes=0", output)
        with self.assertRaisesRegex(RuntimeError, "输入信号发生变化"):
            parse_native_picture_state(output)

    def test_native_dolby_mode_change_uses_actual_mtk_value(self):
        output = self.receipt(action="mode", before=13, expected=13, dovi=1, target=59)
        result = parse_native_action_result(output, "setPictureMode", {"g_video__picture_mode": 59})
        self.assertEqual((result["bank_before"], result["bank_after"]), (13, 59))
        self.assertIn("__test_writes=1", output)

    def test_mode_cannot_force_dolby_when_the_source_is_hdr(self):
        output = self.receipt(action="mode", before=16, expected=16, dovi=0, target=59)
        self.assertIn("__test_writes=0", output)
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            parse_native_action_result(output, "setPictureMode", {"g_video__picture_mode": 59})

    def test_tone_cannot_write_into_dolby_signal(self):
        output = self.receipt(before=13, expected=13, dovi=1)
        self.assertIn("__test_writes=0", output)
        with self.assertRaisesRegex(RuntimeError, "requires an HDR input"):
            parse_native_action_result(output, "setHdrToneMapping", {"g_video__vid_hdr_tone_mapping_mode": 5})

    def test_mode_rejects_dolby_switch_during_native_write(self):
        output = self.receipt(action="mode", before=13, expected=13, dovi=1, target=59, after_dovi=0)
        with self.assertRaisesRegex(RuntimeError, "杜比信号变化"):
            parse_native_action_result(output, "setPictureMode", {"g_video__picture_mode": 59})

    def start_session(self, readonly=False):
        from mimonitor_toolbox.helper_session import HelperSession
        directory = Path(tempfile.mkdtemp(dir=self.root))
        session = HelperSession(None)
        process = subprocess.Popen([shutil.which("java"), "-cp", str(self.root), "SessionHarness",
                                    str(directory), session.token, str(readonly).lower()],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def cleanup():
            try:
                session.call("close", [""])
                process.wait(timeout=3)
            except Exception:
                process.kill()
                process.wait(timeout=3)
                self.fail("Worker did not exit after closing its session")
        self.addCleanup(cleanup)
        deadline = time.monotonic() + 5
        while not (directory / "ready").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue((directory / "ready").exists(), "Java worker did not start")
        session.port = int((directory / "ready").read_text().splitlines()[2])
        return session

    def session_values(self, session, *keys):
        from mimonitor_toolbox.adb import parse_jni_batch_output
        return parse_jni_batch_output(session.call("native", ["getBatch", *keys,
            "/sdcard/Download/Mimonitor_Toolbox/.mtk_action_a1.txt"]))

    def test_session_reuses_process_but_reads_live_values_and_clears_failed_receipts(self):
        session = self.start_session()
        self.assertEqual(self.session_values(session, "test_write_count")["test_write_count"], 0)
        self.assertEqual(session.call("native", ["set", "g_video__brightness", 42, 3]), "0")
        self.assertEqual(self.session_values(session, "g_video__brightness"), {"g_video__brightness": 42})
        output = session.call("native", ["setPictureModeChecked", 15, 3, 13,
            "/sdcard/Download/Mimonitor_Toolbox/.mtk_action_b2.txt"])
        with self.assertRaisesRegex(RuntimeError, "Picture bank changed"):
            parse_native_action_result(output, "setPictureMode", {"g_video__picture_mode": 15})
        state = parse_native_picture_state(session.call("native", ["getPictureState",
            "/sdcard/Download/Mimonitor_Toolbox/.mtk_action_c3.txt"]))
        self.assertEqual(state["g_video__picture_mode"], 16)
        self.assertEqual(self.session_values(session, "test_write_count")["test_write_count"], 1)

    def test_readonly_worker_rejects_setters_before_any_native_write(self):
        session = self.start_session(readonly=True)
        with self.assertRaisesRegex(RuntimeError, "Read-only session"):
            session.call("native", ["set", "g_video__brightness", 42, 3])
        self.assertEqual(self.session_values(session, "test_write_count")["test_write_count"], 0)

    def test_session_authentication_failure_does_not_execute_a_setter(self):
        session = self.start_session()
        token = session.token
        session.token = "invalid"
        with self.assertRaisesRegex(RuntimeError, "authentication failed"):
            session.call("native", ["set", "g_video__brightness", 42, 3])
        session.token = token
        self.assertEqual(self.session_values(session, "test_write_count")["test_write_count"], 0)

    def test_lost_setter_reply_does_not_repeat_the_write(self):
        import socket
        import struct
        session = self.start_session()
        payload = (session.token + "\nnative\nset\ng_video__brightness\n42\n3").encode()
        with socket.create_connection(("127.0.0.1", session.port)) as connection:
            connection.sendall(struct.pack(">I", len(payload)) + payload)
            size = struct.unpack(">I", session._receive(connection, 4))[0]
            self.assertEqual(session._receive(connection, size), b"READY")
            connection.sendall(struct.pack(">I", 2) + b"GO")
        # The next request is processed after the setter, without replaying it.
        self.assertEqual(self.session_values(session, "test_write_count")["test_write_count"], 1)

    def test_abandoned_request_is_not_executed_without_live_client_ack(self):
        import socket
        import struct
        session = self.start_session()
        payload = (session.token + "\nnative\nset\ng_video__brightness\n42\n3").encode()
        with socket.create_connection(("127.0.0.1", session.port)) as connection:
            connection.sendall(struct.pack(">I", len(payload)) + payload)
            size = struct.unpack(">I", session._receive(connection, 4))[0]
            self.assertEqual(session._receive(connection, size), b"READY")
        self.assertEqual(self.session_values(session, "test_write_count")["test_write_count"], 0)

    def test_session_led_dispatch_matches_all_2025_menu_protocol_values(self):
        session = self.start_session()
        commands = [(effect, color) for effect in range(1, 5) for color in range(1, 13)]
        commands += [(5, 0), (5, 1)] + [(0, color) for color in range(12)]
        for mode, color in commands:
            output = session.call("led", [mode, color])
            self.assertEqual(output, f"mode={mode}\ncolor={color}\nreturn=0\n__complete=1\n")
        self.assertEqual(self.session_values(session, "test_write_count")["test_write_count"], len(commands))
        for mode, color in [(5, 2), (0, 12), (1, 0), (11, 5)]:
            with self.assertRaisesRegex(RuntimeError, "Invalid LED command"):
                session.call("led", [mode, color])
        self.assertEqual(self.session_values(session, "test_write_count")["test_write_count"], len(commands))
