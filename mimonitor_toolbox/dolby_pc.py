"""2025 HDMI PC Dolby profiles, verified transitions and bounded recovery."""

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import uuid

from .core import bundled_resource_path, get_app_data_dir
from .windows_display import DevMode, WindowsDisplay, signal_matches
from .system_picture_2025 import COLOR_CALIBRATION_KEYS, SYSTEM_NATIVE_KEYS
from .picture_modes import picture_signal_family

EDID = 'g_fusion_picture__hdmi_edid_version'
FS = 'g_video__freesync_switch'
PC_DOLBY_BLOCK = bytes.fromhex('eb0146d0004d0a9f5898aa5c')
NATIVE_DOLBY_BLOCK = bytes.fromhex('eb0146d0004d0a9e5898aa5c')
GUARD_KEYS = tuple(dict.fromkeys(COLOR_CALIBRATION_KEYS + SYSTEM_NATIVE_KEYS + (
    'g_video__picture_mode', 'g_dovi_info__', 'g_video__vid_hdr_tone_mapping_mode',
    'g_disp__disp_back_light', 'g_video__vid_local_dimming', 'g_video__brightness',
    'g_video__contrast', 'g_video__vid_sat', 'g_video__vid_hue', 'g_video__vid_shp',
    'g_video__vid_gamut_mapping_mode', 'g_video__vid_od_response_time',
    'g_video__light_sensor_switch', 'g_fusion_picture__hdmi_rgb_range', EDID, FS)))


def monitor_instance(device_id):
    parts = str(device_id).split('#')
    if (len(parts) != 4 or parts[1].upper() != 'XMI27B3'
            or not re.fullmatch(r'[A-Za-z0-9&_-]+', parts[2])):
        raise ValueError('必须选择这一台 2025 款实体显示器')
    return 'DISPLAY\\XMI27B3\\' + parts[2]


def validate_edid(data):
    if (len(data) < 128 or len(data) % 128 or data[:8] != bytes.fromhex('00ffffffffffff00')
            or data[8:12] != bytes.fromhex('61a9b327')
            or any(sum(data[i:i+128]) % 256 for i in range(0,len(data),128))):
        raise ValueError('2025 款 EDID 数据或校验和无效')


def compatible_profile(template, identity):
    validate_edid(template)
    validate_edid(identity)
    if len(template) != 384 or template.count(NATIVE_DOLBY_BLOCK) != 1:
        raise ValueError('320Hz 兼容配置与已验证固件不符')
    data = bytearray(template.replace(NATIVE_DOLBY_BLOCK, PC_DOLBY_BLOCK))
    # Preserve the selected unit's EDID vendor/product/serial/manufacture identity.
    data[8:18] = identity[8:18]
    data[126] = 2
    for start in range(0,len(data),128):
        data[start+127] = (-sum(data[start:start+127])) & 255
    validate_edid(data)
    return bytes(data)


def read_profile_state(device_id):
    import winreg
    instance = monitor_instance(device_id)
    path = 'SYSTEM\\CurrentControlSet\\Enum\\' + instance + '\\Device Parameters'
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,path) as parent:
        raw = winreg.QueryValueEx(parent,'EDID')[0]
        children = [winreg.EnumKey(parent,i) for i in range(winreg.QueryInfoKey(parent)[0])]
    if any(name.startswith('EDID_OVERRIDE_Mimonitor2025_Transaction_') for name in children):
        raise RuntimeError('目标显示器配置切换或自动恢复尚在进行')
    values = {}
    if 'EDID_OVERRIDE' in children:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,path+'\\EDID_OVERRIDE') as key:
            for index in range(winreg.QueryInfoKey(key)[1]):
                name,value,kind = winreg.EnumValue(key,index)
                if kind != winreg.REG_BINARY:
                    raise RuntimeError('目标 EDID 覆盖包含无法识别的值，未作更改')
                values[name] = value.hex()
    block_names = sorted((name for name in values if name.isdigit()),key=int)
    blocks = b''.join(bytes.fromhex(values[name]) for name in block_names)
    meta = {}
    if 'Mimonitor2025_Edid' in children:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,path+'\\Mimonitor2025_Edid') as key:
            for index in range(winreg.QueryInfoKey(key)[1]):
                name,value,_ = winreg.EnumValue(key,index)
                meta[name] = value
    saved = 'EDID_OVERRIDE_Mimonitor2025_Original' in children
    if (saved and not meta or meta and meta.get('Version') != 1
            or meta and bool(meta.get('OriginalPresent')) != saved
            or meta and bool(meta.get('Enabled')) and blocks.hex() != meta.get('Profile')
            or meta and bool(meta.get('Enabled')) and block_names != ['0','1','2']
            or meta and not meta.get('Enabled') and values):
        raise RuntimeError('目标 EDID 已被其他软件修改，请核对后再切换')
    return {'instance':instance,'raw':raw,'values':values,'managed':bool(meta),
            'enabled':bool(meta.get('Enabled')) if meta else PC_DOLBY_BLOCK in blocks,
            'compatible':bool(meta.get('Enabled')) and blocks.hex() == meta.get('Profile'),
            'profile':blocks,'saved':saved}


class EdidChange:
    """Elevate only the registry operation; the helper restores on lost heartbeat."""
    def __init__(self, device_id, action, profile):
        before = read_profile_state(device_id)
        self.token = uuid.uuid4().hex
        folder = Path(get_app_data_dir(),'display-transactions')
        folder.mkdir(parents=True,exist_ok=True)
        self.path = folder/(self.token+'.json')
        self.path.write_text(json.dumps({'version':1,'token':self.token,'instance':before['instance'],
                              'action':action,'profile':profile.hex(),'expected':before['values']}),encoding='utf-8')
        self.process = None
        self.last_heartbeat = 0

    def _reply(self):
        try:
            result = json.loads(Path(str(self.path)+'.reply').read_text(encoding='utf-8-sig'))
            return result if result.get('token') == self.token else {}
        except (FileNotFoundError,ValueError):
            return {}

    def heartbeat(self):
        if time.monotonic()-self.last_heartbeat >= 1:
            Path(str(self.path)+'.lease').write_text(self.token,encoding='ascii')
            self.last_heartbeat = time.monotonic()

    def start(self, heartbeat):
        script = bundled_resource_path('assets','display','edid_profile.ps1')
        if not script:
            raise RuntimeError('程序缺少显示器配置组件，请重新安装')
        powershell = os.path.join(os.environ['SystemRoot'],'System32','WindowsPowerShell','v1.0','powershell.exe')
        arguments = subprocess.list2cmdline(['-NoProfile','-ExecutionPolicy','Bypass','-File',script,'-Request',str(self.path)])
        literal = lambda value: "'"+value.replace("'","''")+"'"
        command = ('try { $p=Start-Process -FilePath '+literal(powershell)+' -ArgumentList '+literal(arguments)
                   +' -Verb RunAs -WindowStyle Hidden -Wait -PassThru; exit $p.ExitCode } catch { Write-Error $_; exit 1 }')
        self.process = subprocess.Popen([powershell,'-NoProfile','-Command',command],
             stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic()+120
        while time.monotonic()<deadline:
            self.heartbeat()
            heartbeat()
            reply = self._reply()
            if reply.get('phase') in ('applied','committed'):
                return
            if reply.get('phase') or self.process.poll() is not None:
                raise RuntimeError(reply.get('detail') or '未获得显示器配置权限，未启用 PC 杜比')
            time.sleep(.1)
        raise RuntimeError('等待显示器配置权限超时')

    def finish(self, commit):
        Path(str(self.path)+'.decision').write_text('commit' if commit else 'rollback',encoding='ascii')
        if self.process:
            try:
                self.process.communicate(timeout=25)
            except subprocess.TimeoutExpired:
                raise RuntimeError('显示器配置恢复尚未完成，请保留程序运行')
        reply = self._reply()
        wanted = 'committed' if commit else 'rolled_back'
        if commit and reply.get('phase') != wanted:
            raise RuntimeError(reply.get('detail') or '显示器配置未确认完成')
        if reply.get('phase') == 'recovery_failed':
            raise RuntimeError(reply.get('detail') or '显示器 EDID 恢复失败')
        if (reply.get('phase') in ('committed','rolled_back','rejected')
                or not reply and (self.process is None or self.process.poll() is not None)):
            for suffix in ('','.reply','.reply.tmp','.decision','.lease'):
                Path(str(self.path)+suffix).unlink(missing_ok=True)


class NativeRecovery:
    def __init__(self, adb, original):
        self.adb,self.original = adb,original
        self.remote = '/sdcard/Download/Mimonitor_Toolbox/.display_recovery_'+uuid.uuid4().hex
        self.last = 0

    def start(self):
        from .adb import build_tvservice_app_process_command
        restore = build_tvservice_app_process_command('/data/data/mitv.service/cache/MtkDirectTool.jar',
                    ['MtkDirectTool','set',EDID,self.original,3])
        mi = {1:2,3:3,5:5,6:6}[self.original]
        script = ('echo $$ > '+self.remote+'.pid\nlast=initial\nidle=0\nwhile [ $idle -lt 16 ]; do\n'
                  ' sleep 1\n current=$(cat '+self.remote+'.lease 2>/dev/null)\n'
                  ' if [ "$current" = "$last" ]; then idle=$((idle+1)); else idle=0; last="$current"; fi\n'
                  'done\n'+restore+'\nam broadcast -f 0x10000000 -a mitv.hdmi.action.EDID_VERSION_CHANGE '
                  '-p com.xiaomi.mitv.tvplayer --ei edid_version '+str(mi)+'\n')
        self.adb.shell('printf %s '+shlex.quote(script)+' > '+self.remote+'.sh; '
                       'nohup sh '+self.remote+'.sh </dev/null >'+self.remote+'.log 2>&1 &',check=True)
        self.heartbeat()

    def heartbeat(self):
        now = time.monotonic()
        if now-self.last >= 2:
            self.adb.shell('echo '+str(int(now*1000))+' > '+self.remote+'.lease',check=True)
            self.last = now

    def stop(self):
        self.adb.shell('if [ -f '+self.remote+'.pid ]; then kill $(cat '+self.remote+'.pid) 2>/dev/null; fi; '
                       'rm -f '+self.remote+'.pid '+self.remote+'.lease '+self.remote+'.sh '+self.remote+'.log',check=True)


class DisplayTransition:
    def __init__(self, adb, device_id):
        self.adb,self.device_id = adb,device_id
        monitor_instance(device_id)
        self.windows = WindowsDisplay(device_id)
        self.registry_change = None
        self.recovery = None

    def _heartbeat(self):
        if self.registry_change:
            self.registry_change.heartbeat()
        if self.recovery:
            self.recovery.heartbeat()

    def _wait(self, predicate, message, timeout=9):
        deadline = time.monotonic()+timeout
        while True:
            self._heartbeat()
            try:
                if predicate():
                    return
            except (OSError,RuntimeError):
                pass
            if time.monotonic()>=deadline:
                raise RuntimeError(message)
            time.sleep(.15)

    def _native_edid(self, value):
        self.adb.jni_set(EDID,value,check=True)
        self.adb.shell('am broadcast -f 0x10000000 -a mitv.hdmi.action.EDID_VERSION_CHANGE '
                       '-p com.xiaomi.mitv.tvplayer --ei edid_version '+str({1:2,3:3,5:5,6:6}[value]),check=True)

    def _wait_mode(self, mode=None):
        desired = DevMode.from_buffer_copy(mode) if mode is not None else None
        self._wait(lambda:self.windows.find_mode(desired.width,desired.height,desired.hz)
                   if desired is not None else self.windows.find_mode(1920,1080,320),
                   'Windows 尚未提供目标分辨率，已停止切换')

    def _wait_family(self, family, mode=None):
        consecutive = 0
        desired = DevMode.from_buffer_copy(mode) if mode is not None else None
        def ready():
            nonlocal consecutive
            state = self.adb.read_picture_state()
            stable = self.adb.shell('getprop debug.signal.stable; getprop debug.signal.unstable',check=True).strip().splitlines()
            matches = (picture_signal_family(state.get('g_video__picture_mode'),state.get('g_dovi_info__')) == family
                       and stable == ['1','0'])
            if desired is not None:
                matches = matches and signal_matches(self.windows.signal(),desired.width,desired.height,desired.hz)
            consecutive = consecutive+1 if matches else 0
            return consecutive >= 2
        message = ('未确认杜比输入，请检查 Windows HDR 页的杜比模式开关及系统杜比支持'
                   if family == 'Dolby Vision' else '等待目标屏 '+family+' 输入稳定超时')
        self._wait(ready,message)

    def _prepare(self):
        if self.adb.get('mitv.tvplayer.hdmi.last.source',check=True).strip() not in ('23','24'):
            raise RuntimeError('PC 杜比和自动 320Hz 目前仅支持 HDMI 输入')
        firmware = self.adb.shell('getprop ro.build.version.incremental',check=True).strip()
        if firmware != 'OS3.0.109.0.UFFMAMN':
            raise RuntimeError('此 PC 杜比配置仅完成 OS3.0.109.0.UFFMAMN 固件验证')
        self.before = self.adb.jni_batch_get_or_single(GUARD_KEYS,check=True)
        if self.before[EDID] not in (3,5) or self.before[FS] != 1:
            raise RuntimeError('请先开启 FreeSync；当前兼容配置仅验证了 FreeSync 开启的 HDMI 档位')
        self.old_hdr = self.windows.hdr_enabled()
        self.old_mode = self.windows.current_mode()
        self.old_signal = self.windows.signal()

    def _check_signal(self, mode, expected_dolby):
        desired = DevMode.from_buffer_copy(mode)
        def ready():
            state = self.adb.read_picture_state()
            stable = self.adb.shell('getprop debug.signal.stable; getprop debug.signal.unstable',check=True).strip().splitlines()
            family = 'Dolby Vision' if expected_dolby else 'HDR' if self.old_hdr else 'SDR'
            return (signal_matches(self.windows.signal(),desired.width,desired.height,desired.hz)
                    and picture_signal_family(state.get('g_video__picture_mode'),state.get('g_dovi_info__')) == family
                    and self.windows.hdr_enabled() == self.old_hdr and stable == ['1','0'])
        self._wait(ready,'目标屏实际时序或杜比输入尚未确认')
        current = self.adb.jni_batch_get_or_single(GUARD_KEYS,check=True)
        if (current['g_video__picture_mode'],current['g_dovi_info__']) == (self.before['g_video__picture_mode'],self.before['g_dovi_info__']):
            changed = [k for k,v in self.before.items() if k != EDID and current.get(k) != v]
            if changed:
                raise RuntimeError('切换后画面参数发生变化：'+', '.join(changed))
        if current[FS] != self.before[FS]:
            raise RuntimeError('FreeSync 状态变化，已停止切换')
        return current

    def _recover(self):
        errors = []
        if self.registry_change:
            try:self.registry_change.finish(False)
            except Exception as error:errors.append(str(error))
            self.registry_change = None
        try:
            self._native_edid(3 if self.before[EDID] == 5 else 5)
            time.sleep(.6)
            self._native_edid(self.before[EDID])
            self._wait_mode(self.old_mode)
            self.windows.set_hdr(self.old_hdr)
            time.sleep(.8)
            self._wait_mode(self.old_mode)
            self.windows.apply_mode(self.old_mode)
            self._check_signal(self.old_mode,bool(self.before['g_dovi_info__']))
            if self.recovery:self.recovery.stop()
        except Exception as error:errors.append(str(error))
        if errors:
            raise RuntimeError('恢复尚未完成：'+'; '.join(errors))

    def set_pc_dolby(self, action, normal_mode=None):
        if action not in ('on','off','restore'):
            raise ValueError('无效的 PC 杜比操作')
        self._prepare()
        wanted_mode,wanted_edid = self.old_mode,self.before[EDID]
        if action == 'restore' and self.before[EDID] == 5:
            if normal_mode is None or DevMode.from_buffer_copy(normal_mode).hz > 160:
                raise RuntimeError('恢复原配置前，请先关闭 320Hz 竞技模式')
            wanted_mode,wanted_edid = normal_mode,3
        state = read_profile_state(self.device_id)
        if (action == 'on' and state['compatible']
                or action == 'off' and state['managed'] and not state['enabled']):
            current = self._check_signal(self.old_mode,bool(self.before['g_dovi_info__']))
            return {'native':current,'signal':self.windows.signal(),'profile':action}
        template_path = bundled_resource_path('assets','display','xmi27b3-320.hex')
        if not template_path:
            raise RuntimeError('缺少 2025 HDMI 兼容配置')
        template = bytes.fromhex(Path(template_path).read_text(encoding='ascii'))
        profile = compatible_profile(template,state['raw'])
        self.recovery = NativeRecovery(self.adb,self.before[EDID])
        try:
            self.recovery.start()
            self.windows.set_hdr(False)
            self._wait_family('SDR')
            self.registry_change = EdidChange(self.device_id,action,profile)
            self.registry_change.start(self._heartbeat)
            self._native_edid(3 if wanted_edid == 5 else 5)
            time.sleep(.7)
            self._native_edid(wanted_edid)
            self._wait_mode(wanted_mode)
            self.windows.apply_mode(wanted_mode)
            self._wait_family('SDR',wanted_mode)
            self.windows.set_hdr(self.old_hdr)
            expected = self.old_hdr and (action == 'on' or action == 'restore' and self._active_pc_block())
            self._wait_family('Dolby Vision' if expected else 'HDR' if self.old_hdr else 'SDR')
            self._wait_mode(wanted_mode)
            self.windows.apply_mode(wanted_mode)
            current = self._check_signal(wanted_mode,expected)
            self.registry_change.finish(True)
            self.registry_change = None
            self.recovery.stop()
            return {'native':current,'signal':self.windows.signal(),'profile':action}
        except Exception as error:
            try:self._recover()
            except Exception as recovery_error:raise RuntimeError(str(error)+'; '+str(recovery_error)) from error
            raise

    def _active_pc_block(self):
        # While the registry transaction is pending its metadata still describes
        # the previous state, so inspect only the active numeric EDID blocks.
        import winreg
        path='SYSTEM\\CurrentControlSet\\Enum\\'+monitor_instance(self.device_id)+'\\Device Parameters\\EDID_OVERRIDE'
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,path) as key:
                return any(PC_DOLBY_BLOCK in winreg.EnumValue(key,i)[1]
                           for i in range(winreg.QueryInfoKey(key)[1]) if winreg.EnumValue(key,i)[0].isdigit())
        except FileNotFoundError:
            return False

    def set_320(self, enabled, normal_mode=None):
        self._prepare()
        state = read_profile_state(self.device_id)
        if enabled and state['values'] and not state['compatible']:
            raise RuntimeError('先开启“杜比视界 PC”以使用兼容 320Hz 的配置')
        if enabled and self.old_hdr and not state['compatible']:
            raise RuntimeError('此配置请先关闭 Windows HDR，或开启“杜比视界 PC”')
        target_mode = self.old_mode
        if not enabled:
            target_mode = normal_mode or self.old_mode
            if DevMode.from_buffer_copy(target_mode).hz > 160:
                raise RuntimeError('尚未记录普通分辨率，请先在 Windows 选择 4K 160Hz')
        if (enabled and self.before[EDID] == 5 or not enabled and self.before[EDID] == 3):
            current = self._check_signal(self.old_mode,bool(self.before['g_dovi_info__']))
            return {'native':current,'signal':self.windows.signal(),'normal_mode':None}
        self.recovery = NativeRecovery(self.adb,self.before[EDID])
        try:
            self.recovery.start()
            self.windows.set_hdr(False)
            self._wait_family('SDR')
            self.adb.monitor_refresh_mode(bool(enabled))
            self._wait_mode(None if enabled else target_mode)
            self._heartbeat()
            if enabled:self.windows.select_mode(1920,1080,320)
            else:self.windows.apply_mode(target_mode)
            first_mode = self.windows.find_mode(1920,1080,320) if enabled else target_mode
            self._wait_family('SDR',first_mode)
            self.windows.set_hdr(self.old_hdr)
            expected = self.old_hdr and state['enabled']
            self._wait_family('Dolby Vision' if expected else 'HDR' if self.old_hdr else 'SDR')
            self._wait_mode(None if enabled else target_mode)
            if enabled:
                self.windows.select_mode(1920,1080,320)
                target_mode = self.windows.find_mode(1920,1080,320)
            else:self.windows.apply_mode(target_mode)
            current = self._check_signal(target_mode,expected)
            self.recovery.stop()
            return {'native':current,'signal':self.windows.signal(),'normal_mode':self.old_mode if enabled and self.before[EDID]==3 else None}
        except Exception as error:
            try:self._recover()
            except Exception as recovery_error:raise RuntimeError(str(error)+'; '+str(recovery_error)) from error
            raise
