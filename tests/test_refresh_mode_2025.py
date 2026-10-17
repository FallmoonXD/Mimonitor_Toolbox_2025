import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import _isolation  # noqa: F401
from mimonitor_toolbox.adb import Adb
from mimonitor_toolbox.osd_2025 import hdmi_refresh_mode_target
from mimonitor_toolbox.display_features import DisplayFeaturesMixin
from mimonitor_toolbox import display_features, windows

EDID = 'g_fusion_picture__hdmi_edid_version'
FS = 'g_video__freesync_switch'
TARGET = r'\\?\DISPLAY#XMI27B3#5&test&UID4352#{guid}'


class RefreshModeTests(unittest.TestCase):
    def setUp(self):
        guard = mock.patch.object(Adb, 'read_picture_state', return_value={'g_video__picture_mode':10,'g_dovi_info__':0})
        guard.start()
        self.addCleanup(guard.stop)

    def test_hdmi_mode_selection_matches_osd_and_preserves_freesync(self):
        for current in (0, 1, 3, 5, 6, 7):
            for fs in (0, 1, 2, 3):
                with self.subTest(current=current, fs=fs):
                    self.assertEqual(hdmi_refresh_mode_target(True, current, fs), (5, 5) if fs in (1, 3) else (6, 6))
                    self.assertEqual(hdmi_refresh_mode_target(False, current, fs), (3, 3) if fs in (1, 3) else (1, 2))

    def test_unknown_edid_or_freesync_is_not_guessed(self):
        for edid, fs in ((-1, 1), (4, 1), (None, 1), (3, -1), (3, None)):
            with self.assertRaises(ValueError):
                hdmi_refresh_mode_target(True, edid, fs)

    def test_hdmi_enable_and_disable_notify_mi_version_not_vendor_offset(self):
        for enabled, before, wanted, fs, mi in ((True, 3, 5, 1, 5), (True, 1, 6, 0, 6),
                                               (False, 5, 3, 1, 3), (False, 6, 1, 0, 2)):
            with self.subTest(enabled=enabled, fs=fs):
                a = Adb()
                with mock.patch.object(a, 'get', return_value='23'), \
                     mock.patch.object(a, 'jni_batch_get_or_single', side_effect=[{EDID:before,FS:fs},{EDID:wanted,FS:fs}]), \
                     mock.patch.object(a, 'jni_set') as setter, mock.patch.object(a, 'shell') as notify:
                    self.assertEqual(a.monitor_refresh_mode(enabled), {EDID:wanted,FS:fs})
                setter.assert_called_once_with(EDID, wanted, check=True)
                notify.assert_called_once_with('am broadcast -f 0x10000000 -a mitv.hdmi.action.EDID_VERSION_CHANGE '
                    '-p com.xiaomi.mitv.tvplayer --ei edid_version '+str(mi), check=True)

    def test_already_selected_mode_does_not_renegotiate(self):
        a = Adb()
        with mock.patch.object(a, 'get', return_value='23'), \
             mock.patch.object(a, 'jni_batch_get_or_single', return_value={EDID:5,FS:1}), \
             mock.patch.object(a, 'jni_set') as setter, mock.patch.object(a, 'shell') as notify:
            a.monitor_refresh_mode(True)
        setter.assert_not_called(); notify.assert_not_called()

    def test_unverified_input_is_rejected_before_native_access(self):
        a = Adb()
        with mock.patch.object(a, 'get', return_value='29'), mock.patch.object(a, 'jni_batch_get_or_single') as read:
            with self.assertRaises(RuntimeError):
                a.monitor_refresh_mode(True)
        read.assert_not_called()

    def test_unconfirmed_source_is_rejected_before_refresh_write(self):
        a=Adb()
        with mock.patch.object(a,'get',return_value='23'), \
             mock.patch.object(a,'read_picture_state',return_value={'g_video__picture_mode':-1,'g_dovi_info__':0}), \
             mock.patch.object(a,'jni_set') as setter:
            with self.assertRaisesRegex(RuntimeError,'输入信号未确认'):
                a.monitor_refresh_mode(True)
        setter.assert_not_called()

    def test_hdr_and_dolby_can_change_hdmi_mode_without_an_sdr_write(self):
        for mode,dovi in ((16,0),(13,1)):
            a=Adb()
            with self.subTest(mode=mode),mock.patch.object(a,'get',return_value='23'), \
                 mock.patch.object(a,'read_picture_state',return_value={'g_video__picture_mode':mode,'g_dovi_info__':dovi}), \
                 mock.patch.object(a,'jni_batch_get_or_single',side_effect=[{EDID:3,FS:1},{EDID:5,FS:1}]), \
                 mock.patch.object(a,'jni_set') as setter,mock.patch.object(a,'shell'):
                a.monitor_refresh_mode(True)
            setter.assert_called_once_with(EDID,5,check=True)

    def test_changed_freesync_cannot_report_success(self):
        a = Adb()
        with mock.patch.object(a, 'get', return_value='23'), \
             mock.patch.object(a, 'jni_batch_get_or_single', side_effect=[{EDID:3,FS:1},{EDID:5,FS:0}]), \
             mock.patch.object(a, 'jni_set'), mock.patch.object(a, 'shell'):
            with self.assertRaisesRegex(RuntimeError, '回读不一致'):
                a.monitor_refresh_mode(True)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows registry lookup')
    def test_edid_override_lookup_uses_only_selected_monitor_instance(self):
        import winreg
        with mock.patch.object(winreg, 'OpenKey') as open_key, \
             mock.patch.object(winreg, 'QueryInfoKey', return_value=(0,1,0)), \
             mock.patch.object(winreg, 'EnumValue', return_value=('0',b'EDID',winreg.REG_BINARY)):
            self.assertTrue(windows.monitor_edid_override_present(TARGET))
        open_key.assert_called_once_with(winreg.HKEY_LOCAL_MACHINE,
            r'SYSTEM\CurrentControlSet\Enum\DISPLAY\XMI27B3\5&test&UID4352\Device Parameters\EDID_OVERRIDE')

    def test_other_display_override_cannot_block_selected_target(self):
        target={'device_id':TARGET,'device_name':r'\\.\DISPLAY1'}
        other={'device_id':r'\\?\DISPLAY#ZAK2333#virtual#{guid}','device_name':r'\\.\DISPLAY10'}
        host=SimpleNamespace(_hdr_target_displays=[target,other], current_vals={'mitv.tvplayer.hdmi.last.source':'23',
                                          'g_video__picture_mode':10,'g_dovi_info__':0})
        with mock.patch.object(display_features,'load_settings',return_value={'hdr_target_display_id':TARGET}), \
             mock.patch.object(display_features,'monitor_edid_override_present',return_value=False) as override:
            self.assertIsNone(DisplayFeaturesMixin._320_block_reason(host))
        override.assert_called_once_with(TARGET)

    def test_selected_target_override_blocks_enable(self):
        target={'device_id':TARGET,'device_name':r'\\.\DISPLAY1'}
        host=SimpleNamespace(_hdr_target_displays=[target], current_vals={'mitv.tvplayer.hdmi.last.source':'23',
                                          'g_video__picture_mode':10,'g_dovi_info__':0})
        with mock.patch.object(display_features,'load_settings',return_value={'hdr_target_display_id':TARGET}), \
             mock.patch.object(display_features,'monitor_edid_override_present',return_value=True):
            self.assertIn('EDID 覆盖', DisplayFeaturesMixin._320_block_reason(host))
