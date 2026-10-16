import struct
import hashlib
from pathlib import Path
import zipfile
import unittest
from unittest import mock

from mimonitor_toolbox.adb import Adb
from mimonitor_toolbox.helper_session import HelperSession


class HelperSessionTransportTests(unittest.TestCase):
    def test_bundled_android_helper_contains_worker_and_matches_java_sources(self):
        root = Path(__file__).resolve().parents[1]
        with zipfile.ZipFile(root / "assets/runtime/MtkDirectTool.jar") as archive:
            self.assertIn(b"LToolboxSession;", archive.read("classes.dex"))
            hashes = dict(line.split("  ", 1)[::-1] for line in archive.read("META-INF/source-sha256").decode().splitlines())
        for name in ("MtkDirectTool.java", "ToolboxSession.java"):
            self.assertEqual(hashes[name], hashlib.sha256((root / "tools/mtk_direct" / name).read_text(encoding="utf-8").encode("utf-8")).hexdigest())

    def test_eof_after_dispatch_never_replays_setter(self):
        session = HelperSession(None)
        session.port = 12345
        connection = mock.MagicMock()
        connection.recv.side_effect = [b""]
        connection.__enter__.return_value = connection
        with mock.patch("mimonitor_toolbox.helper_session.socket.create_connection", return_value=connection) as connect:
            with self.assertRaisesRegex(RuntimeError, "命令未自动重发"):
                session.call("native", ["set", "g_video__brightness", 50, 3])
        self.assertEqual(connect.call_count, 1)
        self.assertEqual(connection.sendall.call_count, 1)

    def test_fragmented_socket_response_is_assembled(self):
        session = HelperSession(None)
        session.port = 12345
        response = b"OK\n0"
        frame = struct.pack(">I", 5) + b"READY" + struct.pack(">I", len(response)) + response
        connection = mock.MagicMock()
        connection.recv.side_effect = [bytes([value]) for value in frame]
        connection.__enter__.return_value = connection
        with mock.patch("mimonitor_toolbox.helper_session.socket.create_connection", return_value=connection):
            self.assertEqual(session.call("native", ["set", "g_video__brightness", 50, 3]), "0")

    def test_backend_does_not_restart_or_resend_after_uncertain_result(self):
        adb = Adb()
        session = adb._helper_session = mock.Mock()
        session.matches.return_value = True
        session.call.side_effect = RuntimeError("uncertain write")
        with mock.patch("mimonitor_toolbox.helper_session.HelperSession") as constructor:
            with self.assertRaisesRegex(RuntimeError, "uncertain write"):
                adb.jni_set("g_video__brightness", 50, check=True)
        constructor.assert_not_called()
        session.call.assert_called_once()

    def test_new_connection_is_allowed_only_before_command_dispatch(self):
        adb = Adb()
        old = adb._helper_session = mock.Mock()
        old.matches.return_value = True
        old.call.side_effect = ConnectionRefusedError()
        new = mock.Mock()
        new.call.return_value = "0"
        with mock.patch("mimonitor_toolbox.helper_session.HelperSession") as constructor:
            constructor.return_value.start.return_value = new
            self.assertEqual(adb.jni_set("g_video__brightness", 50, check=True), "0")
        self.assertEqual(old.call.call_count, 1)
        new.call.assert_called_once()

    def test_old_disconnect_cannot_close_the_new_displays_session(self):
        adb = Adb("192.168.1.10")
        session = adb._helper_session = mock.Mock(identity=("192.168.1.10:5555",))
        adb.close_helper_session(expected_serial="192.168.1.9:5555")
        session.close.assert_not_called()

    def test_frame_display_still_requires_final_database_readback(self):
        adb = Adb()
        with mock.patch.object(adb, "shell", return_value="Starting service\n1\n") as shell:
            self.assertEqual(adb.frame_display(1), 1)
        self.assertEqual(shell.call_count, 1)
        for output in ("Starting service\n0\n", "Error: denied\n1\n", ""):
            with self.subTest(output=output), mock.patch.object(adb, "shell", return_value=output):
                with self.assertRaisesRegex(RuntimeError, "帧率显示未确认"):
                    adb.frame_display(1)
