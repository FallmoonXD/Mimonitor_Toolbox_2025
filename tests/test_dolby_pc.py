import _isolation  # noqa: F401
import ctypes
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from mimonitor_toolbox import dolby_pc as pc
from mimonitor_toolbox.windows_display import DevMode, WindowsDisplay, signal_matches

TARGET=r'\\?\DISPLAY#XMI27B3#5&test&UID4352#{guid}'
TEMPLATE=bytes.fromhex((Path(__file__).resolve().parents[1]/'assets/display/xmi27b3-320.hex').read_text())


class ProfileTests(unittest.TestCase):
    def test_profile_preserves_unit_identity_and_recalculates_every_checksum(self):
        identity=bytearray(TEMPLATE)
        identity[12:18]=bytes.fromhex('876543211a24')
        identity[127]=(-sum(identity[:127]))&255
        profile=pc.compatible_profile(TEMPLATE,identity)
        self.assertEqual(profile[8:18],identity[8:18])
        self.assertEqual(profile[126],2)
        self.assertIn(pc.PC_DOLBY_BLOCK,profile)
        self.assertNotIn(pc.NATIVE_DOLBY_BLOCK,profile)
        self.assertTrue(all(sum(profile[i:i+128])%256==0 for i in range(0,384,128)))
        self.assertEqual(profile[256:-1],TEMPLATE[256:-1])

    def test_unknown_hardware_and_damaged_data_are_rejected(self):
        for data in (TEMPLATE[:-1],b'\0'*384,bytes([TEMPLATE[0]^1])+TEMPLATE[1:]):
            with self.subTest(data=data[:8]),self.assertRaises(ValueError):
                pc.compatible_profile(TEMPLATE,data)

    def test_only_exact_2025_instance_is_accepted(self):
        self.assertEqual(pc.monitor_instance(TARGET),r'DISPLAY\XMI27B3\5&test&UID4352')
        for value in (TARGET.replace('XMI27B3','XMI3009'),TARGET.replace('5&test','..\\other'),
                      r'\\?\DISPLAY#VIRTUAL#2#{guid}','XMI27B3',TARGET+'#extra'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                pc.monitor_instance(value)

    def test_signal_checks_actual_resolution_and_fractional_refresh(self):
        self.assertTrue(signal_matches({'width':1920,'height':1080,'hz':319.975},1920,1080,320))
        self.assertFalse(signal_matches({'width':3840,'height':2160,'hz':120},1920,1080,320))
        self.assertFalse(signal_matches({'width':1920,'height':1080,'hz':120},1920,1080,320))

    @unittest.skipUnless(__import__('sys').platform=='win32','Windows ABI')
    def test_windows_abi_matches_sdk_sizes(self):
        from mimonitor_toolbox.windows_display import PathInfo,ModeInfo,TargetName
        self.assertEqual([ctypes.sizeof(t) for t in (DevMode,PathInfo,ModeInfo,TargetName)],[220,72,64,420])


class TransitionTests(unittest.TestCase):
    def make_transition(self):
        with mock.patch.object(pc,'WindowsDisplay'):
            obj=pc.DisplayTransition(mock.Mock(),TARGET)
        dm=DevMode();dm.width=3840;dm.height=2160;dm.hz=160;dm.bits=32
        obj.old_mode=bytes(dm);obj.old_hdr=True;obj.before={pc.EDID:3,pc.FS:1,'g_video__picture_mode':13,'g_dovi_info__':1}
        obj._prepare=mock.Mock();obj._wait=mock.Mock();obj._check_signal=mock.Mock(return_value=obj.before)
        obj.windows.current_mode.return_value=bytes(dm)
        obj.windows.find_mode.return_value=bytes(dm)
        obj.windows.signal.return_value={'width':1920,'height':1080,'hz':319.975}
        return obj

    def test_hdr_enable_is_followed_by_another_explicit_320_selection(self):
        obj=self.make_transition();calls=[]
        obj.windows.set_hdr.side_effect=lambda value:calls.append(('hdr',value))
        obj.windows.select_mode.side_effect=lambda *mode:calls.append(('mode',mode))
        with mock.patch.object(pc,'read_profile_state',return_value={'values':{'0':'data'},'compatible':True,'enabled':True}), \
             mock.patch.object(pc,'NativeRecovery') as watchdog:
            result=obj.set_320(True)
        self.assertEqual(calls,[('hdr',False),('mode',(1920,1080,320)),('hdr',True),('mode',(1920,1080,320))])
        self.assertEqual(result['normal_mode'],obj.old_mode)
        watchdog.return_value.stop.assert_called_once()

    def test_original_override_is_not_mistaken_for_compatible_profile(self):
        obj=self.make_transition()
        with mock.patch.object(pc,'read_profile_state',return_value={'values':{'0':'original'},'compatible':False}), \
             mock.patch.object(pc,'NativeRecovery') as watchdog:
            with self.assertRaisesRegex(RuntimeError,'兼容'):
                obj.set_320(True)
        watchdog.assert_not_called()
        obj.windows.set_hdr.assert_not_called()

    def test_windows_mode_failure_recovers_instead_of_reporting_success(self):
        obj=self.make_transition();obj.windows.select_mode.side_effect=RuntimeError('mode unavailable')
        obj._recover=mock.Mock()
        with mock.patch.object(pc,'read_profile_state',return_value={'values':{},'compatible':True,'enabled':True}), \
             mock.patch.object(pc,'NativeRecovery'):
            with self.assertRaisesRegex(RuntimeError,'mode unavailable'):
                obj.set_320(True)
        obj._recover.assert_called_once();obj._check_signal.assert_not_called()

    def test_hardware_firmware_and_freesync_are_checked_before_windows_writes(self):
        with mock.patch.object(pc,'WindowsDisplay'):
            obj=pc.DisplayTransition(mock.Mock(),TARGET)
        obj.adb.get.return_value='23'
        obj.adb.shell.return_value='different firmware'
        with self.assertRaisesRegex(RuntimeError,'固件'):
            obj._prepare()
        obj.windows.set_hdr.assert_not_called()
        obj.adb.shell.return_value='OS3.0.109.0.UFFMAMN'
        obj.adb.jni_batch_get_or_single.return_value={pc.EDID:3,pc.FS:0}
        with self.assertRaisesRegex(RuntimeError,'FreeSync'):
            obj._prepare()

    def test_temporary_sdr_cannot_be_mistaken_for_completed_hdr_switch(self):
        obj=self.make_transition();obj._wait=mock.Mock()
        obj.adb.read_picture_state.return_value={'g_video__picture_mode':10,'g_dovi_info__':0}
        obj.adb.shell.return_value='1\n0'
        obj.windows.signal.return_value={'width':3840,'height':2160,'hz':159.975}
        obj.windows.hdr_enabled.return_value=True
        obj.adb.jni_batch_get_or_single.return_value=obj.before
        obj._check_signal=pc.DisplayTransition._check_signal.__get__(obj)
        obj._check_signal(obj.old_mode,False)
        predicate=obj._wait.call_args.args[0]
        self.assertFalse(predicate())
        obj.adb.read_picture_state.return_value={'g_video__picture_mode':16,'g_dovi_info__':0}
        self.assertTrue(predicate())

    def test_saved_normal_resolution_is_required_when_starting_in_320(self):
        obj=self.make_transition()
        dm=DevMode.from_buffer_copy(obj.old_mode);dm.width=1920;dm.height=1080;dm.hz=320;obj.old_mode=bytes(dm)
        with mock.patch.object(pc,'read_profile_state',return_value={'values':{},'compatible':True,'enabled':True}), \
             mock.patch.object(pc,'NativeRecovery') as watchdog:
            with self.assertRaisesRegex(RuntimeError,'尚未记录'):
                obj.set_320(False)
        watchdog.assert_not_called()

    def test_recovery_restores_registry_before_hdmi_hotplug(self):
        obj=self.make_transition();calls=[]
        obj.registry_change=mock.Mock();obj.registry_change.finish.side_effect=lambda value:calls.append('registry')
        obj._native_edid=mock.Mock(side_effect=lambda value:calls.append(value))
        obj.recovery=mock.Mock()
        with mock.patch.object(pc.time,'sleep'):
            obj._recover()
        self.assertEqual(calls,['registry',5,3])
        obj.windows.apply_mode.assert_called_once_with(obj.old_mode)

    def test_hdr_transition_waits_for_stable_sdr_output_before_enabling_hdr(self):
        obj=self.make_transition();calls=[]
        obj._wait_family=mock.Mock(side_effect=lambda family,mode=None:calls.append(('stable',family)))
        obj.windows.set_hdr.side_effect=lambda enabled:calls.append(('hdr',enabled))
        obj.windows.select_mode.side_effect=lambda *args:calls.append(('mode',args))
        with mock.patch.object(pc,'read_profile_state',return_value={'values':{},'compatible':True,'enabled':True}), \
             mock.patch.object(pc,'NativeRecovery'):
            obj.set_320(True)
        self.assertLess(calls.index(('mode',(1920,1080,320))),calls.index(('hdr',True)))
        self.assertEqual(calls[:4],[('hdr',False),('stable','SDR'),('mode',(1920,1080,320)),('stable','SDR')])
        self.assertIn(('stable','Dolby Vision'),calls)

    def test_repeated_320_off_keeps_current_normal_mode_without_reconnection(self):
        obj=self.make_transition()
        with mock.patch.object(pc,'read_profile_state',return_value={'values':{},'compatible':True,'enabled':True}), \
             mock.patch.object(pc,'NativeRecovery') as watchdog:
            obj.set_320(False)
        watchdog.assert_not_called();obj.windows.set_hdr.assert_not_called();obj.windows.apply_mode.assert_not_called()

    def test_repeated_pc_enable_verifies_without_elevation_or_hdr_toggle(self):
        obj=self.make_transition()
        with mock.patch.object(pc,'read_profile_state',return_value={'compatible':True,'managed':True,'enabled':True}), \
             mock.patch.object(pc,'EdidChange') as registry, mock.patch.object(pc,'NativeRecovery') as watchdog:
            obj.set_pc_dolby('on')
        registry.assert_not_called();watchdog.assert_not_called();obj.windows.set_hdr.assert_not_called()


class RegistryReadTests(unittest.TestCase):
    @unittest.skipUnless(__import__('sys').platform=='win32','Windows registry')
    def test_profile_read_is_scoped_to_exact_monitor_and_never_writes(self):
        import winreg
        with mock.patch.object(winreg,'OpenKey') as opened, \
             mock.patch.object(winreg,'QueryValueEx',return_value=(TEMPLATE,winreg.REG_BINARY)), \
             mock.patch.object(winreg,'QueryInfoKey',return_value=(0,0,0)), \
             mock.patch.object(winreg,'CreateKey') as created, mock.patch.object(winreg,'SetValueEx') as setter:
            state=pc.read_profile_state(TARGET)
        opened.assert_called_once_with(winreg.HKEY_LOCAL_MACHINE,
            r'SYSTEM\CurrentControlSet\Enum\DISPLAY\XMI27B3\5&test&UID4352\Device Parameters')
        self.assertFalse(state['managed']);created.assert_not_called();setter.assert_not_called()


class WindowsHdrTests(unittest.TestCase):
    def test_hdr_request_is_not_skipped_due_to_cached_advanced_color_flag(self):
        from mimonitor_toolbox.windows_display import PathInfo,SetAdvancedColor
        obj=WindowsDisplay.__new__(WindowsDisplay)
        path=PathInfo();path.target.id=42
        obj._path=mock.Mock(return_value=(path,[]));obj.api=mock.Mock()
        obj.api.DisplayConfigSetDeviceInfo.return_value=0
        obj.hdr_enabled=mock.Mock(return_value=True)
        obj.set_hdr(True)
        obj.hdr_enabled.assert_not_called()
        pointer=obj.api.DisplayConfigSetDeviceInfo.call_args.args[0]
        request=ctypes.cast(pointer,ctypes.POINTER(SetAdvancedColor)).contents
        self.assertEqual((request.header.kind,request.header.id,request.enabled),(10,42,1))

    def test_hdr_read_uses_target_color_space_and_rejects_unknown(self):
        from mimonitor_toolbox import windows
        obj=WindowsDisplay.__new__(WindowsDisplay)
        obj._path=mock.Mock(return_value=(object(),[]));obj._source=mock.Mock(return_value=r'\\.\DISPLAY1')
        with mock.patch.object(windows,'query_windows_hdr_enabled',return_value=False) as read:
            self.assertFalse(obj.hdr_enabled())
        read.assert_called_once_with(target_device_name=r'\\.\DISPLAY1')
        with mock.patch.object(windows,'query_windows_hdr_enabled',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'色彩空间'):
                obj.hdr_enabled()
