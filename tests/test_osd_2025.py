import unittest
from unittest import mock
import _isolation  # noqa: F401
from mimonitor_toolbox.adb import Adb
from mimonitor_toolbox.osd_2025 import LIGHT_KEYS, light_commands, native_option_value
from mimonitor_toolbox.device_features import apply_picture_jni_overrides


class OsdProtectionTests(unittest.TestCase):
    def test_freesync_preserves_normal_and_320hz_edid_families(self):
        from mimonitor_toolbox.presets import set_freesync
        for edid, on_value, off_value in ((1, 1, 0), (3, 1, 0), (5, 3, 2), (6, 3, 2)):
            for enabled, wanted in ((True, on_value), (False, off_value)):
                with self.subTest(edid=edid, enabled=enabled):
                    a = mock.Mock()
                    a.jni_get.return_value = edid
                    set_freesync(a, '23', enabled)
                    a.jni_set.assert_called_once_with('g_video__freesync_switch', wanted, check=True)

    def test_unknown_hdmi_edid_cannot_trigger_freesync_write(self):
        from mimonitor_toolbox.presets import set_freesync
        a = mock.Mock()
        a.jni_get.return_value = -1
        with self.assertRaises(RuntimeError):
            set_freesync(a, '23', True)
        a.jni_set.assert_not_called()

    def test_blocked_320hz_entry_point_cannot_send_device_writes(self):
        from mimonitor_toolbox.display_features import DisplayFeaturesMixin
        host = mock.Mock()
        host._320_block_reason.return_value = 'Windows EDID override'
        DisplayFeaturesMixin._320(host, True)
        host.adb.jni_set.assert_not_called()
        host.adb.monitor_refresh_mode.assert_not_called()
        host._run_adb_action.assert_not_called()

    def test_hdmi_freesync_one_is_enabled_on_2025(self):
        from mimonitor_toolbox.presets import freesync_is_on
        self.assertTrue(freesync_is_on('g_video__freesync_switch', '1'))
        self.assertTrue(freesync_is_on('g_video__freesync_switch', '3'))
        self.assertFalse(freesync_is_on('g_video__freesync_switch', '0'))
        self.assertFalse(freesync_is_on('g_video__dp_adaptive_sync', '3'))

    def test_dark_enhancement_preserves_gamma_and_reserved_bytes(self):
        before = 0x1234017F
        key, value = native_option_value('dark_enhancement', 3, {'g_video__vid_gamma_mode': before})
        self.assertEqual(key, 'g_video__vid_gamma_mode')
        self.assertEqual(value & ~0xFF00, before & ~0xFF00)
        self.assertEqual((value >> 8) & 255, 3)

    def test_unknown_native_controls_clear_old_highlights(self):
        values = {'osd_dark_enhancement': 2, 'osd_eye_protection': 1, 'tv_picture_video_hdmi_rgb_range': 0}
        apply_picture_jni_overrides(values, {'g_video__vid_gamma_mode': -1,
            'g_video__clr_eye_protection_mode': 'ERROR', 'g_fusion_picture__hdmi_rgb_range': -1})
        self.assertTrue(all(value is None for value in values.values()))

    def test_eye_protection_is_rejected_before_any_device_reads_or_writes(self):
        a = Adb()
        with mock.patch.object(a, 'read_picture_state') as read, mock.patch.object(a, 'put') as put:
            with self.assertRaisesRegex(RuntimeError, '白平衡'):
                a.osd_option('eye_protection', 1)
            read.assert_not_called()
            put.assert_not_called()

    def test_wrong_family_or_mode_is_rejected_before_native_setter(self):
        for option, mode, dovi in (('color_range', 13, 1), ('dark_enhancement', 14, 0)):
            a = Adb()
            with mock.patch.object(a, 'read_picture_state', return_value={'g_video__picture_mode': mode, 'g_dovi_info__': dovi}), \
                    mock.patch.object(a, 'get', return_value='23'), mock.patch.object(a, '_checked_native_action') as write:
                with self.assertRaises(RuntimeError):
                    a.osd_option(option, 1)
                write.assert_not_called()

    def test_dp_color_range_is_rejected_before_native_setter(self):
        a = Adb()
        with mock.patch.object(a, 'read_picture_state', return_value={'g_video__picture_mode': 10, 'g_dovi_info__': 0}), \
                mock.patch.object(a, 'get', return_value='29'), mock.patch.object(a, '_checked_native_action') as write:
            with self.assertRaises(RuntimeError): a.osd_option('color_range', 1)
            write.assert_not_called()

    def test_native_failure_does_not_mirror_settings(self):
        a = Adb()
        with mock.patch.object(a, 'read_picture_state', return_value={'g_video__picture_mode': 13, 'g_dovi_info__': 1}), \
                mock.patch.object(a, 'jni_batch_get_or_single', return_value={'g_video__vid_gamma_mode': 1}), \
                mock.patch.object(a, '_checked_native_action', side_effect=RuntimeError('failed')), mock.patch.object(a, 'put') as put:
            with self.assertRaises(RuntimeError): a.osd_option('dark_enhancement', 1)
            put.assert_not_called()

    def test_all_twelve_colors_use_2025_driver_indices(self):
        for color in range(12):
            values = dict(zip(LIGHT_KEYS, (1, 0, color, 0)))
            self.assertEqual(light_commands(values), [(1, color + 1)])
        values = dict(zip(LIGHT_KEYS, (1, 3, 11, 1)))
        self.assertEqual(light_commands(values), [(5, 1)])
        values[LIGHT_KEYS[0]] = 0
        self.assertEqual(light_commands(values), [(5, 0), (0, 11)])

    def test_missing_or_invalid_light_state_is_never_defaulted(self):
        with self.assertRaises(KeyError): light_commands({})
        values = dict(zip(LIGHT_KEYS, (1, 0, 12, 0)))
        with self.assertRaises(ValueError): light_commands(values)

    def test_light_driver_failure_does_not_change_osd_settings(self):
        a = Adb()
        values = dict(zip(LIGHT_KEYS, ('1', '0', '2', '0')))
        with mock.patch.object(a, 'get_many', return_value=values), \
                mock.patch.object(a, '_session_call', return_value='mode=1\ncolor=3\nreturn=-1\n__complete=1\n'), \
                mock.patch.object(a, 'put') as put:
            with self.assertRaises(RuntimeError): a.monitor_lights({LIGHT_KEYS[1]: 0})
            put.assert_not_called()
