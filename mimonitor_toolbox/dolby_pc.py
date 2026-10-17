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
    original_blocks = None
    if saved:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,path+'\\EDID_OVERRIDE_Mimonitor2025_Original') as key:
            original_blocks = {}
            for index in range(winreg.QueryInfoKey(key)[1]):
                name,value,kind = winreg.EnumValue(key,index)
                if name.isdigit():
                    if kind != winreg.REG_BINARY:
                        raise RuntimeError('保存的原 EDID 包含无法识别的值')
                    original_blocks[int(name)] = value
    if (saved and not meta or meta and meta.get('Version') != 1
            or meta and bool(meta.get('OriginalPresent')) != saved
            or meta and bool(meta.get('Enabled')) and blocks.hex() != meta.get('Profile')
            or meta and bool(meta.get('Enabled')) and block_names != ['0','1','2']
            or meta and not meta.get('Enabled') and values):
        raise RuntimeError('目标 EDID 已被其他软件修改，请核对后再切换')
    return {'instance':instance,'raw':raw,'values':values,'managed':bool(meta),
            'enabled':bool(meta.get('Enabled')) if meta else PC_DOLBY_BLOCK in blocks,
            'compatible':bool(meta.get('Enabled')) and blocks.hex() == meta.get('Profile'),
            'profile':blocks,'saved':saved,'original_blocks':original_blocks}


def edid_is_loaded(device_id, identity, expected=None):
    """Read the driver's reported EDID, independently of the pending override key."""
    import winreg
    path = 'SYSTEM\\CurrentControlSet\\Enum\\'+monitor_instance(device_id)+'\\Device Parameters'
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,path) as key:
        current,kind = winreg.QueryValueEx(key,'EDID')
    if kind != winreg.REG_BINARY:
        raise RuntimeError('Windows EDID 缓存类型无效')
    validate_edid(current)
    if current[8:18] != identity[8:18]:
        raise RuntimeError('Windows 目标显示器身份发生变化')
    if isinstance(expected,dict):
        return all(current[index*128:(index+1)*128] == value for index,value in expected.items())
    return current == expected if expected is not None else NATIVE_DOLBY_BLOCK in current and PC_DOLBY_BLOCK not in current


class EdidChange:
    """Elevate only the registry operation; the helper restores on lost heartbeat."""
    def __init__(self, device_id, action, profile, *, refresh='monitor'):
        if refresh not in ('monitor','hdmi'):
            raise ValueError('无效的 EDID 刷新方式')
        before = read_profile_state(device_id)
        self.token = uuid.uuid4().hex
        folder = Path(get_app_data_dir(),'display-transactions')
        folder.mkdir(parents=True,exist_ok=True)
        self.path = folder/(self.token+'.json')
        self.path.write_text(json.dumps({'version':1,'token':self.token,'instance':before['instance'],
                              'action':action,'profile':profile.hex(),'expected':before['values'],'refresh':refresh}),encoding='utf-8')
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
        alternate = 3 if self.original == 5 else 5
        disconnect = build_tvservice_app_process_command('/data/data/mitv.service/cache/MtkDirectTool.jar',
                    ['MtkDirectTool','set',EDID,alternate,3])
        mi = {1:2,3:3,5:5,6:6}[self.original]
        script = ('echo $$ > '+self.remote+'.pid\nlast=initial\nidle=0\nwhile [ $idle -lt 16 ]; do\n'
                  ' sleep 1\n current=$(cat '+self.remote+'.lease 2>/dev/null)\n'
                  ' if [ "$current" = "$last" ]; then idle=$((idle+1)); else idle=0; last="$current"; fi\n'
                  'done\n'+disconnect+'\nsleep 1\n'+restore+'\nam broadcast -f 0x10000000 -a mitv.hdmi.action.EDID_VERSION_CHANGE '
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
    def __init__(self, adb, device_id, progress=None):
        self.adb,self.device_id = adb,device_id
        monitor_instance(device_id)
        self.windows = WindowsDisplay(device_id)
        self.registry_change = None
        self.recovery = None
        self.progress = progress

    def _stage(self, message):
        if self.progress is not None:
            self.progress(message)

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

    def _wait_family(self, family, mode=None, timeout=9):
        consecutive = 0
        families = (family,) if isinstance(family,str) else family
        desired = DevMode.from_buffer_copy(mode) if mode is not None else None
        def ready():
            nonlocal consecutive
            try:
                signal = self.adb.read_input_signal()
                state = signal['picture']
                matches = (picture_signal_family(state.get('g_video__picture_mode'),state.get('g_dovi_info__')) in families
                           and not signal['lost'])
                if desired is not None:
                    matches = (matches and signal_matches(signal,desired.width,desired.height,desired.hz)
                               and signal_matches(self.windows.signal(),desired.width,desired.height,desired.hz))
            except (OSError,RuntimeError):
                consecutive = 0
                raise
            consecutive = consecutive+1 if matches else 0
            return consecutive >= 2
        message = ('未确认杜比输入，请检查 Windows HDR 页的杜比模式开关及系统杜比支持'
                   if families == ('Dolby Vision',) else '等待目标屏 '+' / '.join(families)+' 输入稳定超时')
        self._wait(ready,message,timeout=timeout)

    def _wait_link(self):
        previous, since = None, time.monotonic()
        observed = '尚未取得可用的输入读数'
        def ready():
            nonlocal previous, since, observed
            try:
                signal = self.windows.signal()
                hdr = self.windows.hdr_enabled()
                input_signal = self.adb.read_input_signal()
                native = input_signal['picture']
                family = picture_signal_family(native.get('g_video__picture_mode'),native.get('g_dovi_info__'))
                observed = (f"Windows {signal['width']}×{signal['height']} {signal['hz']:.3f}Hz；"
                            f"输入 {input_signal.get('width','?')}×{input_signal.get('height','?')} "
                            f"{input_signal.get('hz','?')}Hz、{family}、丢失信号={input_signal['lost']}")
            except (OSError,RuntimeError):
                previous, since = None, time.monotonic()
                raise
            snapshot = (signal['width'],signal['height'],signal['hz'],hdr,family)
            # A cached Windows color space and the actual HDMI input can differ.
            # Waiting for them to agree here would prevent the HDR repair below.
            matches = (not input_signal['lost'] and family in ('SDR','HDR','Dolby Vision')
                       and signal_matches(signal,input_signal['width'],input_signal['height'],input_signal['hz']))
            if not matches or snapshot != previous:
                since = time.monotonic()
            previous = snapshot if matches else None
            return matches and time.monotonic()-since >= .5
        try:
            self._wait(ready,'等待目标屏重新连接并稳定超时')
        except RuntimeError as error:
            raise RuntimeError(str(error)+'；'+observed) from error

    def _restore_output(self, mode, expected_dolby, family_timeout=9):
        """Respect the saved HDR intent after Windows restores an EDID's state."""
        self._stage('等待显示器连接稳定')
        self._wait_mode(mode)
        self._wait_link()
        family = self._output_family(expected_dolby)
        families = (family,) if isinstance(family,str) else family
        if self.windows.hdr_enabled() != self.old_hdr:
            self._stage('恢复 HDR 状态' if self.old_hdr else '恢复 SDR 状态')
            self.windows.set_hdr(self.old_hdr)
        else:
            native = self.adb.read_picture_state()
            if picture_signal_family(native.get('g_video__picture_mode'),native.get('g_dovi_info__')) not in families:
                try:
                    self._wait_family(family,timeout=min(2,family_timeout))
                except RuntimeError:
                    self._stage('同步实际 HDR 输出' if self.old_hdr else '同步实际 SDR 输出')
                    self.windows.set_hdr(self.old_hdr)
        self._wait_family(family,timeout=family_timeout)
        desired = DevMode.from_buffer_copy(mode)
        if not signal_matches(self.windows.signal(),desired.width,desired.height,desired.hz):
            self._stage('恢复目标分辨率和刷新率')
            self._wait_mode(mode)
            self.windows.apply_mode(mode)
        self._stage('核对实际画面信号')
        self._wait_family(family,mode,timeout=family_timeout)

    def _output_family(self, expected_dolby):
        if not self.old_hdr:
            return 'SDR'
        # The native EDIDs can retain Windows' Dolby preference too. Installing
        # or removing the PC capability profile does not override that choice.
        if expected_dolby is None:
            return ('HDR','Dolby Vision')
        return 'Dolby Vision' if expected_dolby else 'HDR'

    def _prepare(self):
        if self.adb.get('mitv.tvplayer.hdmi.last.source',check=True).strip() not in ('23','24'):
            raise RuntimeError('PC 杜比和自动 320Hz 目前仅支持 HDMI 输入')
        firmware = self.adb.shell('getprop ro.build.version.incremental',check=True).strip()
        if firmware != 'OS3.0.109.0.UFFMAMN':
            raise RuntimeError('此 PC 杜比配置仅完成 OS3.0.109.0.UFFMAMN 固件验证')
        self.before = self.adb.jni_batch_get_or_single(GUARD_KEYS,check=True)
        if self.before[EDID] not in (3,5) or self.before[FS] != 1:
            raise RuntimeError('请先开启 FreeSync；当前兼容配置仅验证了 FreeSync 开启的 HDMI 档位')
        if picture_signal_family(self.before.get('g_video__picture_mode'),self.before.get('g_dovi_info__')) not in ('SDR','HDR','Dolby Vision'):
            raise RuntimeError('目标屏输入信号未确认，请刷新后重试')
        self.old_hdr = self.windows.hdr_enabled()
        self.old_mode = self.windows.current_mode()
        self.old_signal = self.windows.signal()

    def _check_signal(self, mode, expected_dolby):
        desired = DevMode.from_buffer_copy(mode)
        def ready():
            input_signal = self.adb.read_input_signal()
            state = input_signal['picture']
            family = self._output_family(expected_dolby)
            families = (family,) if isinstance(family,str) else family
            return (not input_signal['lost'] and signal_matches(input_signal,desired.width,desired.height,desired.hz)
                    and signal_matches(self.windows.signal(),desired.width,desired.height,desired.hz)
                    and picture_signal_family(state.get('g_video__picture_mode'),state.get('g_dovi_info__')) in families
                    and self.windows.hdr_enabled() == self.old_hdr)
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
        self._stage('正在恢复切换前的显示状态')
        errors = []
        if self.registry_change:
            try:self.registry_change.finish(False)
            except Exception as error:errors.append(str(error))
            self.registry_change = None
        try:
            self._native_edid(3 if self.before[EDID] == 5 else 5)
            time.sleep(.6)
            self._native_edid(self.before[EDID])
            self._restore_output(self.old_mode,bool(self.before['g_dovi_info__']))
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
            self._stage('更新杜比视界支持')
            self.registry_change = EdidChange(self.device_id,action,profile,refresh='hdmi')
            self.registry_change.start(self._heartbeat)
            expected = None
            if wanted_edid == self.before[EDID]:
                self._native_edid(3 if wanted_edid == 5 else 5)
                time.sleep(.7)
            self._native_edid(wanted_edid)
            expected_edid = profile if action == 'on' else None
            if action == 'restore':
                expected_edid = state.get('original_blocks') or None
            self._stage('核对 Windows 已读取的显示器能力')
            self._wait(lambda:edid_is_loaded(self.device_id,state['raw'],expected_edid),
                       'Windows 尚未读取新的显示器能力，已停止切换')
            try:
                self._restore_output(wanted_mode,expected)
            except RuntimeError:
                if not self.old_hdr:
                    raise
                self._stage('重新同步 HDR 输出')
                self.windows.set_hdr(False)
                self._wait_family('SDR')
                self._restore_output(wanted_mode,expected)
            current = self._check_signal(wanted_mode,expected)
            self.registry_change.finish(True)
            self.registry_change = None
            self.recovery.stop()
            return {'native':current,'signal':self.windows.signal(),'profile':action}
        except Exception as error:
            try:self._recover()
            except Exception as recovery_error:raise RuntimeError(str(error)+'; '+str(recovery_error)) from error
            raise

    def set_320(self, enabled, normal_mode=None):
        self._prepare()
        state = read_profile_state(self.device_id)
        if enabled and state['values'] and not state['compatible']:
            raise RuntimeError('先开启“杜比视界 PC”以使用兼容 320Hz 的配置')
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
            self._stage('切换刷新率档位')
            self.adb.monitor_refresh_mode(bool(enabled))
            self._wait_mode(None if enabled else target_mode)
            self._heartbeat()
            if enabled:target_mode = self.windows.find_mode(1920,1080,320)
            expected = None
            self._restore_output(target_mode,expected)
            current = self._check_signal(target_mode,expected)
            self.recovery.stop()
            return {'native':current,'signal':self.windows.signal(),'normal_mode':self.old_mode if enabled and self.before[EDID]==3 else None}
        except Exception as error:
            try:self._recover()
            except Exception as recovery_error:raise RuntimeError(str(error)+'; '+str(recovery_error)) from error
            raise
