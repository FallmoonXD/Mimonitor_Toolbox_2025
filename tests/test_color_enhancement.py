import unittest
from unittest import mock
import _isolation  # noqa: F401
from mimonitor_toolbox.adb import Adb
from mimonitor_toolbox.device_features import DeviceFeaturesMixin, apply_picture_jni_overrides
from mimonitor_toolbox import presets
from mimonitor_toolbox.system_picture_2025 import COLOR_CALIBRATION_KEYS
from test_presets import FakeAdb, full_values

KEY = "g_video__vid_auto_color"
DBKEY = "mitv.settings.db.video.color_booster"
STATE = {"g_video__picture_mode": 13, "g_dovi_info__": 1}
CAL = {k: 50 for k in COLOR_CALIBRATION_KEYS}


class ColorEnhancementTests(unittest.TestCase):
    def test_saved_zero_is_applied_after_all_pq_reloads(self):
        adb = FakeAdb()
        values = full_values(mode=13)
        values.update({KEY: 0, **STATE})
        result = presets.apply_preset(adb, values)
        self.assertTrue(result.ok, result.summary())
        self.assertEqual(adb.calls[-1], ("system_picture_option", "color_enhancement", 0, 13))
        self.assertEqual(presets.PICTURE_ITEMS[-1].id, "color_enhancement")

    def test_legacy_preset_does_not_guess_from_cached_database(self):
        adb = FakeAdb()
        values = full_values(mode=13)
        values[DBKEY] = 1
        result = presets.apply_preset(adb, values)
        self.assertTrue(result.ok)
        self.assertFalse(any(c[0] == "system_picture_option" for c in adb.calls))
        self.assertIn("色彩增强", [name for name, _ in result.skipped])

    def test_enhancement_write_failure_is_a_failed_preset(self):
        adb = FakeAdb(fail_on={"system_picture_option"})
        values = full_values(mode=13)
        values[KEY] = 0
        result = presets.apply_preset(adb, values)
        self.assertFalse(result.ok)
        self.assertIn("色彩增强", [name for name, _ in result.failed])

    def test_snapshot_reads_native_zero_instead_of_legacy_database_one(self):
        adb = mock.Mock()
        adb.transaction.return_value.__enter__ = mock.Mock()
        adb.transaction.return_value.__exit__ = mock.Mock()
        adb.shell.return_value = "tv_picture_video_auto_color=1\npicture_mode=13"
        adb.get.return_value = "23"
        adb.jni_batch_get_or_single.side_effect = [{KEY: 0, **STATE}, {"g_video__freesync_switch": 1}]
        host = mock.Mock(adb=adb)
        values = DeviceFeaturesMixin._read_picture_values(host)
        self.assertEqual(values[KEY], 0)
        self.assertIn(KEY, adb.jni_batch_get_or_single.call_args_list[0].args[0])

    def test_unavailable_calibration_stops_before_write(self):
        adb = Adb()
        with mock.patch.object(adb, "read_picture_state", return_value=STATE), \
             mock.patch.object(adb, "jni_batch_get_or_single", return_value={}), \
             mock.patch.object(adb, "_checked_native_action") as native:
            with self.assertRaisesRegex(RuntimeError, "校色参数未完整读取"):
                adb.system_picture_option("color_enhancement", 0, expected_bank=13)
            native.assert_not_called()

    def test_native_calibration_change_does_not_write_database(self):
        adb = Adb()
        changed = {**CAL, "g_fusion_picture__color_tuner_enable": 0}
        with mock.patch.object(adb, "read_picture_state", return_value=STATE), \
             mock.patch.object(adb, "jni_batch_get_or_single", side_effect=[CAL, changed]), \
             mock.patch.object(adb, "_checked_native_action", return_value={"readback": {KEY: 1}}), \
             mock.patch.object(adb, "put") as put:
            with self.assertRaisesRegex(RuntimeError, "校色参数发生变化"):
                adb.system_picture_option("color_enhancement", 1)
            put.assert_not_called()

    def test_database_observer_calibration_change_is_not_success(self):
        adb = Adb()
        final = {**CAL, **STATE, KEY: 0, "g_video__clr_gain_r": 1024}
        with mock.patch.object(adb, "read_picture_state", return_value=STATE), \
             mock.patch.object(adb, "jni_batch_get_or_single", side_effect=[CAL, CAL, final]), \
             mock.patch.object(adb, "_checked_native_action", return_value={"readback": {KEY: 0}}), \
             mock.patch.object(adb, "put") as put:
            with self.assertRaisesRegex(RuntimeError, "校色参数发生变化"):
                adb.system_picture_option("color_enhancement", 0)
            put.assert_called_once_with(DBKEY, 0, check=True)

    def test_changed_bank_stops_color_write(self):
        adb = Adb()
        with mock.patch.object(adb, "read_picture_state", return_value=STATE), \
             mock.patch.object(adb, "_checked_native_action") as native:
            with self.assertRaisesRegex(RuntimeError, "画面场景已变化"):
                adb.system_picture_option("color_enhancement", 0, expected_bank=16)
            native.assert_not_called()

    def test_invalid_level_is_rejected(self):
        with self.assertRaises(ValueError):
            Adb().system_picture_option("color_enhancement", 4)
