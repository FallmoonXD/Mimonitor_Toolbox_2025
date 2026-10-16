"""Display mode/HDR operations scoped to one exact Windows monitor interface."""

import ctypes as c
import ctypes.wintypes as w
import sys


class Luid(c.Structure):
    _fields_ = [('low', w.DWORD), ('high', w.LONG)]


class Point(c.Structure):
    _fields_ = [('x', w.LONG), ('y', w.LONG)]


class Rational(c.Structure):
    _fields_ = [('numerator', w.UINT), ('denominator', w.UINT)]


class Region(c.Structure):
    _fields_ = [('width', w.UINT), ('height', w.UINT)]


class VideoSignal(c.Structure):
    _fields_ = [('pixel_rate', c.c_ulonglong), ('h_sync', Rational), ('v_sync', Rational),
                ('active', Region), ('total', Region), ('video_standard', w.UINT), ('scanline', w.UINT)]


class ModeData(c.Union):
    _fields_ = [('signal', VideoSignal), ('raw', c.c_byte * 48)]


class ModeInfo(c.Structure):
    _fields_ = [('kind', w.UINT), ('id', w.UINT), ('adapter', Luid), ('data', ModeData)]


class SourceInfo(c.Structure):
    _fields_ = [('adapter', Luid), ('id', w.UINT), ('mode_index', w.UINT), ('flags', w.UINT)]


class TargetInfo(c.Structure):
    _fields_ = [('adapter', Luid), ('id', w.UINT), ('mode_index', w.UINT),
                ('technology', w.UINT), ('rotation', w.UINT), ('scaling', w.UINT),
                ('refresh', Rational), ('scanline', w.UINT), ('available', w.BOOL), ('flags', w.UINT)]


class PathInfo(c.Structure):
    _fields_ = [('source', SourceInfo), ('target', TargetInfo), ('flags', w.UINT)]


class Header(c.Structure):
    _fields_ = [('kind', w.UINT), ('size', w.UINT), ('adapter', Luid), ('id', w.UINT)]


class TargetName(c.Structure):
    _fields_ = [('header', Header), ('flags', w.UINT), ('technology', w.UINT),
                ('manufacturer', w.WORD), ('product', w.WORD), ('connector', w.UINT),
                ('friendly_name', w.WCHAR * 64), ('device_path', w.WCHAR * 128)]


class SourceName(c.Structure):
    _fields_ = [('header', Header), ('name', w.WCHAR * 32)]


class SetAdvancedColor(c.Structure):
    _fields_ = [('header', Header), ('enabled', w.UINT)]


class DevMode(c.Structure):
    _fields_ = [('device', w.WCHAR * 32), ('spec', w.WORD), ('driver', w.WORD),
                ('size', w.WORD), ('extra', w.WORD), ('fields', w.DWORD),
                ('position', Point), ('orientation', w.DWORD), ('fixed_output', w.DWORD),
                ('color', c.c_short), ('duplex', c.c_short), ('y_resolution', c.c_short),
                ('tt_option', c.c_short), ('collate', c.c_short), ('form', w.WCHAR * 32),
                ('log_pixels', w.WORD), ('bits', w.DWORD), ('width', w.DWORD),
                ('height', w.DWORD), ('display_flags', w.DWORD), ('hz', w.DWORD),
                ('icm_method', w.DWORD), ('icm_intent', w.DWORD), ('media', w.DWORD),
                ('dither', w.DWORD), ('reserved1', w.DWORD), ('reserved2', w.DWORD),
                ('panning_width', w.DWORD), ('panning_height', w.DWORD)]


def signal_matches(signal, width, height, hz):
    return (signal.get('width') == width and signal.get('height') == height
            and abs(signal.get('hz', 0) - hz) < .12)


class WindowsDisplay:
    def __init__(self, device_id):
        if sys.platform != 'win32':
            raise RuntimeError('此功能需要 Windows 11')
        self.device_id = str(device_id)
        self.api = c.WinDLL('user32', use_last_error=True)
        self.api.GetDisplayConfigBufferSizes.argtypes = [w.UINT, c.POINTER(w.UINT), c.POINTER(w.UINT)]
        self.api.QueryDisplayConfig.argtypes = [w.UINT, c.POINTER(w.UINT), c.POINTER(PathInfo),
                                               c.POINTER(w.UINT), c.POINTER(ModeInfo), c.c_void_p]
        self.api.DisplayConfigGetDeviceInfo.argtypes = [c.POINTER(Header)]
        self.api.DisplayConfigSetDeviceInfo.argtypes = [c.POINTER(Header)]
        self.api.EnumDisplaySettingsW.argtypes = [w.LPCWSTR, w.DWORD, c.POINTER(DevMode)]
        self.api.ChangeDisplaySettingsExW.argtypes = [w.LPCWSTR, c.POINTER(DevMode), w.HWND, w.DWORD, c.c_void_p]
        self.api.ChangeDisplaySettingsExW.restype = w.LONG

    def _path(self):
        # Topology may change between size and data calls during HDMI hotplug.
        for _ in range(4):
            count, mode_count = w.UINT(), w.UINT()
            error = self.api.GetDisplayConfigBufferSizes(2, c.byref(count), c.byref(mode_count))
            if error:
                raise OSError(error, '无法读取显示器路径')
            paths, modes = (PathInfo * count.value)(), (ModeInfo * mode_count.value)()
            error = self.api.QueryDisplayConfig(2, c.byref(count), paths, c.byref(mode_count), modes, None)
            if error == 122:
                continue
            if error:
                raise OSError(error, '无法读取活动显示器配置')
            matches = []
            for path in paths[:count.value]:
                name = TargetName()
                name.header = Header(2, c.sizeof(name), path.target.adapter, path.target.id)
                error = self.api.DisplayConfigGetDeviceInfo(c.byref(name.header))
                if error:
                    raise OSError(error, '无法确认显示器身份')
                if name.device_path.casefold() == self.device_id.casefold():
                    matches.append(path)
            if len(matches) != 1:
                raise RuntimeError('目标显示器未连接，或正在切换显示路径')
            return matches[0], modes[:mode_count.value]
        raise RuntimeError('显示器配置持续变化，请稍后重试')

    def _source(self, path):
        name = SourceName()
        name.header = Header(1, c.sizeof(name), path.source.adapter, path.source.id)
        error = self.api.DisplayConfigGetDeviceInfo(c.byref(name.header))
        if error:
            raise OSError(error, '无法读取目标显示器名称')
        return name.name

    def current_mode(self):
        path, _ = self._path()
        mode = DevMode()
        mode.size = c.sizeof(mode)
        if not self.api.EnumDisplaySettingsW(self._source(path), 0xFFFFFFFF, c.byref(mode)):
            raise RuntimeError('无法读取目标显示器当前分辨率')
        return bytes(mode)

    def hdr_enabled(self):
        path, _ = self._path()
        from .windows import query_windows_hdr_enabled
        state = query_windows_hdr_enabled(target_device_name=self._source(path))
        if state is None:
            raise RuntimeError('无法确认目标屏实际 HDR 色彩空间')
        return state

    def set_hdr(self, enabled):
        # Windows can retain AdvancedColorEnabled across HDMI mode changes while
        # the new timing is still SDR. An explicit request is required here.
        path, _ = self._path()
        request = SetAdvancedColor()
        request.header = Header(10, c.sizeof(request), path.target.adapter, path.target.id)
        request.enabled = int(bool(enabled))
        error = self.api.DisplayConfigSetDeviceInfo(c.byref(request.header))
        if error:
            raise OSError(error, '无法切换目标屏 HDR')

    def signal(self):
        path, modes = self._path()
        index = path.target.mode_index
        if index >= len(modes) or modes[index].kind != 2:
            raise RuntimeError('当前实际输出时序尚不可用')
        signal = modes[index].data.signal
        if not signal.v_sync.denominator:
            raise RuntimeError('当前刷新率尚不可用')
        return {'width': signal.active.width, 'height': signal.active.height,
                'hz': signal.v_sync.numerator / signal.v_sync.denominator}

    def apply_mode(self, data):
        mode = DevMode.from_buffer_copy(data)
        path, _ = self._path()
        name = self._source(path)
        tested = self.api.ChangeDisplaySettingsExW(name, c.byref(mode), None, 2, None)
        if tested:
            raise RuntimeError(f'目标显示器不接受该分辨率，Windows 返回 {tested}')
        error = self.api.ChangeDisplaySettingsExW(name, c.byref(mode), None, 0, None)
        if error:
            raise RuntimeError(f'切换目标显示器分辨率失败，Windows 返回 {error}')

    def find_mode(self, width, height, hz):
        path, _ = self._path()
        name = self._source(path)
        old = DevMode.from_buffer_copy(self.current_mode())
        for index in range(4096):
            mode = DevMode()
            mode.size = c.sizeof(mode)
            if not self.api.EnumDisplaySettingsW(name, index, c.byref(mode)):
                break
            if (mode.width, mode.height, mode.hz, mode.bits) == (width, height, hz, 32):
                mode.position = old.position
                mode.fields |= 0x20
                return bytes(mode)
        return None

    def select_mode(self, width, height, hz):
        mode = self.find_mode(width, height, hz)
        if mode is not None:
            self.apply_mode(mode)
            return
        raise RuntimeError(f'目标显示器未提供 {width}×{height}、{hz}Hz')
