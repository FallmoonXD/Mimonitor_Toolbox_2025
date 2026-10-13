"""Native scene contracts and HDR/Dolby source changes without hardware access."""
import unittest
from unittest import mock

import _isolation  # noqa: F401
from PyQt6.QtWidgets import QApplication
from mimonitor_toolbox import adb as adb_runtime, device_features, presets
from mimonitor_toolbox.main_window import App
from mimonitor_toolbox.picture_modes import (
    NATIVE_MODE_NAMES, picture_mode_choices, picture_signal_family, validate_mode_target,
)


def state(mode=13, dovi=1, tone=0):
    return {"g_video__picture_mode": mode, "g_dovi_info__": dovi,
            "g_video__vid_hdr_tone_mapping_mode": tone}


class NativeModeControlTests(unittest.TestCase):
    def test_2025_dolby_modes_use_converted_mtk_numbers(self):
        expected = {5: "IQ", 59: "明亮", 6: "暗场", 13: "游戏", 61: "自定义"}
        self.assertEqual(dict(picture_mode_choices(13, 1)), expected)
        self.assertEqual(NATIVE_MODE_NAMES[13], "Dolby Vision 游戏")
        self.assertEqual(NATIVE_MODE_NAMES[61], "Dolby Vision 自定义")
        self.assertEqual(NATIVE_MODE_NAMES[16], "HDR 游戏")

    def test_mode_zero_is_a_real_native_custom_mode(self):
        values = {}
        device_features.apply_picture_signal_reads(values, state(0, 0))
        self.assertEqual(values["g_video__picture_mode"], 0)
        self.assertEqual(picture_signal_family(0, 0), "SDR")

    def test_source_and_mode_disagreement_is_not_guessed_as_hdr_or_dolby(self):
        for mode, dovi in [(13, 0), (16, 1), (77, 0), (None, 1)]:
            with self.subTest(mode=mode, dovi=dovi):
                self.assertIsNone(picture_signal_family(mode, dovi))

    def test_cross_source_native_mode_writes_are_refused(self):
        for target, mode, dovi in [(59, 16, 0), (16, 13, 1), (14, 16, 0)]:
            with self.subTest(target=target), self.assertRaises(ValueError):
                validate_mode_target(target, mode, dovi)

    def test_backend_validates_native_then_database_and_final_readback(self):
        target = adb_runtime.Adb("192.168.1.9")
        with mock.patch.object(target, "read_picture_state", side_effect=[state(), state(59)]) as read, \
                mock.patch.object(target, "_checked_native_action", return_value={"warnings": []}) as setter, \
                mock.patch.object(target, "put") as put:
            result = target.picture_mode(59, expected_bank=13)
        setter.assert_called_once_with("setPictureMode", [59, 3], {"g_video__picture_mode": 59}, expected_bank=13)
        self.assertEqual(put.call_args_list, [mock.call("picture_mode", "59", check=True),
                                             mock.call("picture_mode_dolby", "59", check=True)])
        self.assertEqual(read.call_count, 2)
        self.assertEqual(result["state"], state(59))

    def test_mode_source_changes_before_write_do_not_write_native_or_database(self):
        target = adb_runtime.Adb("192.168.1.9")
        with mock.patch.object(target, "read_picture_state", return_value=state(16, 0)), \
                mock.patch.object(target, "_checked_native_action") as setter, \
                mock.patch.object(target, "put") as put:
            with self.assertRaises(RuntimeError):
                target.picture_mode(59, expected_bank=13)
        setter.assert_not_called()
        put.assert_not_called()

    def test_mode_final_readback_cannot_silently_accept_a_new_source(self):
        target = adb_runtime.Adb("192.168.1.9")
        with mock.patch.object(target, "read_picture_state", side_effect=[state(), state(16, 0)]), \
                mock.patch.object(target, "_checked_native_action", return_value={}), \
                mock.patch.object(target, "put"):
            with self.assertRaisesRegex(RuntimeError, "未确认最终生效值"):
                target.picture_mode(59)

    def test_hdr_tone_is_not_written_while_dolby_is_the_actual_signal(self):
        target = adb_runtime.Adb("192.168.1.9")
        with mock.patch.object(target, "read_picture_state", return_value=state()), \
                mock.patch.object(target, "_checked_native_action") as setter:
            with self.assertRaisesRegex(RuntimeError, "仅在 HDR 输入"):
                target.hdr_tone_mapping(5, check=True)
        setter.assert_not_called()

    def test_preset_uses_native_mode_even_when_database_value_is_stale(self):
        target = mock.Mock()
        presets._apply_picture_mode(target, {"picture_mode": 14, "g_video__picture_mode": 13})
        target.picture_mode.assert_called_once_with(13, check=True)
        target.put.assert_not_called()

    def test_preset_signal_mismatch_stops_before_freesync_or_picture_writes(self):
        target = mock.Mock()
        target.read_picture_state.return_value = state(16, 0)
        result = presets.apply_preset(target, {"g_video__picture_mode": 13, "freesync": 1})
        self.assertTrue(result.failed)
        target.jni_set.assert_not_called()
        target.picture_mode.assert_not_called()


class NativeSignalUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        with mock.patch.object(App, "register_global_hotkeys"), \
                mock.patch.object(App, "setup_tray"), \
                mock.patch.object(App, "_auto_connect_on_startup"):
            self.window = App()

    def tearDown(self):
        self.window._cleanup_done = True
        self.window.deleteLater()
        self.qt.processEvents()

    def test_windows_hdr_stays_on_while_native_dolby_switch_refreshes_the_ui(self):
        window = self.window
        window._hdr_windows_state = True
        window._apply_polled_values(state())
        window.adb_connected = True
        window.adb.ip = "192.168.1.9"
        generation = window._connection_intent_generation
        with mock.patch.object(window.adb, "picture_mode") as writer, \
                mock.patch.object(window, "_refresh_picture_data_after_hdr_change") as refresh, \
                mock.patch("mimonitor_toolbox.display_features.QTimer.singleShot", side_effect=lambda delay, call: call()):
            window._on_picture_signal_read(generation, window.adb.ip, window._picture_mode_switch_seq, state(16, 0, 5))
            self.assertTrue(window._hdr_windows_state)
            self.assertEqual(window.picture_signal_label.text(), "当前信号：HDR")
            self.assertTrue(window.mode_btns[16].isChecked())
            self.assertTrue(window.state_buttons["g_video__vid_hdr_tone_mapping_mode"][5].isChecked())
            refresh.assert_called_once()
            writer.assert_not_called()
            window._on_picture_signal_read(generation, window.adb.ip, window._picture_mode_switch_seq, state())
            self.assertEqual(window.picture_signal_label.text(), "当前信号：Dolby Vision")
            self.assertTrue(window.mode_btns[13].isChecked())
            self.assertTrue(all(not button.isEnabled() and not button.isChecked()
                                for button in window.state_buttons["g_video__vid_hdr_tone_mapping_mode"].values()))

    def test_unknown_tone_keeps_its_raw_value_without_showing_an_old_strategy(self):
        window = self.window
        for raw in (4, 6):  # 实机 HDR Filmmaker 的 tone 6 也不能套用四档名称。
            with self.subTest(raw=raw):
                window._apply_polled_values({**state(16, 0, raw), "settings_display_hdr_color_tone": 0})
                self.assertEqual(window.current_vals["g_video__vid_hdr_tone_mapping_mode"], raw)
                self.assertEqual(window.hdr_tone_mapping_status.text(), "未知策略")
                self.assertTrue(all(not button.isChecked()
                                    for button in window.state_buttons["g_video__vid_hdr_tone_mapping_mode"].values()))

    def test_late_read_from_previous_connection_cannot_change_the_current_source(self):
        window = self.window
        window._apply_polled_values(state())
        window.adb_connected = True
        window.adb.ip = "192.168.1.9"
        window._on_picture_signal_read(window._connection_intent_generation - 1, window.adb.ip, 0, state(16, 0, 5))
        self.assertEqual(window.current_vals["g_video__picture_mode"], 13)
        self.assertEqual(window.picture_signal_label.text(), "当前信号：Dolby Vision")
