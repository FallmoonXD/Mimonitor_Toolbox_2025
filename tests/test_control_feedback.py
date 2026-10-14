import os
import time
import unittest
from unittest import mock
import _isolation  # noqa: F401
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PyQt6.QtTest import QTest
from mimonitor_toolbox.display_features import DisplayFeaturesMixin
from mimonitor_toolbox.pages import PagesMixin
from mimonitor_toolbox.system_picture_2025 import GAMMA_OFFSETS, SYSTEM_OPTIONS
from mimonitor_toolbox.adb import Adb

_app = QApplication.instance() or QApplication([])


class FeedbackHost(QWidget, DisplayFeaturesMixin, PagesMixin):
    def __init__(self):
        super().__init__()
        self.current_vals = {"control": 0}
        self.state_buttons = {}
        self.mode_btns = {}
        self._control_rollback_values = {}
        self.check_connection = lambda: True
        self._update_osd_availability = lambda: None
        self._update_monitor_light_controls = lambda: None
        self._update_system_picture_controls = lambda: None
        self.command_count = 0
        layout = QVBoxLayout(self)
        self._btn_section(layout, "Control", [("Off", 0, self.request), ("On", 1, self.request)], "control")
        self._optimistic_highlight("control", 0)
        self.show()

    def request(self, _checked):
        self.command_count += 1
        self.feedback = self._dispatching_control
        self._pending_controls["control"]["claimed"] = True


class ControlFeedbackTests(unittest.TestCase):
    def test_click_is_immediate_without_falsifying_confirmed_value_and_rolls_back(self):
        host = FeedbackHost()
        try:
            button = host.state_buttons["control"][1]
            start = time.perf_counter()
            button.click()
            self.assertLess(time.perf_counter() - start, .1)
            self.assertTrue(button.isChecked())
            self.assertIn("…", button.text())
            self.assertEqual(host.current_vals["control"], 0)
            # A periodic stale read must not remove the pending feedback.
            host._optimistic_highlight("control", 0)
            self.assertTrue(button.isChecked())
            button.click()
            self.assertEqual(host.command_count, 1)
            host._finish_control_feedback(*host.feedback, False)
            self.assertFalse(button.isChecked())
            self.assertTrue(host.state_buttons["control"][0].isChecked())
            self.assertTrue(button.isEnabled())
            self.assertEqual(button.text(), "On")
        finally:
            host.close(); host.deleteLater(); _app.processEvents()

    def test_success_uses_confirmed_readback(self):
        host = FeedbackHost()
        try:
            button = host.state_buttons["control"][1]
            button.click()
            host.current_vals["control"] = 1
            host._finish_control_feedback(*host.feedback, True)
            self.assertTrue(button.isChecked())
            self.assertFalse(host.state_buttons["control"][0].isChecked())
            self.assertEqual(button.text(), "On")
        finally:
            host.close(); host.deleteLater(); _app.processEvents()


class ChoiceFeedbackHost(FeedbackHost):
    def __init__(self):
        super().__init__()
        self.current_vals["gamma"] = 2
        self._choice_section(self.layout(), "Gamma 偏移", [
            (label, value, self.request) for value, label in GAMMA_OFFSETS
        ], "gamma")
        self._optimistic_highlight("gamma", 2)

    def request(self, _checked):
        self.command_count += 1
        self.feedback = self._dispatching_control
        self._pending_controls[self.feedback[0]]["claimed"] = True


class ChoiceFeedbackTests(unittest.TestCase):
    def test_native_readback_changes_selection_without_writing(self):
        host = ChoiceFeedbackHost()
        try:
            combo, _status = host.state_choices["gamma"]
            for native, label in GAMMA_OFFSETS:
                host._optimistic_highlight("gamma", native)
                self.assertEqual(combo.currentText(), label)
                self.assertEqual(combo.currentData(), native)
            self.assertEqual(host.command_count, 0)
            host._optimistic_highlight("gamma", 99)
            self.assertEqual(combo.currentIndex(), -1)
        finally:
            host.close(); host.deleteLater(); _app.processEvents()

    def test_pending_selection_survives_stale_reads_and_rolls_back_on_failure(self):
        host = ChoiceFeedbackHost()
        try:
            combo, status = host.state_choices["gamma"]
            combo.setCurrentIndex(6)  # label 2, native 1
            combo.activated.emit(6)
            self.assertEqual(host.command_count, 1)
            self.assertEqual(host.current_vals["gamma"], 2)
            self.assertFalse(combo.isEnabled())
            self.assertEqual(status.text(), "正在应用…")
            host._optimistic_highlight("gamma", 2)
            self.assertEqual(combo.currentData(), 1)
            host._finish_control_feedback(*host.feedback, False)
            self.assertEqual(combo.currentData(), 2)
            self.assertTrue(combo.isEnabled())
            self.assertEqual(status.text(), "")
        finally:
            host.close(); host.deleteLater(); _app.processEvents()

    def test_success_displays_confirmed_native_value(self):
        host = ChoiceFeedbackHost()
        try:
            combo, status = host.state_choices["gamma"]
            combo.setCurrentIndex(6)
            combo.activated.emit(6)
            host.current_vals["gamma"] = 1
            host._finish_control_feedback(*host.feedback, True)
            self.assertEqual(combo.currentData(), 1)
            self.assertEqual(combo.currentText(), "2")
            self.assertEqual(status.text(), "")
        finally:
            host.close(); host.deleteLater(); _app.processEvents()


class SystemPictureSafetyTests(unittest.TestCase):
    def test_gamma_mapping_is_not_linear(self):
        self.assertEqual(dict(GAMMA_OFFSETS), {4:"-4",5:"-3",3:"-2",6:"-1",2:"0",7:"1",1:"2",8:"3",9:"4"})

    def test_gamma_policy_preserves_black_stretch_and_reserved_bits(self):
        from mimonitor_toolbox.osd_2025 import native_option_value
        key, value = native_option_value("gamma_policy", 1, {"g_video__vid_gamma_mode": 0x12340300})
        self.assertEqual(key, "g_video__vid_gamma_mode")
        self.assertEqual(value, 0x12340301)

    def test_system_menu_mode_restrictions_are_checked_before_native_writes(self):
        a = Adb()
        for option, bank, dovi in (("local_contrast",13,1), ("black_correction",14,0), ("contrast_enhancement",18,0), ("smooth_gradient",10,0)):
            with mock.patch.object(a,"read_picture_state",return_value={"g_video__picture_mode":bank,"g_dovi_info__":dovi}), mock.patch.object(a,"_checked_native_action") as native:
                with self.assertRaises(RuntimeError):a.system_picture_option(option,0)
                native.assert_not_called()

    def test_helper_cache_requires_a_successful_receipt_and_does_not_cross_devices(self):
        a = Adb("192.0.2.1")
        with mock.patch.object(a, "_jar_fingerprint", return_value=("test.jar", 2000, 1)), mock.patch.object(a, "shell", return_value="2000") as shell:
            a._confirm_remote_jar("test.jar", "test.jar")
            self.assertTrue(a._check_and_heal_remote_jar("test.jar", "test.jar", check=True))
            shell.assert_not_called()
            a.ip = "192.0.2.2"
            self.assertTrue(a._check_and_heal_remote_jar("test.jar", "test.jar", check=True))
            self.assertEqual(shell.call_count, 2)

    def test_calibration_and_reset_keys_are_not_writable_options(self):
        self.assertNotIn("color_booster", SYSTEM_OPTIONS)
        for item in SYSTEM_OPTIONS.values():
            self.assertNotIn("color_tuner", item[1])
            self.assertNotIn("pq_wb_cor", item[1])
            self.assertNotIn("reset", item[1])

    def test_changed_bank_is_rejected_before_writing(self):
        a = Adb()
        with mock.patch.object(a, "read_picture_state", return_value={"g_video__picture_mode":13,"g_dovi_info__":1}), mock.patch.object(a,"_checked_native_action") as native:
            with self.assertRaises(RuntimeError):
                a.system_picture_option("gamma_offset", 2, expected_bank=16)
            native.assert_not_called()

    def test_native_failure_does_not_update_database(self):
        a = Adb()
        with mock.patch.object(a,"read_picture_state",return_value={"g_video__picture_mode":16,"g_dovi_info__":0}), mock.patch.object(a,"_checked_native_action",side_effect=RuntimeError("failed")), mock.patch.object(a,"put") as put:
            with self.assertRaises(RuntimeError):a.system_picture_option("gamma_offset", 2, expected_bank=16)
            put.assert_not_called()


if __name__ == "__main__":
    unittest.main()
