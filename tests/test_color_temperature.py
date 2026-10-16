"""2025 firmware's database observer consumes native, not UI, color-temperature enums."""
from types import SimpleNamespace
from contextlib import nullcontext
from unittest import TestCase, mock

from mimonitor_toolbox.display_features import DisplayFeaturesMixin
from mimonitor_toolbox import presets


class ColorTemperatureTests(TestCase):
    def host(self, readback=2):
        adb = mock.Mock()
        adb.transaction = nullcontext
        adb.jni_batch_get_or_single.return_value = {"g_video__clr_temp": readback}
        host = SimpleNamespace(adb=adb, current_vals={}, check_connection=lambda: True,
            _mark_adb_busy=lambda *args: None, _take_control_previous=lambda *args: 3,
            _note_picture_change=lambda: None, log=lambda *args: None,
            _optimistic_highlight=mock.Mock())
        def run(label, operation, success, failure):
            operation()
            success()
        host._run_adb_action = run
        return host

    def test_standard_writes_native_two_but_keeps_ui_one(self):
        host = self.host()
        DisplayFeaturesMixin._set_color_temp(host, 2, 1, "标准")
        host.adb.put_many.assert_called_once_with({"picture_color_temperature": "2"}, check=True, refresh=True)
        self.assertEqual(host.current_vals["picture_color_temperature"], 1)

    def test_observer_overwrite_cannot_be_reported_as_success(self):
        host = self.host(readback=1)
        with self.assertRaisesRegex(RuntimeError, "色温最终回读不一致"):
            DisplayFeaturesMixin._set_color_temp(host, 2, 1, "标准")
        host._optimistic_highlight.assert_not_called()

    def test_custom_rgb_preset_synchronizes_native_zero(self):
        adb = mock.Mock()
        presets._apply_color_gains(adb, {"picture_red_gain": 985, "picture_green_gain": 1025,
                                       "picture_blue_gain": 955})
        self.assertIn(mock.call("picture_color_temperature", "0", check=True), adb.put.call_args_list)
